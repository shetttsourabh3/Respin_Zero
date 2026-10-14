import os
import subprocess
import zipfile

import pytest

from conftest import mod

V = mod("vcs")
pytestmark = pytest.mark.skipif(not V.git_exe(), reason="git not installed")


@pytest.fixture
def repo(tmp_path, board_copy, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    board_copy()
    (tmp_path / "demo.kicad_sch").write_text("(kicad_sch)")
    (tmp_path / "demo.kicad_prl").write_text("{}")
    r = V.Repo(str(tmp_path))
    r.init()
    r.set_identity("Test", "t@example.com")
    return r


def test_ignore_and_versions(repo, tmp_path):
    assert ".gitignore" in open(tmp_path / ".gitignore").read() or "kicad_prl" in open(tmp_path / ".gitignore").read()
    assert "demo.kicad_prl" not in [p for _, p in repo.changes()]
    repo.save("first", {"Milestone": "Design started"})
    (tmp_path / "demo.kicad_sch").write_text("(kicad_sch 2)")
    repo.save("fixed", {"Review-Blocks": 0, "Review-Risks": 2}, tag="v0.1")
    with pytest.raises(V.GitError):
        repo.save("nothing", {})
    repo.save("to fab", {"Milestone": "Sent to fab", "Review-Blocks": 0, "Review-Risks": 0}, tag="rev-A")
    log = repo.log()
    assert [c.subject for c in log] == ["first", "fixed", "to fab"]
    assert log[1].tags == ["v0.1"] and log[1].state == "risk" and log[2].state == "ok"
    assert log[0].milestone == "Design started"


def test_push_export_and_bad_names(repo, tmp_path):
    repo.save("first", {})
    with pytest.raises(V.GitError):
        repo.tag("has space", "x")
    remote = tmp_path.parent / (tmp_path.name + "_remote.git")
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    repo.set_remote(str(remote))
    repo.push()
    assert repo.ahead_behind() == (0, 0)
    out = str(tmp_path / "v.zip")
    repo.export(repo.log()[0], out)
    assert "demo.kicad_pcb" in zipfile.ZipFile(out).namelist()
