"""IPC requirement logic. Pure Python: no KiCad imports, so it can be unit-tested.

Values come from IPC-2221 (Table 6-1 spacing, conductor current equation),
IPC-6012 (annular ring by class) and the selected fabricator profile.
Every generated value carries a "why" string that names its source.
"""
from dataclasses import dataclass, field, asdict
import json
import math
import os

# IPC-2221 Table 6-1: (max volts, B1 internal, B2 external uncoated, B4 external coated) in mm
IPC2221_SPACING = [
    (15, 0.05, 0.10, 0.13),
    (30, 0.05, 0.10, 0.13),
    (50, 0.10, 0.60, 0.13),
    (100, 0.10, 0.60, 0.13),
    (150, 0.20, 0.60, 0.40),
    (170, 0.20, 1.25, 0.40),
    (250, 0.20, 1.25, 0.40),
    (300, 0.20, 1.25, 0.40),
    (500, 0.25, 2.50, 0.80),
]
PER_VOLT_ABOVE_500 = (0.0025, 0.005, 0.00305)  # mm/V above 500 V
LOC_NAME = {"internal": "B1 internal", "external": "B2 external uncoated", "external_coated": "B4 external coated"}

ANNULAR_RING = {1: (0.05, 0.025), 2: (0.05, 0.025), 3: (0.10, 0.05)}
EDGE_CLEARANCE = {1: 0.25, 2: 0.30, 3: 0.40}
MAX_ASPECT = {1: 10.0, 2: 8.0, 3: 8.0}

LEVELS = ["Beginner", "Intermediate", "Expert"]
GROUPS = ["Signal", "Power", "Ground", "High voltage"]
PRESETS_FILE = os.path.join(os.path.dirname(__file__), "presets.json")


@dataclass
class PowerNet:
    name: str           # KiCad net class name, e.g. "Power"
    current_a: float
    layer: str = "outer"  # "outer" or "inner"


@dataclass
class NetGroup:
    """One board net, as classified by the net-class assistant."""
    net: str
    group: str = "Signal"     # one of GROUPS
    current_a: float = 0.0
    voltage_v: float = 0.0


@dataclass
class Requirements:
    level: str = "Beginner"
    preset: str = ""
    ipc_class: int = 2
    layers: int = 2
    board_thickness_mm: float = 1.6
    outer_copper_oz: float = 1.0
    inner_copper_oz: float = 0.5
    max_voltage_v: float = 5.0
    hv_voltage_v: float = 0.0          # voltage of a high-voltage net class, 0 = none
    hv_netclass: str = "HV"
    solder_mask_coated: bool = True    # B4 column applies to outer layers
    temp_rise_c: float = 10.0
    fab_min_track_mm: float = 0.127
    fab_min_space_mm: float = 0.127
    fab_min_drill_mm: float = 0.2
    fab_min_annular_mm: float = 0.0
    fab_hole_to_hole_mm: float = 0.25
    fab_edge_mm: float = 0.0
    fab_mask_dam_mm: float = 0.1
    fab_silk_line_mm: float = 0.15
    fab_silk_height_mm: float = 0.8
    manufacturer: str = ""
    density: str = "B"                  # IPC-7351 A/B/C
    medical: bool = False
    ai_disabled: bool = False                          # per project: never send this design to an AI tool
    ai_consent: bool = False                           # the user has seen what the AI review sends
    ai_skills_off: list = field(default_factory=list)  # skill names turned off for this project
    power_nets: list = field(default_factory=list)   # net-class based (intermediate/expert)
    net_groups: list = field(default_factory=list)   # per-net, from the net-class assistant

    def to_json(self):
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, text):
        d = json.loads(text)
        d["power_nets"] = [PowerNet(**p) for p in d.get("power_nets", [])]
        d["net_groups"] = [NetGroup(**g) for g in d.get("net_groups", [])]
        known = cls.__dataclass_fields__
        return cls(**{k: v for k, v in d.items() if k in known})

    def apply_profile(self, prof):
        """Copy fabricator capability values into the fab_* fields."""
        multi = self.layers > 2 and prof.get("min_track_multilayer_mm")
        self.fab_min_track_mm = prof.get("min_track_multilayer_mm") if multi else prof.get("min_track_mm", self.fab_min_track_mm)
        self.fab_min_space_mm = prof.get("min_space_mm", self.fab_min_space_mm)
        self.fab_min_drill_mm = prof.get("min_drill_mm", self.fab_min_drill_mm)
        self.fab_min_annular_mm = prof.get("min_annular_mm", self.fab_min_annular_mm)
        self.fab_hole_to_hole_mm = prof.get("hole_to_hole_mm", self.fab_hole_to_hole_mm)
        self.fab_edge_mm = prof.get("edge_clearance_mm", self.fab_edge_mm)
        self.fab_mask_dam_mm = prof.get("mask_dam_mm", self.fab_mask_dam_mm)
        self.fab_silk_line_mm = prof.get("silk_line_mm", self.fab_silk_line_mm)
        self.fab_silk_height_mm = prof.get("silk_height_mm", self.fab_silk_height_mm)

    def apply_preset(self, preset):
        """Copy preset values (a dict of Requirements fields) into this object."""
        for k, v in preset.get("values", {}).items():
            if k in self.__dataclass_fields__ and k not in ("power_nets", "net_groups"):
                setattr(self, k, v)
        self.preset = preset.get("name", "")


