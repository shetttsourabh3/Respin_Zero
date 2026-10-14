import os

import pytest

from conftest import mod

V = mod("vcs")
CMP = mod("compare")
C = mod("checks")
pytestmark = pytest.mark.skipif(not V.git_exe(), reason="git not installed")

SCH = '''(kicad_sch (version 20250114)
  (lib_symbols (symbol "Device:R" (property "Reference" "R" (at 0 0 0))))
  (symbol (lib_id "Device:R") (at 10 10 0)
    (property "Reference" "R1" (at 0 0 0)) (property "Value" "{r1}" (at 0 0 0))
    (property "Footprint" "Resistor_SMD:R_0603_1608Metric" (at 0 0 0))
    (instances (project "demo" (path "/x" (reference "R1") (unit 1)))))
  {extra}
  (symbol (lib_id "power:GND") (at 0 0 0) (property "Reference" "#PWR01" (at 0 0 0)) (property "Value" "GND" (at 0 0 0)))
)'''
U1 = '''(symbol (lib_id "MCU:ESP32-C3") (at 20 20 0)
    (property "Reference" "U1" (at 0 0 0)) (property "Value" "ESP32-C3" (at 0 0 0))
    (property "Footprint" "Package_DFN_QFN:QFN-32" (at 0 0 0)) (property "MPN" "ESP32-C3FH4" (at 0 0 0)))'''


def finding(t, tier, uuid):
    return C.Finding("DRC", t, tier, f"{t} problem", "fix it", items=[{"description": "x", "uuid": uuid}])


def test_compare_versions(tmp_path, board_copy, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    board_copy("k10_ai.kicad_pcb")
    sch = tmp_path / "demo.kicad_sch"
    sch.write_text(SCH.format(r1="10k", extra=""))
    r = V.Repo(str(tmp_path))
    r.init()
    r.set_identity("T", "t@example.com")
    a, b, c = finding("clearance", "Blocks fabrication", "u1"), finding("silk", "Cosmetic", "u2"), \
        finding("courtyard", "Reliability risk", "u3")
    CMP.write_snapshot(str(tmp_path), {"ERC/DRC": ([a, b], [])})
    r.save("first", {})
    sch.write_text(SCH.format(r1="4.7k", extra=U1))
    CMP.write_snapshot(str(tmp_path), {"ERC/DRC": ([c], [b])})
    r.save("second", {}, tag="rev-B")
    log = r.log()
    res = CMP.compare(CMP.snapshot(r, log[0].hash), CMP.snapshot(r, log[1].hash))
    assert res["parts_added"] == ["U1"] and res["parts_removed"] == []
    assert res["parts_changed"] == [("R1", ["value: 10k -> 4.7k"])]
    f = res["findings"]
    assert [x["type"] for x in f["fixed"]] == ["clearance"]
    assert [x["type"] for x in f["waived"]] == ["silk"]
    assert [x["type"] for x in f["new"]] == ["courtyard"]
    text = CMP.report_text(res, "first", "rev-B", r.diff_names(log[0].hash, log[1].hash))
    assert "fixed 1 (1 blocking)" in text and "demo.kicad_sch" in text
    # against the current files on disk
    sch.write_text(SCH.format(r1="4.7k", extra=""))
    res = CMP.compare(CMP.snapshot(r, log[1].hash), CMP.snapshot(r, None))
    assert res["parts_removed"] == ["U1"]


def test_parts_skip_power_symbols_and_library():
    p = CMP.parts_from_schematics([SCH.format(r1="1k", extra=U1)])
    assert set(p) == {"R1", "U1"} and p["U1"]["mpn"] == "ESP32-C3FH4"
