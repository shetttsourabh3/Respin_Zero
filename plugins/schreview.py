"""Schematic review for embedded designs: generic checks + chip-profile rules.

Every finding names the parts and pins, says what to do, and why. Pure Python.
"""
import glob
import json
import math
import os
import re

from . import checks as C
from .schnet import parse_value, fmt_si, norm

HERE = os.path.dirname(__file__)
TIER = {"block": C.BLOCK, "risk": C.RISK, "cosmetic": C.COSMETIC}
I2C = re.compile(r"(^|[_/\-])(I2C\d*_?)?(SDA|SCL)\d*($|[_\-])")
USB_DATA = re.compile(r"(^|[_/\-])(USB\d*_?)?(D[+\-PN]|DP|DM|DPLUS|DMINUS)(\d*)$")
ESD_PART = re.compile(r"ESD|TVS|USBLC|PESD|TPD\d|SRV0|PRTR|IP42|SP05|RCLAMP|SMF|SMAJ|SMBJ|CDSOT|NUP\d|ECMF|SM712|DF5A", re.I)
LED_VF = [(re.compile(r"\b(IR|INFRA)", re.I), 1.3), (re.compile(r"RED|AMBER|ORANGE|YELLOW", re.I), 2.0),
          (re.compile(r"GREEN|BLUE|WHITE|UV|RGB|PINK|PURPLE", re.I), 3.0)]


def _f(tier, type_, desc, action, why, pins_or_refs, section=""):
    items = []
    for p in pins_or_refs:
        if hasattr(p, "label"):
            items.append({"description": p.label(), "ref": p.ref})
        else:
            items.append({"description": str(p), "ref": str(p)})
    return C.Finding("SCH", type_, tier, desc, action, why, section, "", "error", items)


# ====================================================================== profiles

def load_profiles(project_dir=None):
    out = {}
    paths = sorted(glob.glob(os.path.join(HERE, "profiles", "*.json")))
    if project_dir:
        paths += sorted(glob.glob(os.path.join(project_dir, "kicad_review_profiles", "*.json")))
    for p in paths:
        try:
            with open(p, encoding="utf-8") as f:
                prof = json.load(f)
            out[prof["id"]] = prof
        except (OSError, ValueError, KeyError):
            continue
    return list(out.values())


def match_profile(comp, profiles):
    for prof in profiles:
        for pat in prof.get("match", []):
            for text in (comp.part, comp.value):
                if text and re.search(pat, text.strip(), re.I):
                    return prof
    return None


def profile_pins(comp, prof, key):
    pats = [re.compile("^" + p + "$") for p in prof.get("pins", {}).get(key, [key])]
    return [p for p in comp.pins.values() if any(any(rx.match(n) for rx in pats) for n in p.names)]


# ====================================================================== pin helpers

def pin_state(d, pin):
    net = pin.net
    if d.is_floating(net):
        return {"floating": True, "low": False, "high": False, "ups": [], "downs": [], "caps": [], "jumper": False}
    ups, downs = d.pulls(net)
    caps = d.caps_to_ground(net)
    jumper = any(p.ref != pin.ref and d.comps[p.ref].kind in ("J", "SW", "TP") for p in d.pins_on(net))
    return {"floating": False, "low": d.is_ground(net) or bool(downs), "high": d.is_power(net) or bool(ups),
            "tied_low": d.is_ground(net), "tied_high": d.is_power(net),
            "ups": ups, "downs": downs, "caps": caps, "jumper": jumper}


def _cap_list(caps):
    return ", ".join(f"{c.ref} {fmt_si(v, 'F')}" for c, v in caps) or "none"


# ====================================================================== generic checks

