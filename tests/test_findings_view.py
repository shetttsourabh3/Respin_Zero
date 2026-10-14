import pytest

pytest.importorskip("wx")
from conftest import mod  # noqa: E402

C = mod("checks")
FV = mod("gui.findings_view")


def F(source, type_, desc, items=(), why=""):
    return C.Finding(source, type_, C.RISK, desc, "fix", why, items=list(items))


def test_readable_titles():
    assert FV.title_of(F("SCH", "usbc_cc_shared", "x")) == "USB-C CC1 and CC2 joined"
    assert FV.title_of(F("SCH", "i2c_sda_weak_pullup", "x")) == "I2C sda weak pullup"
    assert FV.title_of(F("AI", "ldo_input", "LDO input exceeds rating: details here")) == "LDO input exceeds rating"
    assert FV.detail_of(F("AI", "x", "Title: the detail")) == "the detail"


def test_where_is_short_and_counts_more():
    f = F("DRC", "clearance", "x", [{"description": "Track [+5V] on F.Cu", "pos": {"x": 1, "y": 2}},
                                    {"description": "Pad 1 of U1"}])
    f.sheet = "/"
    assert FV.where_of(f) == "Track [+5V] on F.Cu  (+1 more)"
    assert FV.part_of(F("SCH", "x", "x", [{"description": "U3 pin 5", "ref": "U3"}])) == "U3"


def test_ai_confidence_shown():
    assert FV.confidence_of(F("AI", "x", "t", why="AI review, confidence low. Check.")) == "low"
