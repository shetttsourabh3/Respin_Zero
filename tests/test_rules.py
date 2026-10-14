from conftest import mod

R = mod("rules")
N = mod("netdetect")


def test_ipc2221_spacing_table():
    assert [R.spacing_mm(v, "external") for v in (15, 50, 150, 300)] == [0.1, 0.6, 0.6, 1.25]
    assert [R.spacing_mm(v, "internal") for v in (15, 50, 150, 300)] == [0.05, 0.1, 0.2, 0.2]


def test_ipc2221_conductor_width():
    assert abs(R.track_width_mm(1, 1, True, 10) - 0.300) < 0.005
    assert abs(R.track_width_mm(1, 1, False, 10) - 0.781) < 0.005
    assert R.track_width_mm(2, 1, True, 10) > R.track_width_mm(1, 1, True, 10)
    assert R.track_width_mm(1, 2, True, 10) < R.track_width_mm(1, 1, True, 10)


def test_requirements_json_roundtrip():
    r = R.Requirements()
    r.board_thickness_mm = 1.2
    r.ai_disabled = True
    r2 = R.Requirements.from_json(r.to_json())
    assert r2.board_thickness_mm == 1.2 and r2.ai_disabled


def test_rail_voltage_from_name():
    names = ["+3.3V", "+3V3", "+1.8V", "VBAT", "+5V", "12V_IN", "GND"]
    assert [N.guess_voltage(n) for n in names] == [3.3, 3.3, 1.8, 4.2, 5.0, 12.0, 0.0]


def test_net_classes():
    assert N.classify("GND")[0] == "Ground"
    assert N.classify("+3V3")[0] == "Power"
    assert N.classify("AC_L")[0] == "High voltage"
    assert N.classify("/SDA")[0] == "Signal"
