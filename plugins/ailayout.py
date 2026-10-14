"""AI layout review: the plugin measures the board, the AI judges the measurements.

Language models are poor at geometry from raw coordinates, so distances, lengths and pair
mismatches are computed here and given to the AI as facts. Pure Python.
"""
import math
import re

from . import aireview as AR
from . import netdetect as N

MAX_CHARS = AR.MAX_CHARS
MODULE_RX = re.compile(r"ESP32|ESP8266|WROOM|WROVER|MINI-1|NRF5|BL65|BM8|RF_Module|WIFI|BLE|LORA|RFM9|SX12|ANTENNA|GSM|LTE|GPS", re.I)
PAIR_PATTERNS = [(re.compile(r"^(.*?)(D)\+$"), re.compile(r"^(.*?)(D)-$")),
                 (re.compile(r"^(.*?)_?(DP)$"), re.compile(r"^(.*?)_?(DM)$")),
                 (re.compile(r"^(.*?)_(P)$"), re.compile(r"^(.*?)_(N)$")),
                 (re.compile(r"^(.*?)(\+)$"), re.compile(r"^(.*?)(-)$"))]

INSTRUCTIONS = """You are a senior PCB layout engineer reviewing an embedded product's board before it is ordered.
The plugin has measured the layout and gives you facts: stackup, placement, distances, track lengths,
differential-pair mismatch, power routing, and the DRC / power-check results. Judge these facts:
- decoupling: capacitor-to-power-pin distance (usually < 2-3 mm for 100 nF), bulk capacitor near the source
- crystals: distance to the MCU (short, < 5-10 mm), no long traces
- differential pairs (USB, Ethernet, CAN, LVDS): length mismatch, vias, same layer, reference plane
- RF modules and antennas: antenna area at the board edge, keep-out, no copper or ground pour under the antenna
- power: track widths for the current, vias at layer changes, pours, regulator thermal area
- placement: connectors at edges, mounting holes, parts on both sides (assembly cost), test access
- manufacturability: anything in the facts that suggests a fabrication or assembly problem

Rules:
- Judge only from the facts given. Do not invent measurements. If a fact is missing, do not guess it.
- If unsure about a datasheet requirement, set "confidence" to "low".
- Use ONLY reference designators, pad numbers and net names that appear in the facts.
- Do not repeat the DRC / power findings that are listed as already reported.
- Severity: "block" = the board will not work or cannot be built; "risk" = may fail or be out of spec; "cosmetic" = improvement.

Reply with ONLY a JSON object, no other text:
{"findings": [{"severity": "block|risk|cosmetic", "title": "short title",
  "detail": "what is wrong and why, with the measured values", "action": "what to change",
  "refs": ["C3", "U1"], "pins": ["U1.3"], "nets": ["+3V3"], "confidence": "high|medium|low"}],
 "summary": "one or two sentences about the layout"}
"""


def _is_ic(ref):
    return bool(re.match(r"^(U|IC|M|MOD|A)\d", ref, re.I))


def _is_cap(ref):
    return bool(re.match(r"^C\d", ref, re.I))


def _is_xtal(ref):
    return bool(re.match(r"^(Y|X|XTAL)\d", ref, re.I))


def _ground(net):
    return N.classify(net)[0] == "Ground"


def _power(net, b):
    if not net or _ground(net):
        return False
    if N.classify(net)[0] in ("Power", "High voltage"):
        return True
    return net in b.zones and not _ground(net)


def decoupling(b):
    """[(cap, net, nearest IC pad label, distance mm)] for capacitors between a rail and ground."""
    out = []
    by_ref = {}
    for p in b.pads:
        by_ref.setdefault(p.ref, []).append(p)
    for ref, pads in by_ref.items():
        if not _is_cap(ref) or len(pads) != 2:
            continue
        nets = [p.net for p in pads]
        if not any(_ground(n) for n in nets):
            continue
        rail_pad = next((p for p in pads if _power(p.net, b)), None)
        if not rail_pad:
            continue
        ic_pads = [q for q in b.pads if q.net == rail_pad.net and _is_ic(q.ref)]
        if not ic_pads:
            continue
        near = min(ic_pads, key=lambda q: math.dist(q.pos, rail_pad.pos))
        out.append((ref, rail_pad.net, f"{near.ref}.{near.number}", math.dist(near.pos, rail_pad.pos)))
    return sorted(out, key=lambda x: -x[3])


def crystals(b):
    out = []
    for f in b.footprints:
        if not _is_xtal(f.ref):
            continue
        pads = [p for p in b.pads if p.ref == f.ref and p.net and not _ground(p.net)]
        for p in pads:
            ics = [q for q in b.pads if q.net == p.net and _is_ic(q.ref)]
            if ics:
                near = min(ics, key=lambda q: math.dist(q.pos, p.pos))
                length = sum(s.length for s in b.segments if s.net == p.net)
                out.append((f.ref, p.net, f"{near.ref}.{near.number}", math.dist(near.pos, p.pos), length))
    return out


def pairs(b):
    out, used = [], set()
    nets = sorted(b.nets)
    tails = {n: n.split("/")[-1].upper() for n in nets}
    for pos_rx, neg_rx in PAIR_PATTERNS:
        for n in nets:
            if n in used:
                continue
            m = pos_rx.match(tails[n])
            if not m:
                continue
            base = m.group(1)
            mate = next((x for x in nets if x not in used and x != n and neg_rx.match(tails[x])
                         and neg_rx.match(tails[x]).group(1) == base), None)
            if not mate:
                continue
            used |= {n, mate}
            stats = []
            for net in (n, mate):
                segs = [s for s in b.segments if s.net == net]
                stats.append((sum(s.length for s in segs), sorted({s.layer for s in segs}),
                              sum(1 for v in b.vias if v.net == net),
                              min((s.width for s in segs), default=0)))
            out.append((n, mate, stats))
    return out


