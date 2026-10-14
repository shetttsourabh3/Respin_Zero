"""Schematic review rules and the AI reply checks."""
import json

from conftest import mod

SR = mod("schreview")
AR = mod("aireview")


def types(findings):
    return {(f.tier, f.type) for f in findings}


def test_buggy_esp32_findings(design):
    f, matched, _ = SR.review(design("buggy_esp"), SR.load_profiles(None))
    t = {x for _, x in types(f)}
    for expected in ("crystal_wrong_frequency", "led_no_resistor", "strap_pin_wrong", "usbc_cc_shared",
                     "i2c_no_pullup", "usb_no_esd", "missing_capacitor"):
        assert expected in t
    assert matched


def test_clean_module_has_no_findings(design):
    f, _, _ = SR.review(design("clean_module"), SR.load_profiles(None))
    assert f == []


def test_profiles_rp2040_stm32(design):
    assert ("Blocks fabrication", "pin_not_grounded") in types(SR.review(design("rp2040"), SR.load_profiles(None))[0])
    assert ("Blocks fabrication", "boot_pin_floating") in types(SR.review(design("stm32"), SR.load_profiles(None))[0])


def test_ai_reply_is_checked_against_design(design):
    d = design("buggy_esp")
    ref = sorted(c.ref for c in d.comps.values() if c.kind == "IC")[0]
    reply = {"findings": [
        {"severity": "block", "title": "Invented part", "detail": "x", "action": "y", "refs": ["U999"], "confidence": "high"},
        {"severity": "block", "title": "Unsure", "detail": "x", "action": "y", "refs": [ref], "confidence": "low"},
    ], "summary": "s"}
    found, dropped, summary = AR.parse_reply("```json\n" + json.dumps(reply) + "\n```", d)
    assert len(found) == 1 and len(dropped) == 1 and summary == "s"
    assert found[0].tier != "Blocks fabrication"          # low confidence is never 'blocks'


def test_summary_carries_part_numbers(design):
    d = design("buggy_esp")
    c = next(c for c in d.comps.values() if c.kind == "IC")
    c.fields["mpn"] = "TEST-MPN-123"
    text, _ = AR.summarize(d)
    assert "MPN=TEST-MPN-123" in text
