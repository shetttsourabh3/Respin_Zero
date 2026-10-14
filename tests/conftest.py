"""Tests run without KiCad: the package is imported in standalone mode (no pcbnew needed)."""
import importlib
import os
import shutil
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "tests", "data")
os.environ["IPCSTE_STANDALONE"] = "1"
sys.path.insert(0, ROOT)
sys.path.insert(0, DATA)


def mod(name):
    return importlib.import_module("plugins." + name)


@pytest.fixture
def design():
    import designs, gen
    SN = mod("schnet")
    return lambda name: SN.parse_xml(gen.netlist(*getattr(designs, name)()))


@pytest.fixture
def board_copy(tmp_path):
    def make(name="k10.kicad_pcb"):
        p = tmp_path / "demo.kicad_pcb"
        shutil.copy(os.path.join(DATA, name), p)
        (tmp_path / "demo.kicad_pro").write_text("{}")
        return str(p)
    return make


@pytest.fixture
def stub_bin(tmp_path, monkeypatch):
    """A folder put first on PATH, for fake command-line tools."""
    d = tmp_path / "bin"
    d.mkdir()
    monkeypatch.setenv("PATH", str(d) + os.pathsep + os.environ.get("PATH", ""))

    def add(name, body):
        """Write a fake command-line tool. On Windows a script cannot run by itself, so a .cmd launcher
        starts it with this Python (the same way npm installs tools such as claude.cmd)."""
        script = d / (name + ".py")
        script.write_text("#!" + sys.executable + "\n" + body)
        if os.name == "nt":
            launcher = d / (name + ".cmd")
            launcher.write_text(f'@"{sys.executable}" "%~dp0{name}.py" %*\n')
            return str(launcher)
        p = d / name
        p.write_text("#!" + sys.executable + "\n" + body)
        p.chmod(0o755)
        return str(p)
    return add