def check_decoupling(d, profiled_refs):
    out = []
    by_net = {}
    for c in d.comps_of("IC"):
        if c.ref in profiled_refs:
            continue
        for p in c.pins.values():
            if p.type == "power_in" and d.is_power(p.net):
                by_net.setdefault(p.net, []).append(p)
    for net, pins in sorted(by_net.items()):
        caps = [(c, v) for c, v in d.caps_to_ground(net) if v is not None]
        ics = sorted({p.ref for p in pins})
        if not caps:
            out.append(_f(C.RISK, "no_decoupling",
                          f"{net} feeds {len(pins)} IC power pin(s) ({', '.join(ics[:6])}) but has no capacitor to ground.",
                          "Add one 100 nF ceramic capacitor close to each power pin, and one 1-10 uF bulk capacitor on the rail.",
                          "Without decoupling, supply noise and current spikes cause resets, ADC errors and EMI.", pins[:8], "3.4"))
        elif len(caps) < len(ics):
            out.append(_f(C.COSMETIC, "few_decoupling",
                          f"{net}: {len(ics)} IC(s) ({', '.join(ics[:6])}) share {len(caps)} capacitor(s): {_cap_list(caps)}.",
                          "Give each IC at least one 100 nF capacitor placed next to its power pin.",
                          "A shared capacitor far from a pin does not decouple that pin.", pins[:8], "3.4"))
    return out


def check_i2c(d):
    out = []
    buses = {}
    for net in d.nets:
        tail = net.split("/")[-1].upper()
        m = I2C.search(tail)
        if m and not d.is_floating(net):
            buses.setdefault(m.group(3), []).append(net)
    for line, nets in buses.items():
        for net in nets:
            ups, _ = d.pulls(net)
            pins = [p for p in d.pins_on(net) if d.comps[p.ref].kind == "IC"]
            if len(pins) < 1:
                continue
            if not ups:
                out.append(_f(C.RISK, "i2c_no_pullup", f"I2C line {net} has no pull-up resistor.",
                              "Add a pull-up to the bus supply: 4.7 kOhm for 100 kHz, 2.2 kOhm for 400 kHz (typical).",
                              "I2C outputs are open-drain. Internal pull-ups (20-50 kOhm) are too weak for reliable edges.",
                              pins[:6]))
                continue
            vals = [v for _, v, _ in ups if v]
            if not vals:
                continue
            r = 1 / sum(1 / v for v in vals)
            vbus = max([d.voltage(o) for _, _, o in ups] + [3.3])
            if vbus / r > 3e-3:
                out.append(_f(C.RISK, "i2c_pullup_strong",
                              f"I2C line {net}: pull-up {fmt_si(r, 'Ohm')} ({len(vals)} in parallel) sinks {vbus / r * 1000:.1f} mA at {vbus:g} V.",
                              "Use fewer or larger pull-ups. The I2C standard limits the sink current to 3 mA.",
                              "Too strong a pull-up stops devices from pulling the line low enough.",
                              [r_ for r_, _, _ in ups]))
            elif r > 10e3:
                out.append(_f(C.COSMETIC, "i2c_pullup_weak", f"I2C line {net}: pull-up {fmt_si(r, 'Ohm')} is weak.",
                              "For 400 kHz use about 2.2 kOhm; 10 kOhm works only for short, slow buses.",
                              "Slow rising edges cause errors at high speed or with long wires.", [r_ for r_, _, _ in ups]))
    return out


def check_usb_c(d):
    out = []
    for c in d.comps_of("J"):
        cc = [p for p in c.pins.values() if p.names & {"CC1", "CC2", "CC"}]
        if not cc:
            continue
        nets = {p.net for p in cc if p.net}
        if len(cc) >= 2 and len(nets) == 1 and not d.is_floating(next(iter(nets))):
            out.append(_f(C.BLOCK, "usbc_cc_shared",
                          f"{c.ref}: CC1 and CC2 are connected together.",
                          "Give CC1 and CC2 each their own 5.1 kOhm resistor to ground.",
                          "With one shared resistor, many USB-C chargers and cables do not supply power, or e-marked cables fail.",
                          cc))
            continue
        for p in cc:
            st = pin_state(d, p)
            if st["floating"]:
                out.append(_f(C.BLOCK, "usbc_cc_missing", f"{p.label()} is not connected.",
                              "Add a 5.1 kOhm resistor from each CC pin to ground (USB-C sink).",
                              "Without the CC resistors a USB-C charger does not turn on VBUS.", [p]))
                continue
            if st["ups"] and not st["downs"]:
                continue    # source / DRP design: out of scope
            if any(d.comps[q.ref].kind == "IC" for q in d.pins_on(p.net) if q.ref != c.ref):
                continue    # a USB-PD / CC controller handles it
            if not st["downs"]:
                out.append(_f(C.BLOCK, "usbc_cc_missing", f"{p.label()} has no resistor to ground.",
                              "Add a 5.1 kOhm resistor from this CC pin to ground (USB-C sink).",
                              "Without the CC resistors a USB-C charger does not turn on VBUS.", [p]))
            else:
                v = st["downs"][0][1]
                if v and not (4.59e3 <= v <= 5.61e3):
                    out.append(_f(C.RISK, "usbc_cc_value", f"{p.label()}: pull-down is {fmt_si(v, 'Ohm')}.",
                                  "Use 5.1 kOhm (+-10 %) for a USB-C sink.",
                                  "Other values can be read as a different device type or as no device.",
                                  [st["downs"][0][0]]))
    return out