def load_presets():
    try:
        with open(PRESETS_FILE, encoding="utf-8") as f:
            return {p["name"]: p for p in json.load(f)["presets"]}
    except (OSError, ValueError, KeyError):
        return {}


def spacing_mm(voltage, location):
    """location: 'internal', 'external', 'external_coated'."""
    col = {"internal": 1, "external": 2, "external_coated": 3}[location]
    if voltage <= 500:
        for row in IPC2221_SPACING:
            if voltage <= row[0]:
                return row[col]
    return IPC2221_SPACING[-1][col] + (voltage - 500) * PER_VOLT_ABOVE_500[col - 1]


def track_width_mm(current_a, copper_oz, outer, temp_rise_c):
    """IPC-2221 equation, I = k * dT^0.44 * A^0.725 (A in mil^2). First estimate only."""
    if current_a <= 0:
        return 0.0
    k = 0.048 if outer else 0.024
    area_mil2 = (current_a / (k * temp_rise_c ** 0.44)) ** (1 / 0.725)
    thick_mil = copper_oz * 1.378
    return area_mil2 / thick_mil * 0.0254


def _r(x, step=0.005):
    return round(math.ceil(x / step - 1e-9) * step, 4)


def _pick(sources, step=0.005):
    """sources: list of (label, value). Return (rounded max, why-string)."""
    sources = [(l, v) for l, v in sources if v is not None]
    label, val = max(sources, key=lambda s: s[1])
    others = "; ".join(f"{l} {v:g} mm" for l, v in sources)
    return _r(val, step), f"{others} -> {label} governs"


def _quote(net):
    return net


def _usable(net):
    """KiCad rule expressions have no escape for quotes, so such nets cannot be named in a rule."""
    return "'" not in net and '"' not in net


def _net_condition(nets):
    return " || ".join(f"A.NetName == '{n}'" for n in sorted(nets))


