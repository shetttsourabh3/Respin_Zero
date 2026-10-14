"""Power & Thermal checks on the copper read from the board file.

For each power / ground net from the Net-Class Assistant:
  * narrowest track per layer -> estimated temperature rise (IPC-2221 equation)
  * vias near each other form a group; each group needs enough barrels for the current
  * worst-case voltage drop over the routed copper (nets without a pour)
For the whole board:
  * exposed / thermal pads (large SMD pads on power or ground) without enough vias
Pure Python, so it can be tested without KiCad.
"""
import math
from dataclasses import dataclass

from . import checks as C
from .rules import track_width_mm

RHO_CU = 1.72e-8          # ohm·m at 20 C
ALPHA_CU = 0.00393        # per C
PLATING_MM = 0.025        # via barrel plating
MIL2_PER_MM2 = 1 / (0.0254 ** 2)
VIA_GROUP_MM = 1.5        # vias closer than this are one group
EP_MIN_AREA = 2.0         # mm^2: a pad this big on a power/ground net is a thermal pad candidate
EP_MM2_PER_VIA = 1.5      # guideline: about one thermal via per 1.5 mm^2 of exposed pad
VDROP_LIMIT = 0.03        # 3 % of the rail


@dataclass
class NetSummary:
    net: str
    group: str
    current_a: float
    voltage_v: float
    length_mm: float
    narrowest: str
    est_rise_c: float
    vias: int
    vias_needed: int
    vdrop_v: float
    has_pour: bool


def temp_rise(current_a, width_mm, thick_mm, outer):
    """Invert the IPC-2221 equation: rise in C for a track of this cross-section."""
    if current_a <= 0 or width_mm <= 0 or thick_mm <= 0:
        return 0.0
    k = 0.048 if outer else 0.024
    area_mil2 = width_mm * thick_mm * MIL2_PER_MM2
    return (current_a / (k * area_mil2 ** 0.725)) ** (1 / 0.44)


def via_current(drill_mm, rise_c):
    """Current one via barrel carries for the given rise.

    The barrel is treated as an internal conductor (IPC-2221 k = 0.024): it is enclosed in
    laminate. This is conservative, about 1 A for a 0.3 mm via at 10 C rise.
    """
    area_mm2 = math.pi * PLATING_MM * (drill_mm + PLATING_MM)
    return 0.024 * rise_c ** 0.44 * (area_mm2 * MIL2_PER_MM2) ** 0.725


def rise_text(rise):
    return ">200 C" if rise > 200 else f"about {rise:.0f} C"


def _outer(layer):
    return layer in ("F.Cu", "B.Cu")


def _groups(vias, gap=VIA_GROUP_MM):
    """Cluster vias of one net that are within `gap` of each other."""
    groups, seen = [], set()
    for i, v in enumerate(vias):
        if i in seen:
            continue
        stack, g = [i], []
        seen.add(i)
        while stack:
            j = stack.pop()
            g.append(vias[j])
            for k, w in enumerate(vias):
                if k not in seen and math.dist(vias[j].pos, w.pos) <= gap:
                    seen.add(k)
                    stack.append(k)
        groups.append(g)
    return groups


def _f(type_, tier, desc, action, why, items, section="3.1"):
    return C.Finding("PWR", type_, tier, desc, action, why, section, "", "error", items)


def _item(desc, pos, uuid=""):
    return {"description": desc, "pos": {"x": pos[0], "y": pos[1]}, "uuid": uuid}