def check_usb_esd(d):
    out, seen = [], set()
    for net, pins in d.nets.items():
        tail = net.split("/")[-1].upper().replace("USB_", "USB")
        if not USB_DATA.search(tail):
            continue
        conn = [p for p in pins if d.comps[p.ref].kind == "J"]
        if not conn or net in seen:
            continue
        seen.add(net)
        esd = [p for p in pins if d.comps[p.ref].kind in ("D", "IC") and
               ESD_PART.search(d.comps[p.ref].value + " " + d.comps[p.ref].part)]
        if not esd:
            out.append(_f(C.RISK, "usb_no_esd", f"USB data line {net} goes to {conn[0].ref} with no ESD protection.",
                          "Add a low-capacitance USB ESD array (for example USBLC6-2, TPD2E2U06) close to the connector.",
                          "Connectors are touched by people; ESD can destroy the USB pins of the MCU.", conn[:2]))
    return out


def _led_vf(led):
    text = f"{led.value} {led.part} {led.fields.get('color', '')}"
    for rx, vf in LED_VF:
        if rx.search(text):
            return vf, True
    return 2.0, False


def check_leds(d):
    out = []
    for led in d.comps_of("LED"):
        tn = led.two_nets()
        if not tn:
            continue
        a, b = tn
        vf, known = _led_vf(led)
        # direct connection between a supply and ground, no resistor
        if (d.is_power(a) and d.is_ground(b)) or (d.is_power(b) and d.is_ground(a)):
            out.append(_f(C.BLOCK, "led_no_resistor", f"{led.ref} connects {a} to {b} with no resistor.",
                          "Add a series resistor: R = (V supply - V forward) / I.",
                          "The LED current is limited only by the supply. The LED burns out.", [led.ref]))
            continue
        for led_net, other in ((a, b), (b, a)):
            rs = d.parts_between("R", led_net, lambda n: d.is_power(n) or d.is_ground(n))
            if not rs:
                continue
            r, far = rs[0]
            rv = parse_value(r.value, "Ω")
            v = d.voltage(far) if d.is_power(far) else d.voltage(other)
            if not rv or v <= 0:
                break
            i = (v - vf) / rv
            if i > 0.025:
                out.append(_f(C.RISK, "led_current_high",
                              f"{led.ref} current is about {i * 1000:.0f} mA ({v:g} V, {r.ref} {fmt_si(rv, 'Ohm')}, "
                              f"Vf {vf:g} V{'' if known else ' assumed'}).",
                              f"Use about {fmt_si((v - vf) / 0.01, 'Ohm')} for 10 mA, or check the LED and pin limits.",
                              "Most indicator LEDs are rated 20 mA, and many MCU pins only 10-20 mA.", [led.ref, r.ref]))
            break
        else:
            ic_pin = any(d.comps[p.ref].kind == "IC" for n in (a, b) for p in d.pins_on(n))
            if ic_pin and not any(d.parts_between("R", n, lambda x: True) for n in (a, b)):
                out.append(_f(C.RISK, "led_no_resistor", f"{led.ref} has no series resistor.",
                              "Add a series resistor between the LED and the pin or supply.",
                              "The pin or the LED is overloaded without a current limit.", [led.ref]))
    return out


