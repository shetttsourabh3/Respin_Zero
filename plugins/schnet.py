"""Schematic connectivity from the KiCad XML netlist (kicad-cli sch export netlist --format kicadxml).

Using KiCad's own netlist gets hierarchy, power symbols and buses right. Pure Python.
"""
import os
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from . import netdetect as N

# ---------------------------------------------------------------- values

_MULT = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "μ": 1e-6, "m": 1e-3, "k": 1e3, "K": 1e3,
         "M": 1e6, "G": 1e9, "R": 1.0, "r": 1.0, "": 1.0}


def parse_value(text, unit=""):
    """'100n', '0.1uF', '4u7', '4.7µF 16V', '5K1', '22R', '1M', '470' -> float (SI). None if not a number."""
    if not text:
        return None
    t = text.strip().split()[0].replace(",", ".")
    if unit:
        t = re.sub(re.escape(unit) + r"$", "", t, flags=re.I)
        t = re.sub(r"(?i)ohms?$|Ω$", "", t)
    m = re.match(r"^(\d+)([pnuµμmkKMGRr])(\d+)$", t)          # 4u7, 5K1, 2R2
    if m:
        return float(f"{m.group(1)}.{m.group(3)}") * _MULT[m.group(2)]
    m = re.match(r"^(\d+(?:\.\d+)?)\s*([pnuµμmkKMGRr]?)", t)
    if not m:
        return None
    mult = m.group(2)
    if mult == "m" and unit.upper() == "F":   # 'mF' rarely means milli; keep SI
        pass
    return float(m.group(1)) * _MULT[mult]


def fmt_si(v, unit):
    if v is None:
        return "?"
    for s, f in (("M", 1e6), ("k", 1e3), ("", 1), ("m", 1e-3), ("u", 1e-6), ("n", 1e-9), ("p", 1e-12)):
        if abs(v) >= f * 0.999:
            return f"{v / f:.3g} {s}{unit}"
    return f"{v:.3g} {unit}"


# ---------------------------------------------------------------- model

@dataclass
class Pin:
    ref: str
    num: str
    name: str
    type: str
    net: str = ""

    @property
    def names(self):
        """All normalised names of the pin ('GPIO18/USB_D-' -> {'GPIO18', 'USBD-'})."""
        return {norm(p) for p in re.split(r"[/,]", self.name) if p.strip()} | {norm(self.name)}

    def label(self):
        return f"{self.ref} pin {self.num}" + (f" ({self.name})" if self.name and self.name != self.num else "")


@dataclass
class Comp:
    ref: str
    value: str
    footprint: str = ""
    lib: str = ""
    part: str = ""
    description: str = ""
    fields: dict = field(default_factory=dict)
    pins: dict = field(default_factory=dict)       # num -> Pin

    @property
    def prefix(self):
        return re.match(r"[A-Za-z_#]*", self.ref).group(0).upper()

    @property
    def kind(self):
        p, part, val = self.prefix, self.part.upper(), self.value.upper()
        if p.startswith("#") or self.fields.get("dnp"):
            return "ignore"
        if p in ("R", "RN") or part in ("R", "R_SMALL", "R_US") or part.startswith("R_"):
            return "R"
        if p == "C" or part in ("C", "C_SMALL", "C_POLARIZED", "CP", "C_POLARIZED_SMALL") or part.startswith("C_"):
            return "C"
        if p in ("LED",) or "LED" in part:
            return "LED"
        if p in ("Y", "X", "XTAL") or "CRYSTAL" in part or "RESONATOR" in part:
            return "XTAL"
        if p in ("FB",) or "FERRITE" in part:
            return "FB"
        if p == "L" or part in ("L", "L_SMALL"):
            return "L"
        if p in ("D", "TVS", "ESD"):
            return "D"
        if p in ("J", "P", "CN", "CON", "USB", "X") or "CONN" in part or "USB_C" in part:
            return "J"
        if p in ("TP",) or "TESTPOINT" in part:
            return "TP"
        if p in ("SW", "S", "BTN"):
            return "SW"
        if p in ("Q", "T"):
            return "Q"
        if p in ("U", "IC", "M", "MOD", "A"):
            return "IC"
        return "other"

    def two_nets(self):
        nets = [p.net for p in self.pins.values() if p.net]
        return (nets[0], nets[1]) if len(nets) == 2 else None


