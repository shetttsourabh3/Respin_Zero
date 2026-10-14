"""Guess the group, voltage and current of each net from its name."""
import re

_GND = re.compile(r"^(A|D|P|S|C)?GND\w*$|^VSS\w*$|^V-$|^EARTH$|^PE$|^0V$|^COM$")
_HV = re.compile(r"(^|_)(AC|MAINS|LINE|LIVE|NEUTRAL|PHASE|HV|VAC)(_|\d|$)|^L\d?$|^N$|^(115|120|220|230|240)V?(AC)?$")
_PWR = re.compile(r"^\+?-?\d+(\.\d+)?V\d*\w*$|^V(CC|DD|BAT|IN|BUS|SYS|MAIN|USB|SUP|PWR|MOT|LED|CHG|OUT|REG|IO|CORE|BATT|_)\w*$"
                  r"|(^|_)(PWR|POWER|BAT|BATT)(_|$)|^\+[\w.]+$|(^|_)\d+(\.\d+)?V(\d+)?($|_)")
_SIGNAL_SUFFIX = re.compile(r"_(EN|ENABLE|GOOD|PG|OK|SENSE|SNS|FB|DET|INT|IRQ|ALERT|FAULT|FLT|STAT|ON|OFF|CTRL|SW|ADC|MON)\d*$|^(EN|PG|SENSE)_")
_VOLT = re.compile(r"(\d+(?:\.\d+)?)V(\d+)?")


def _clean(name):
    n = name.split("/")[-1].upper()
    return n.lstrip("~{").rstrip("}")


def guess_voltage(name):
    n = _clean(name)
    if _HV.search(n):
        return 340.0  # 240 V AC peak (339 V) rounded up
    m = _VOLT.search(n)
    if m:
        whole, frac = m.group(1), m.group(2)
        if "." in whole or not frac:
            return float(whole)
        return float(f"{whole}.{frac}")
    if "USB" in n or "VBUS" in n:
        return 5.0
    if "BAT" in n:
        return 4.2
    return 0.0


def classify(name):
    """Return (group, voltage_v, current_a) as a starting guess."""
    n = _clean(name)
    if not n or n.startswith("NET-(") or n.startswith("UNCONNECTED"):
        return "Signal", 0.0, 0.0
    if _SIGNAL_SUFFIX.search(n):
        return "Signal", 0.0, 0.0
    if _GND.match(n):
        return "Ground", 0.0, 0.5
    if _HV.search(n):
        return "High voltage", guess_voltage(name), 0.0
    if _PWR.search(n):
        return "Power", guess_voltage(name), 0.5
    return "Signal", 0.0, 0.0


def detect(net_names, known=None):
    """Return a list of NetGroup-like dicts. Values in `known` (net -> NetGroup) win over guesses."""
    known = known or {}
    out = []
    for name in sorted(set(net_names)):
        if not name:
            continue
        if name in known:
            k = known[name]
            out.append({"net": name, "group": k.group, "current_a": k.current_a, "voltage_v": k.voltage_v,
                        "guessed": False})
        else:
            g, v, a = classify(name)
            out.append({"net": name, "group": g, "current_a": a, "voltage_v": v, "guessed": True})
    return out