def check_crystals(d, info):
    out = []
    for x in d.comps_of("XTAL"):
        pins = [p for p in x.pins.values() if p.net and not d.is_ground(p.net)]
        if len(pins) != 2:
            continue
        caps = [d.caps_to_ground(p.net) for p in pins]
        if not all(caps):
            out.append(_f(C.RISK, "crystal_no_load_caps", f"{x.ref} ({x.value}) has no load capacitor on "
                          f"{' and '.join(p.net for p, c in zip(pins, caps) if not c)}.",
                          "Add a load capacitor from each crystal pin to ground. "
                          "C = 2 x (CL - Cstray), with CL from the crystal datasheet and Cstray about 3-5 pF.",
                          "Without load capacitors the oscillator can run off-frequency or not start.", [x.ref]))
            continue
        c1, c2 = caps[0][0][1], caps[1][0][1]
        if c1 and c2:
            cl = c1 * c2 / (c1 + c2) + 4e-12
            info.append(f"{x.ref} ({x.value}): load capacitors {fmt_si(c1, 'F')} / {fmt_si(c2, 'F')} give about "
                        f"{cl * 1e12:.1f} pF with 4 pF stray. Compare with CL in the crystal datasheet.")
    return out


# ====================================================================== profile rules

def _mhz(text):
    m = re.search(r"(\d+(?:\.\d+)?)\s*M(?:HZ)?", text.upper())
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+(?:\.\d+)?)\s*K(?:HZ)?", text.upper())
    return float(m.group(1)) / 1000 if m else None