def analyze(board, req):
    """Return (findings, summaries, notes)."""
    findings, summaries, notes = [], [], []
    allowed = req.temp_rise_c
    nets = {g.net: g for g in req.net_groups if g.group in ("Power", "Ground", "High voltage")}
    if not nets:
        notes.append("No power or ground nets are set. Set them in the Nets tab first.")

    for name, g in sorted(nets.items()):
        segs = [s for s in board.segments if s.net == name]
        vias = [v for v in board.vias if v.net == name]
        pour = board.zones.get(name, set())
        I = g.current_a
        if g.group == "High voltage" and I <= 0:
            continue
        if I <= 0:
            notes.append(f"Net '{name}' has no current. Give a current in the Net-Class Assistant to check it.")
            continue
        if name not in board.nets:
            notes.append(f"Net '{name}' is not on the board file. Update the PCB or the net list.")
            continue

        # --- track width / temperature rise, per layer
        worst_rise, worst_txt = 0.0, "-"
        for layer in sorted({s.layer for s in segs}):
            ls = [s for s in segs if s.layer == layer]
            n = min(ls, key=lambda s: s.width)
            t = board.copper_mm.get(layer, 0.035 if _outer(layer) else 0.0175)
            rise = temp_rise(I, n.width, t, _outer(layer))
            need = track_width_mm(I, t / 0.035, _outer(layer), allowed)
            if rise > worst_rise:
                worst_rise, worst_txt = rise, f"{n.width:g} mm on {layer}"
            if rise > allowed:
                narrow = [s for s in ls if temp_rise(I, s.width, t, _outer(layer)) > allowed]
                severe = rise > max(3 * allowed, 60)
                tier = C.BLOCK if severe else C.RISK
                pour_note = " A pour on this layer can share the current." if layer in pour else ""
                findings.append(_f(
                    "track_too_narrow_for_current", tier,
                    f"{name}: {I:g} A in {n.width:g} mm on {layer} ({t * 1000:.0f} um copper) "
                    f"rises {rise_text(rise)}. Limit {allowed:g} C needs {need:.2f} mm.",
                    f"Make the {len(narrow)} narrow track segment(s) {need:.2f} mm or wider, "
                    f"or add copper (pour or thicker copper).{pour_note}",
                    "A track that is too narrow for its current gets hot. It can damage the laminate "
                    "or the solder joints, and the voltage at the load drops.",
                    [_item(f"Track [{name}] {s.width:g} mm on {layer}", s.start, s.uuid) for s in narrow[:20]]))

        # --- vias: each group carries the full current in the worst case
        v1 = None
        needed = 0
        if vias:
            v1 = via_current(min(v.drill for v in vias), allowed)
            needed = max(1, math.ceil(I / v1))
            for grp in _groups(vias):
                if len(grp) < needed:
                    c = grp[0]
                    findings.append(_f(
                        "too_few_vias_for_current", C.RISK,
                        f"{name}: {len(grp)} via(s) here; {I:g} A needs {needed} "
                        f"(one {c.drill:g} mm via carries about {v1:.2f} A at {allowed:g} C rise).",
                        f"Add {needed - len(grp)} via(s) next to this group, or use larger drills.",
                        "When the current changes layer, all of it goes through the via barrels. "
                        "Too few vias get hot and can crack.",
                        [_item(f"Via [{name}] {v.drill:g}/{v.size:g} mm", v.pos, v.uuid) for v in grp], "3.3"))

        # --- worst-case voltage drop (series sum of all routed copper)
        vdrop = 0.0
        if g.voltage_v > 0 and not pour and segs:
            temp = 20 + allowed
            rho = RHO_CU * (1 + ALPHA_CU * (temp - 20))
            r = sum(rho * (s.length * 1e-3) / (s.width * 1e-3 * board.copper_mm.get(
                s.layer, 0.035) * 1e-3) for s in segs)
            vdrop = I * r
            if vdrop > VDROP_LIMIT * g.voltage_v:
                longest = max(segs, key=lambda s: s.length)
                findings.append(_f(
                    "voltage_drop_high", C.RISK,
                    f"{name}: worst-case drop {vdrop * 1000:.0f} mV at {I:g} A "
                    f"({100 * vdrop / g.voltage_v:.1f} % of {g.voltage_v:g} V) over {sum(s.length for s in segs):.0f} mm of track.",
                    "Make the supply tracks wider or shorter, or use a pour. Measure the real path "
                    "from the source to the load.",
                    "This is an upper limit: it adds all track of the net in series. If it is near "
                    "the limit, the load can see a low voltage.",
                    [_item(f"Longest track [{name}] {longest.length:.1f} mm", longest.start, longest.uuid)], "3.1"))

        summaries.append(NetSummary(name, g.group, I, g.voltage_v, sum(s.length for s in segs),
                                    worst_txt, worst_rise, len(vias), needed, vdrop, bool(pour)))

    # --- thermal / exposed pads on power or ground nets
    hot_nets = set(nets) | {n for n in board.nets if n.upper().split("/")[-1].startswith(("GND", "VSS"))}
    for p in board.pads:
        if p.kind != "smd" or p.net not in hot_nets or p.area < EP_MIN_AREA:
            continue
        others = [q for q in board.pads if q.ref == p.ref and q is not p]
        if len(others) < 3:          # a two-terminal part, not a package with a thermal pad
            continue
        if p.area < 0.5 * max(q.area for q in others + [p]):
            continue
        inside = [v for v in board.vias if v.net == p.net and p.contains(v.pos)]
        rec = max(1, round(p.area / EP_MM2_PER_VIA))
        if not inside:
            findings.append(_f(
                "thermal_pad_no_vias", C.RISK,
                f"{p.ref} pad {p.number} ({p.size[0]:g} x {p.size[1]:g} mm, {p.net}) has no thermal vias.",
                f"Add about {rec} vias (0.3 mm drill) in the pad, connected to a {p.net} plane. "
                "Use plugged or tented vias if the datasheet says so.",
                "The exposed pad is the main heat path of the package. Without vias the part runs hot.",
                [_item(f"Pad {p.ref}.{p.number} [{p.net}]", p.pos, p.uuid)], "3.4"))
        elif len(inside) < rec:
            findings.append(_f(
                "thermal_pad_few_vias", C.COSMETIC,
                f"{p.ref} pad {p.number} has {len(inside)} thermal via(s); about {rec} is usual for "
                f"{p.area:.1f} mm^2.",
                "Examine the datasheet. Add vias if the part dissipates more than a few hundred mW.",
                "More vias move more heat to the inner and bottom copper.",
                [_item(f"Pad {p.ref}.{p.number} [{p.net}]", p.pos, p.uuid)], "3.4"))
    return findings, summaries, notes


def summary_table(summaries, allowed):
    if not summaries:
        return "No power or ground nets with a current."
    h = (f"{'Net':16} {'Group':7} {'I (A)':>6} {'V':>6} {'Track mm':>9}  {'Narrowest':22} "
         f"{'Rise C':>7} {'Vias':>5} {'Need/grp':>8} {'Vdrop mV':>9} Pour")
    out = [h, "-" * len(h)]
    for s in summaries:
        flag = " !" if s.est_rise_c > allowed else ""
        out.append(f"{s.net[:16]:16} {s.group[:7]:7} {s.current_a:>6g} {s.voltage_v:>6g} {s.length_mm:>9.1f}  "
                   f"{s.narrowest[:22]:22} {('>200' if s.est_rise_c > 200 else f'{s.est_rise_c:.1f}'):>6}{flag:2}{s.vias:>4} {s.vias_needed:>8} "
                   f"{(s.vdrop_v * 1000 if not s.has_pour else 0):>9.0f} {'yes' if s.has_pour else 'no'}")
    out += ["", f"Rise C = estimated temperature rise of the narrowest track (limit {allowed:g} C). "
                "Need/grp = vias needed at each layer change. Vdrop is a worst case (all track in series); "
                "it is not calculated for nets with a pour."]
    return "\n".join(out)
