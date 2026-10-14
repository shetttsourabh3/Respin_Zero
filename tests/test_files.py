"""Board-file tools: stackup edit, custom DRC rules kept, waivers."""
import os

from conftest import mod

SF = mod("stackup_file")
D = mod("dru")
PF = mod("pcbfile")


def test_stackup_thickness_edit(board_copy):
    p = board_copy()
    SF.edit_file(p, 1.0, 1, 0.5)
    lines = SF.describe(open(p).read())
    total = sum(float(l.split()[-2]) for l in lines if l.endswith(" mm") and not l.startswith("general"))
    assert abs(total - 1.0) < 0.01
    assert lines[-1] == "general board thickness: 1 mm"


def test_custom_rules_are_kept(tmp_path):
    p = str(tmp_path / "x.kicad_dru")
    D.write(p, "(rule gen1 (constraint clearance (min 0.2mm)))")
    with open(p, "a") as f:
        f.write("\n(rule mine (constraint clearance (min 0.5mm)))\n")
    D.write(p, "(rule gen2 (constraint clearance (min 0.15mm)))")
    text = open(p).read()
    assert "mine" in text and "gen2" in text and "gen1" not in text


def test_board_parse():
    b = PF.parse(open(os.path.join(os.path.dirname(__file__), "data", "k10.kicad_pcb")).read())
    assert len(b.footprints) == 3 and b.layers == ['F.Cu', 'In1.Cu', 'In2.Cu', 'B.Cu']