def run_profile(d, comp, prof):
    out = []
    tag = f"{comp.ref} ({prof['name']})"

    def pins(key):
        return profile_pins(comp, prof, key)

    for rule in prof.get("rules", []):
        t, tier = rule["type"], TIER.get(rule.get("tier", "risk"), C.RISK)
        text = rule.get("text", "")
        if t == "supply":
            for p in [p for k in rule["pins"] for p in pins(k)]:
                v = d.voltage(p.net)
                if v and not (rule["min_v"] <= v <= rule["max_v"]):
                    out.append(_f(tier, "supply_out_of_range", f"{p.label()} is on {p.net} ({v:g} V). "
                                  f"{prof['name']} needs {rule['min_v']:g}-{rule['max_v']:g} V.",
                                  "Connect the pin to a supply in the allowed range.",
                                  "Over-voltage destroys the chip; under-voltage gives brown-outs.", [p]))
        elif t == "decoupling":
            for k in rule["pins"]:
                ps = [p for p in pins(k) if d.is_power(p.net)]
                for net in sorted({p.net for p in ps}):
                    n_pins = sum(1 for p in ps if p.net == net)
                    need = min(n_pins, rule.get("max_count", n_pins))
                    small = [(c, v) for c, v in d.caps_to_ground(net) if v and v <= 1.1e-6]
                    if not small:
                        out.append(_f(tier, "no_decoupling", f"{tag}: {k} on {net} has no 100 nF decoupling capacitor.",
                                      f"Put a {rule.get('per_pin_nf', 100)} nF ceramic capacitor next to each {k} pin.",
                                      text or "Missing decoupling causes resets and RF or ADC problems.",
                                      [p for p in ps if p.net == net]))
                    elif len(small) < need:
                        out.append(_f(C.COSMETIC, "few_decoupling",
                                      f"{tag}: {n_pins} {k} pin(s) on {net} share {len(small)} small capacitor(s) ({_cap_list(small)}).",
                                      f"Use one {rule.get('per_pin_nf', 100)} nF capacitor per pin, placed close to it.",
                                      text or "Each pin needs its own local decoupling.", [p for p in ps if p.net == net]))
        elif t in ("bulk", "min_cap"):
            keys = rule.get("pins") or [rule["pin"]]
            min_f = rule.get("min_uf", 1) * 1e-6
            for net in sorted({p.net for k in keys for p in pins(k) if p.net and not d.is_floating(p.net)}):
                caps = d.caps_to_ground(net)
                if not any(v and v >= min_f * 0.95 for _, v in caps):
                    out.append(_f(tier, "missing_capacitor",
                                  f"{tag}: {'/'.join(keys)} on {net} has no capacitor of {fmt_si(min_f, 'F')} or more "
                                  f"(found: {_cap_list(caps)}).",
                                  f"Add a {fmt_si(min_f, 'F')} capacitor from {net} to ground, close to the pin.",
                                  text, [p for k in keys for p in pins(k) if p.net == net][:4]))
        elif t == "strap":
            for p in pins(rule["pin"]):
                st = pin_state(d, p)
                if st["jumper"] and not st.get("tied_low") and not st.get("tied_high"):
                    continue          # button / jumper / test point: the user selects the mode
                if rule.get("bad") == "low" and st["low"]:
                    how = "tied to ground" if st.get("tied_low") else \
                        f"pulled down by {', '.join(r.ref for r, _, _ in st['downs'])}"
                    out.append(_f(tier, "strap_pin_wrong", f"{tag}: {p.label()} is {how}.",
                                  "Remove the pull-down, or put it on a button or jumper.", text, [p]))
                if rule.get("want") == "high" and not st["high"]:
                    out.append(_f(tier, "strap_pin_no_pullup", f"{tag}: {p.label()} has no pull-up.",
                                  "Add a 10 kOhm pull-up to 3.3 V.", text, [p]))
        elif t == "max_cap":
            for p in pins(rule["pin"]):
                big = [(c, v) for c, v in pin_state(d, p)["caps"] if v and v > rule["max_nf"] * 1e-9]
                if big:
                    out.append(_f(tier, "strap_pin_capacitor", f"{tag}: {p.label()} has {_cap_list(big)} to ground.",
                                  f"Keep the capacitance on this pin below {rule['max_nf']:g} nF.", text,
                                  [p] + [c.ref for c, _ in big]))
        elif t == "enable_rc":
            for p in pins(rule["pin"]):
                st = pin_state(d, p)
                if st["floating"]:
                    out.append(_f(C.BLOCK, "enable_floating", f"{tag}: {p.label()} is not connected.",
                                  "Connect a 10 kOhm pull-up to 3.3 V and a 1 uF capacitor to ground.", text, [p]))
                    continue
                if not st["high"]:
                    out.append(_f(tier, "enable_no_pullup", f"{tag}: {p.label()} has no pull-up.",
                                  "Add a 10 kOhm pull-up to 3.3 V.", text, [p]))
                if not st.get("tied_high") and not any(v and v >= rule["min_nf"] * 1e-9 * 0.95 for _, v in st["caps"]):
                    out.append(_f(tier, "enable_no_delay", f"{tag}: {p.label()} has no RC delay capacitor "
                                  f"(found: {_cap_list(st['caps'])}).",
                                  "Add 1 uF from the pin to ground (10 kOhm / 1 uF).", text, [p]))
        elif t == "crystal":
            xp = [p for k in rule["pins"] for p in pins(k)]
            xtals = {q.ref for p in xp if p.net for q in d.pins_on(p.net) if d.comps[q.ref].kind == "XTAL"}
            # also through a series resistor (RP2040 XOUT)
            for p in xp:
                for r, far in d.parts_between("R", p.net, lambda n: True) if p.net else []:
                    xtals |= {q.ref for q in d.pins_on(far) if d.comps[q.ref].kind == "XTAL"}
            for ref in sorted(xtals):
                f = _mhz(d.comps[ref].value)
                if f and abs(f - rule["mhz"]) > 0.001:
                    out.append(_f(tier, "crystal_wrong_frequency", f"{tag}: crystal {ref} is {d.comps[ref].value}; "
                                  f"the chip needs {rule['mhz']:g} MHz.",
                                  f"Use a {rule['mhz']:g} MHz crystal.", text, [ref]))
            if not xtals and all(d.is_floating(p.net) for p in xp) and xp:
                out.append(_f(tier, "crystal_missing", f"{tag}: nothing is connected to the crystal pins.",
                              f"Add a {rule['mhz']:g} MHz crystal with load capacitors.", text, xp))
        elif t == "tie_ground":
            for p in pins(rule["pin"]):
                if not d.is_ground(p.net):
                    out.append(_f(tier, "pin_not_grounded", f"{tag}: {p.label()} is "
                                  f"{'not connected' if d.is_floating(p.net) else 'on ' + p.net}.",
                                  "Connect the pin directly to ground.", text, [p]))
        elif t == "same_net":
            a, b = (pins(k) for k in rule["pins"])
            if a and b and {p.net for p in a} != {b[0].net} and not all(d.is_power(p.net) and d.voltage(p.net) for p in a):
                out.append(_f(tier, "pins_not_connected", f"{tag}: {rule['pins'][0]} is not on the same net as {rule['pins'][1]}.",
                              f"Connect {rule['pins'][0]} to {rule['pins'][1]}.", text, a[:3] + b[:1]))
        elif t == "no_float":
            for p in pins(rule["pin"]):
                if d.is_floating(p.net):
                    out.append(_f(tier, "pin_floating", f"{tag}: {p.label()} is not connected.",
                                  "Connect the pin as the datasheet says.", text, [p]))
        elif t == "boot_pin":
            for p in pins(rule["pin"]):
                st = pin_state(d, p)
                if st["floating"]:
                    out.append(_f(C.BLOCK, "boot_pin_floating", f"{tag}: {p.label()} is not connected.",
                                  "Pull it to ground with 10 kOhm (boot from flash).", text, [p]))
                elif st["high"] and not st["low"] and not st["jumper"]:
                    out.append(_f(C.RISK, "boot_pin_high", f"{tag}: {p.label()} is always high.",
                                  "Pull it low to run from flash; use a jumper or button for the bootloader.",
                                  "With BOOT0 high the chip starts the system bootloader, not your firmware.", [p]))
        elif t == "series_r":
            for k, ohms in zip(rule["pins"], rule["ohms"]):
                for p in pins(k):
                    if d.is_floating(p.net):
                        continue
                    rs = [(r, parse_value(r.value, "Ω")) for r, _ in d.parts_between("R", p.net, lambda n: not d.is_power(n) and not d.is_ground(n))]
                    tol = rule.get("tolerance", 0.25)
                    if not any(v and abs(v - ohms) <= ohms * tol for _, v in rs):
                        out.append(_f(tier, "series_resistor", f"{tag}: {p.label()} has no {ohms:g} Ohm series resistor"
                                      f"{' (found ' + ', '.join(r.ref + ' ' + r.value for r, _ in rs) + ')' if rs else ''}.",
                                      f"Add a {ohms:g} Ohm resistor in series, close to the pin.", text, [p]))
        elif t == "debug":
            ok = False
            for group in rule["any_of"]:
                gp = [pins(k) for k in group]
                if all(ps for ps in gp) and all(_reaches_connector(d, ps[0]) for ps in gp):
                    ok = True
                    break
            if not ok:
                out.append(_f(tier, "no_debug_access", f"{tag}: no programming or debug interface reaches a connector or test point.",
                              "Add a header or test points.", text, [comp.ref]))
    return out