def derive(req: Requirements):
    """Return (rules, notes). rules['why'] maps each rule key to the reason for its value."""
    notes, why = [], {}
    ext_loc = "external_coated" if req.solder_mask_coated else "external"

    # General voltage = the largest non-HV voltage the user gave anywhere.
    v = max([req.max_voltage_v] + [g.voltage_v for g in req.net_groups if g.group in ("Power", "Ground")])
    if v > req.max_voltage_v:
        notes.append(f"A power net is at {v:g} V. The general clearance uses {v:g} V, not {req.max_voltage_v:g} V.")

    srcs = [(f"IPC-2221 {LOC_NAME[ext_loc]} at {v:g} V", spacing_mm(v, ext_loc))]
    if req.layers > 2:
        srcs.append((f"IPC-2221 B1 internal at {v:g} V", spacing_mm(v, "internal")))
    srcs.append(("fabricator minimum space", req.fab_min_space_mm))
    clearance, why["clearance"] = _pick(srcs)

    track, why["track_width"] = _pick([("fabricator minimum track", req.fab_min_track_mm)])

    ring_ext, _ = ANNULAR_RING[req.ipc_class]
    annular, why["annular_ring"] = _pick([
        (f"IPC-6012 Class {req.ipc_class} external ring + 0.05 mm drill margin", ring_ext + 0.05),
        ("fabricator minimum annular ring", req.fab_min_annular_mm or None)])

    min_drill, why["min_drill"] = _pick([
        (f"aspect ratio {MAX_ASPECT[req.ipc_class]:.0f}:1 for {req.board_thickness_mm} mm board",
         req.board_thickness_mm / MAX_ASPECT[req.ipc_class]),
        ("fabricator minimum drill", req.fab_min_drill_mm)])

    via_drill, why["via_drill"] = _pick([
        ("minimum drill", min_drill),
        (f"Class {req.ipc_class} preferred via drill", 0.3 if req.ipc_class < 3 else 0.35)])

    hole, why["hole_to_hole"] = _pick([("fabricator hole to hole", req.fab_hole_to_hole_mm),
                                       ("plugin floor", 0.2)])
    edge, why["copper_edge"] = _pick([(f"Class {req.ipc_class} design margin", EDGE_CLEARANCE[req.ipc_class]),
                                      ("fabricator copper to edge", req.fab_edge_mm or None)])
    mask, why["solder_mask_web"] = _pick([("fabricator solder mask dam", req.fab_mask_dam_mm),
                                          ("plugin floor", 0.08)])
    silk_line, why["silk_line"] = _pick([("fabricator silkscreen line", req.fab_silk_line_mm),
                                         ("plugin floor", 0.1)])
    silk_h, why["silk_height"] = _pick([("fabricator silkscreen height", req.fab_silk_height_mm),
                                        ("plugin floor", 0.6)])

    rules = {
        "clearance": clearance, "track_width": track, "min_drill": min_drill, "via_drill": via_drill,
        "annular_ring": annular, "via_diameter": _r(via_drill + 2 * annular),
        "hole_to_hole": hole, "copper_edge": edge, "courtyard_clearance": 0.0,
        "silk_clearance": 0.05, "solder_mask_web": mask, "silk_line": silk_line, "silk_height": silk_h,
        "netclass_rules": [], "why": why,
    }
    why["via_diameter"] = f"via drill {via_drill:g} mm + 2 x annular ring {annular:g} mm"
    why["courtyard_clearance"] = "IPC-7351: courtyards must not overlap"
    why["silk_clearance"] = "keeps legend off exposed copper"
    nr = rules["netclass_rules"]

    # --- High voltage by net class (intermediate / expert) ---
    if req.hv_voltage_v > 0:
        _hv_rules(nr, f"net class {req.hv_netclass}", f"A.NetClass == '{req.hv_netclass}'",
                  req.hv_voltage_v, ext_loc, req.layers)

    # --- Power width by net class ---
    for p in req.power_nets:
        outer = p.layer == "outer"
        oz = req.outer_copper_oz if outer else req.inner_copper_oz
        w = _r(max(track_width_mm(p.current_a, oz, outer, req.temp_rise_c), req.fab_min_track_mm), 0.01)
        nr.append({"name": f"IPC-2152 {p.name} width", "condition": f"A.NetClass == '{p.name}'",
                   "layer": p.layer, "constraint": "track_width", "min": w,
                   "why": f"IPC-2221 equation: {p.current_a:g} A, {oz:g} oz {p.layer}, {req.temp_rise_c:g} C rise"})

    # --- Per-net groups from the net-class assistant ---
    bad = [g.net for g in req.net_groups if not _usable(g.net) and g.group != "Signal"]
    if bad:
        notes.append("These nets have a quote mark in the name, so no rule can name them: "
                     + ", ".join(bad) + ". Rename the nets, or put them in a net class.")
    groups = [g for g in req.net_groups if _usable(g.net)]
    widths = {}
    for g in groups:
        if g.group in ("Power", "Ground") and g.current_a > 0:
            for layer, oz, outer in (("outer", req.outer_copper_oz, True), ("inner", req.inner_copper_oz, False)):
                if layer == "inner" and req.layers <= 2:
                    continue
                w = _r(max(track_width_mm(g.current_a, oz, outer, req.temp_rise_c), req.fab_min_track_mm), 0.01)
                widths.setdefault((layer, w), []).append((g.net, g.current_a, oz))
    for (layer, w), items in sorted(widths.items()):
        nets = [n for n, _, _ in items]
        amps = max(a for _, a, _ in items)
        nr.append({"name": f"IPC-2152 {w:g} mm {layer} ({len(nets)} net{'s' if len(nets) > 1 else ''})",
                   "condition": _net_condition(nets), "layer": layer, "constraint": "track_width", "min": w,
                   "why": f"IPC-2221 equation: up to {amps:g} A, {items[0][2]:g} oz {layer}, {req.temp_rise_c:g} C rise"})

    for (layer, w), items in widths.items():
        if w > 3.0:
            notes.append(f"{', '.join(n for n, _, _ in items)} need {w:g} mm on {layer} layers. "
                         "Use a copper pour or plane, or put more copper on that layer.")
    hv = {}
    for g in groups:
        if g.group == "High voltage" and g.voltage_v > 0:
            hv.setdefault(g.voltage_v, []).append(g.net)
    for volts, nets in sorted(hv.items()):
        _hv_rules(nr, f"{len(nets)} HV net{'s' if len(nets) > 1 else ''}",
                  "(" + _net_condition(nets) + ")", volts, ext_loc, req.layers)

    if hv or req.hv_voltage_v > 0:
        if req.medical:
            notes.append("WARNING: For patient-connected or mains circuits, get creepage and clearance "
                         "from IEC 60601-1. The IPC values are not sufficient for isolation barriers.")
        else:
            notes.append("CAUTION: Mains circuits need creepage and clearance from the product safety "
                         "standard (for example IEC 62368-1). The IPC values are a minimum only.")

    for g in req.net_groups:
        if g.group in ("Power", "Ground") and g.current_a <= 0:
            notes.append(f"Net '{g.net}' is {g.group.lower()} but has no current. Give a current to get a width rule.")
        if g.group == "High voltage" and g.voltage_v <= 0:
            notes.append(f"Net '{g.net}' is high voltage but has no voltage. Give the peak voltage.")

    if req.ipc_class == 3:
        notes.append("Class 3 is selected. Write 'IPC-6012 Class 3' in the fabrication notes.")
    if req.medical and req.ipc_class < 2:
        notes.append("A medical device needs Class 2 minimum. Change the class.")
    return rules, notes


