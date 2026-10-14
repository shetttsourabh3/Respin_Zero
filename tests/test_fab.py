import csv
import json
import os
import zipfile

import pytest

from conftest import mod

F = mod("fab")
R = mod("rules")
C = mod("checks")

CLI = r'''
import sys, os, json
a = sys.argv[1:]
open(os.environ["CLI_LOG"], "a").write(json.dumps(a) + "\n")
out = a[a.index("-o") + 1]
if a[:3] == ["pcb", "export", "gerbers"]:
    for l in a[a.index("-l") + 1].split(","):
        open(os.path.join(out, "demo-" + l.replace(".", "_") + ".gbr"), "w").write("G04*")
elif a[:3] == ["pcb", "export", "drill"]:
    open(os.path.join(out, "demo-PTH.drl"), "w").write("M48")
    open(os.path.join(out, "demo-NPTH.drl"), "w").write("M48")
elif a[:3] == ["pcb", "export", "pos"]:
    open(out, "w").write('Ref,Val,Package,PosX,PosY,Rot,Side\nU1,ESP32-C3,QFN-32,100.5,50.25,90,top\nC1,10u,C_0603,101,52,0,bottom\n')
elif a[:3] == ["pcb", "export", "step"]:
    open(out, "w").write("ISO-10303-21;")
'''


@pytest.fixture
def cli(stub_bin, tmp_path, monkeypatch):
    p = stub_bin("kicad-cli", CLI)
    monkeypatch.setenv("CLI_LOG", str(tmp_path / "cli.log"))
    monkeypatch.setattr(C, "find_kicad_cli", lambda: p)
    return lambda: [json.loads(l) for l in open(tmp_path / "cli.log")]


def paths_for(board):
    base = os.path.splitext(board)[0]
    return {"board": board, "sch": base + ".kicad_sch", "dru": base + ".kicad_dru", "dir": os.path.dirname(board)}


def test_presets_and_mapping():
    ps = F.load_presets()
    assert {"jlcpcb", "pcbway", "generic"} <= {p["id"] for p in ps}
    assert F.preset_for("jlcpcb", ps)["id"] == "jlcpcb"
    assert F.preset_for("lioncircuits", ps)["id"] == "generic"


def test_preflight_blocks_unchecked_or_stale(board_copy):
    p = paths_for(board_copy("k10_ai.kicad_pcb"))
    req = R.Requirements()
    chk = F.preflight(p, req, {"sch": None, "check": None, "power": None})
    assert any(c.title == "ERC and DRC not run" and c.level == F.FAIL for c in chk)
    old = {"counts": {"Blocks fabrication": 0}, "ran_at": 0, "ran": ("ERC", "DRC")}
    chk = F.preflight(p, req, {"check": old})
    assert any("older than the saved files" in c.title for c in chk)
    fresh = {"counts": {"Blocks fabrication": 2}, "ran_at": 9e12, "ran": ("ERC", "DRC")}
    assert any("2 blocking" in c.title for c in F.blocking(F.preflight(p, req, {"check": fresh})))


def test_export_jlcpcb(board_copy, cli, design, tmp_path):
    board = board_copy("k10_ai.kicad_pcb")
    d = design("buggy_esp")
    u = next(c for c in d.comps.values() if c.kind == "IC")
    u.fields["lcsc"] = "C2838500"
    preset = F.preset_for("jlcpcb", F.load_presets())
    out = str(tmp_path / "fab" / "rev-A")
    files, notes = F.export(paths_for(board), R.Requirements(), preset, out, {"bom": True, "cpl": True, "step": True},
                            design=d, version_label="rev-A")
    names = [os.path.basename(f) for f in files]
    assert "demo-rev-A-gerbers.zip" in names and "FAB_NOTE.txt" in names and "demo.step" in names
    z = zipfile.ZipFile(os.path.join(out, "demo-rev-A-gerbers.zip")).namelist()
    assert "demo-Edge_Cuts.gbr" in z and "demo-PTH.drl" in z
    calls = cli()
    g = next(c for c in calls if c[2] == "gerbers")
    assert "--no-x2" in g and "--no-netlist" in g             # JLCPCB format
    assert "--excellon-separate-th" in next(c for c in calls if c[2] == "drill")
    bom = list(csv.reader(open(next(f for f in files if "BOM" in f))))
    assert bom[0] == ["Comment", "Designator", "Footprint", "LCSC Part #"]
    assert any(r[3] == "C2838500" for r in bom[1:])
    cpl = list(csv.reader(open(next(f for f in files if "CPL" in f))))
    assert cpl[0] == ["Designator", "Mid X", "Mid Y", "Layer", "Rotation"]
    assert cpl[1] == ["U1", "100.5mm", "50.25mm", "Top", "90"] and cpl[2][3] == "Bottom"
    assert "rev-A" in open(os.path.join(out, "FAB_NOTE.txt")).read()


def test_export_generic_keeps_x2(board_copy, cli, tmp_path):
    board = board_copy("k10_ai.kicad_pcb")
    F.export(paths_for(board), R.Requirements(), F.preset_for("", F.load_presets()), str(tmp_path / "o"), {})
    g = next(c for c in cli() if c[2] == "gerbers")
    assert "--no-x2" not in g and "--no-netlist" not in g


def test_production_export_keeps_other_files(board_copy, cli, design, tmp_path):
    board = board_copy("k10_ai.kicad_pcb")
    out = tmp_path / "production"
    out.mkdir()
    (out / "my_notes.txt").write_text("keep me")
    preset = F.preset_for("", F.load_presets())
    for _ in range(2):                                   # second run replaces, never piles up
        files, _ = F.export(paths_for(board), R.Requirements(), preset, str(out),
                            {"bom": True, "cpl": True, "raw_pos": True}, design=design("buggy_esp"),
                            clean=False, note=False)
    names = sorted(os.listdir(out))
    assert "my_notes.txt" in names and "FAB_NOTE.txt" not in names
    assert {"demo-gerbers.zip", "demo-pos.csv", "demo-BOM-generic.csv", "demo-CPL-generic.csv", "gerbers"} <= set(names)