def _reaches_connector(d, pin, hops=1):
    if not pin.net or d.is_floating(pin.net):
        return False
    nets = {pin.net}
    for _ in range(hops):
        for n in list(nets):
            nets |= {far for r, far in d.parts_between("R", n, lambda x: not d.is_power(x) and not d.is_ground(x))}
    return any(d.comps[q.ref].kind in ("J", "TP") for n in nets for q in d.pins_on(n))


# ====================================================================== entry point

def review(d, profiles):
    """Return (findings, matched [(ref, profile name)], notes)."""
    findings, matched, notes = [], [], []
    profiled = set()
    for c in sorted(d.comps.values(), key=lambda c: c.ref):
        if c.kind != "IC":
            continue
        prof = match_profile(c, profiles)
        if prof:
            matched.append((c.ref, prof["name"]))
            profiled.add(c.ref)
            findings += run_profile(d, c, prof)
    findings += check_decoupling(d, profiled)
    findings += check_i2c(d)
    findings += check_usb_c(d)
    findings += check_usb_esd(d)
    findings += check_leds(d)
    findings += check_crystals(d, notes)
    ics = [c for c in d.comps_of("IC")]
    unknown = [c.ref for c in ics if c.ref not in profiled]
    if unknown:
        notes.append(f"{len(unknown)} IC(s) have no chip profile and get only the generic checks: "
                     f"{', '.join(unknown[:12])}{' ...' if len(unknown) > 12 else ''}.")
    if not ics:
        notes.append("No ICs found (reference U, IC or M). Check the reference designators.")
    return findings, matched, notes