def summarize(b, req=None, prior_findings=()):
    lines = []
    bb = b.bbox()
    lines.append("# Board")
    if bb:
        lines.append(f"  outline {bb[2] - bb[0]:.1f} x {bb[3] - bb[1]:.1f} mm (from {bb[0]:.1f},{bb[1]:.1f} to {bb[2]:.1f},{bb[3]:.1f})")
    lines.append(f"  copper layers: {', '.join(f'{l} ({b.copper_mm.get(l, 0) * 1000:.0f} um)' for l in b.layers)}")
    if req is not None:
        lines.append(f"  IPC class {req.ipc_class}, thickness {req.board_thickness_mm:g} mm, fabricator "
                     f"{req.manufacturer or 'not set'}, temperature rise limit {req.temp_rise_c:g} C")
    lines.append(f"  footprints {len(b.footprints)} (bottom side: {sum(1 for f in b.footprints if f.side == 'bottom')}), "
                 f"tracks {len(b.segments)}, vias {len(b.vias)}, keep-out areas {b.keepouts}")

    lines.append("# Copper pours (net: layers)")
    for net, layers in sorted(b.zones.items()):
        lines.append(f"  {net}: {', '.join(sorted(layers))}")

    lines.append("# Placement (ref value footprint x y rotation side; mm, degrees; Y points down)")
    for f in sorted(b.footprints, key=lambda f: f.ref)[:500]:
        edge = ""
        if bb:
            d = min(f.pos[0] - bb[0], bb[2] - f.pos[0], f.pos[1] - bb[1], bb[3] - f.pos[1])
            edge = f" edge {d:.1f}"
        lines.append(f"  {f.ref} {f.value or '-'} {f.name.split(':')[-1]} {f.pos[0]:.2f} {f.pos[1]:.2f} {f.rot:g} {f.side}{edge}")

    mods = [f for f in b.footprints if MODULE_RX.search(f"{f.value} {f.name}")]
    if mods:
        lines.append("# RF modules / antennas (centre distance to nearest board edge)")
        for f in mods:
            under = sorted(n for n, ls in b.zones.items() if ("F.Cu" in ls or "B.Cu" in ls))
            lines.append(f"  {f.ref} {f.value or f.name}: centre {f.pos[0]:.1f},{f.pos[1]:.1f}, rotation {f.rot:g}, "
                         f"{'edge ' + format(min(f.pos[0] - bb[0], bb[2] - f.pos[0], f.pos[1] - bb[1], bb[3] - f.pos[1]), '.1f') + ' mm' if bb else 'no outline'}; "
                         f"outer-layer pours on board: {', '.join(under) or 'none'}")

    dec = decoupling(b)
    if dec:
        lines.append("# Decoupling: capacitor pad to nearest IC pad on the same rail (mm, farthest first)")
        lines += [f"  {c} on {net}: {pin} at {d:.1f} mm" for c, net, pin, d in dec[:150]]
    xt = crystals(b)
    if xt:
        lines.append("# Crystals: pad to nearest IC pad, routed length")
        lines += [f"  {r} {net}: {pin} at {d:.1f} mm, track {ln:.1f} mm" for r, net, pin, d, ln in xt]
    pr = pairs(b)
    if pr:
        lines.append("# Differential pairs (length mm, layers, vias, min width)")
        for p, n, ((lp, yp, vp, wp), (ln, yn, vn, wn)) in pr:
            lines.append(f"  {p} / {n}: {lp:.1f} / {ln:.1f} mm (mismatch {abs(lp - ln):.2f} mm), "
                         f"layers {','.join(yp) or '-'} / {','.join(yn) or '-'}, vias {vp}/{vn}, width {wp:g}/{wn:g}")
    lines.append("# Power and ground nets (routed length, width range, layers, vias, pour)")
    groups = {g.net: g for g in (req.net_groups if req else [])}
    for net in sorted(n for n in b.nets if _power(n, b) or _ground(n)):
        segs = [s for s in b.segments if s.net == net]
        g = groups.get(net)
        cur = f", {g.current_a:g} A" if g and g.current_a else ""
        widths = f"{min(s.width for s in segs):g}-{max(s.width for s in segs):g} mm" if segs else "no tracks"
        lines.append(f"  {net}{cur}: {sum(s.length for s in segs):.1f} mm, {widths}, "
                     f"layers {','.join(sorted({s.layer for s in segs})) or '-'}, vias {sum(1 for v in b.vias if v.net == net)}, "
                     f"pour {','.join(sorted(b.zones.get(net, []))) or 'none'}")
    if prior_findings:
        lines.append("# DRC / power-check findings (already reported)")
        lines += [f"  - [{f.source} {f.tier}] {f.description}" for f in prior_findings[:150]]
    text = "\n".join(lines)
    trunc = len(text) > MAX_CHARS
    return (text[:MAX_CHARS] + "\n# (facts cut here: the board is too large for one request)") if trunc else text, trunc


def build_request(b, req=None, prior=()):
    text, trunc = summarize(b, req, prior)
    return INSTRUCTIONS, "MEASURED LAYOUT FACTS\n\n" + text, trunc


def parse_reply(text, b):
    refs = {f.ref for f in b.footprints}
    pads = {(p.ref, p.number) for p in b.pads}
    return AR.parse_generic(text, lambda r: r in refs, lambda r, n: (r, n) in pads if n else r in refs,
                            lambda n: n in b.nets, lambda r, n: f"{r} pad {n}")