def _hv_rules(nr, label, cond, volts, ext_loc, layers):
    out_mm = _r(spacing_mm(volts, ext_loc))
    nr.append({"name": f"IPC-2221 {label} {volts:g} V outer", "condition": f"{cond} && B.Net != A.Net",
               "layer": "outer", "constraint": "clearance", "min": out_mm,
               "why": f"IPC-2221 {LOC_NAME[ext_loc]} at {volts:g} V"})
    if layers > 2:
        in_mm = _r(spacing_mm(volts, "internal"))
        nr.append({"name": f"IPC-2221 {label} {volts:g} V inner", "condition": f"{cond} && B.Net != A.Net",
                   "layer": "inner", "constraint": "clearance", "min": in_mm,
                   "why": f"IPC-2221 B1 internal at {volts:g} V"})


def rules_block(req: Requirements, rules: dict) -> str:
    """The generated rule block (without the version line). See dru.merge()."""
    why = rules["why"]
    out = [f"# IPC class {req.ipc_class}, density {req.density}, level {req.level}",
           f"# Fabricator: {req.manufacturer or 'custom values'}; preset: {req.preset or 'none'}", ""]

    def rule(name, constraint, minimum, condition=None, layer=None, reason=None):
        if reason:
            out.append(f"# why: {reason}")
        s = f'(rule "{name}"'
        if layer:
            s += f" (layer {layer})"
        s += f" (constraint {constraint} (min {minimum:g}mm))"
        if condition:
            s += f' (condition "{condition}")'
        out.append(s + ")")

    rule("IPC-2221 general clearance", "clearance", rules["clearance"], reason=why["clearance"])
    rule("Fab minimum track", "track_width", rules["track_width"], reason=why["track_width"])
    rule("IPC-6012 annular ring", "annular_width", rules["annular_ring"], reason=why["annular_ring"])
    rule("Minimum drill", "hole_size", rules["min_drill"], reason=why["min_drill"])
    rule("Hole to hole", "hole_to_hole", rules["hole_to_hole"], reason=why["hole_to_hole"])
    rule("Copper to board edge", "edge_clearance", rules["copper_edge"], reason=why["copper_edge"])
    rule("Courtyards", "courtyard_clearance", rules["courtyard_clearance"], reason=why["courtyard_clearance"])
    rule("Silk to mask opening", "silk_clearance", rules["silk_clearance"], reason=why["silk_clearance"])
    rule("Fab silkscreen line", "text_thickness", rules["silk_line"], reason=why["silk_line"])
    rule("Fab silkscreen height", "text_height", rules["silk_height"], reason=why["silk_height"])
    if rules["netclass_rules"]:
        out.append("")
    for n in rules["netclass_rules"]:
        rule(n["name"], n["constraint"], n["min"], n["condition"], n.get("layer"), n.get("why"))
    return "\n".join(out)