@dataclass
class Design:
    comps: dict = field(default_factory=dict)       # ref -> Comp
    nets: dict = field(default_factory=dict)        # name -> [Pin]
    source: str = ""

    def comps_of(self, kind):
        return [c for c in self.comps.values() if c.kind == kind]

    def pins_on(self, net):
        return self.nets.get(net, [])

    # --- net classes
    def is_ground(self, net):
        return bool(net) and N.classify(net)[0] == "Ground"

    def is_power(self, net):
        if not net or self.is_ground(net) or self.is_floating(net):
            return False
        if N.classify(net)[0] in ("Power", "High voltage"):
            return True
        # any rail that drives or feeds IC power pins is a power net, whatever its name
        return any(p.type in ("power_out", "power_in") for p in self.pins_on(net))

    def is_floating(self, net):
        return not net or net.lower().startswith("unconnected-") or len(self.pins_on(net)) <= 1

    def voltage(self, net):
        return N.guess_voltage(net) if net else 0.0

    # --- two-terminal parts between nets
    def parts_between(self, kind, net, other_pred):
        """Two-terminal parts of `kind` with one end on `net` and the other end where other_pred(net2) is true."""
        out = []
        for c in self.comps_of(kind):
            tn = c.two_nets()
            if not tn:
                continue
            a, b = tn
            if a == net and other_pred(b):
                out.append((c, b))
            elif b == net and other_pred(a):
                out.append((c, a))
        return out

    def caps_to_ground(self, net):
        return [(c, parse_value(c.value, "F")) for c, _ in self.parts_between("C", net, self.is_ground)]

    def pulls(self, net):
        """(ups, downs): resistors from net to a power net / to ground, with values."""
        ups = [(r, parse_value(r.value, "Ω"), o) for r, o in self.parts_between("R", net, self.is_power)]
        downs = [(r, parse_value(r.value, "Ω"), o) for r, o in self.parts_between("R", net, self.is_ground)]
        return ups, downs


def parse_xml(text):
    root = ET.fromstring(text)
    d = Design()
    lib_pins = {}
    for lp in root.iter("libpart"):
        key = (lp.get("lib", ""), lp.get("part", ""))
        pins = {}
        for p in lp.iter("pin"):
            pins[p.get("num")] = (p.get("name", ""), p.get("type", ""))
        lib_pins[key] = pins
    for c in root.iter("comp"):
        ls = c.find("libsource")
        lib, part = (ls.get("lib", ""), ls.get("part", "")) if ls is not None else ("", "")
        fields = {f.get("name", "").lower(): (f.text or "") for f in c.iter("field")}
        for p in c.iter("property"):
            fields[p.get("name", "").lower()] = p.get("value", "") or "1"
        ds = (c.findtext("datasheet") or "").strip()
        if ds and "datasheet" not in fields:
            fields["datasheet"] = ds
        comp = Comp(c.get("ref"), (c.findtext("value") or "").strip(), (c.findtext("footprint") or "").strip(),
                    lib, part, (ls.get("description", "") if ls is not None else ""), fields)
        for num, (name, typ) in lib_pins.get((lib, part), {}).items():
            comp.pins[num] = Pin(comp.ref, num, name, typ)
        d.comps[comp.ref] = comp
    for n in root.iter("net"):
        name = n.get("name", "")
        for node in n.iter("node"):
            ref, num = node.get("ref"), node.get("pin")
            comp = d.comps.get(ref)
            if comp is None:
                continue
            pin = comp.pins.get(num)
            if pin is None:
                pin = comp.pins[num] = Pin(ref, num, node.get("pinfunction", "") or num, node.get("pintype", ""))
            if node.get("pinfunction"):
                pin.name = node.get("pinfunction")
            if node.get("pintype"):
                pin.type = node.get("pintype").split("+")[0]
            pin.net = name
            d.nets.setdefault(name, []).append(pin)
    return d


def export_netlist(cli, sch_path):
    out = os.path.join(tempfile.mkdtemp(), "netlist.xml")
    kw = {"capture_output": True, "text": True}
    if os.name == "nt":
        kw["creationflags"] = 0x08000000
    res = subprocess.run([cli, "sch", "export", "netlist", "--format", "kicadxml", "-o", out, sch_path], **kw)
    if not os.path.isfile(out):
        raise RuntimeError((res.stderr or res.stdout or "kicad-cli gave no netlist").strip()[:400])
    with open(out, encoding="utf-8") as f:
        return f.read()


def norm(name):
    return re.sub(r"[^A-Z0-9+\-]", "", (name or "").upper().replace("~{", "").replace("}", ""))
