"""Read copper geometry from a saved .kicad_pcb file (KiCad 7 to 10 formats).

KiCad 10 hides parts of the board from Python plugins, so the analysis tools read
the file. Pure Python, no KiCad import.
"""
import math
import re
from dataclasses import dataclass, field

from . import stackup_file as SF

_NUM = r"-?\d+(?:\.\d+)?(?:[eE]-?\d+)?"
_NET_NUM = re.compile(r'\(\s*net\s+(\d+)(?:\s+"((?:[^"\\]|\\.)*)")?\s*\)')
_NET_STR = re.compile(r'\(\s*net\s+"((?:[^"\\]|\\.)*)"\s*\)')
_UUID = re.compile(r'\(\s*(?:uuid|tstamp)\s+"?([^")\s]+)"?\s*\)')


@dataclass
class Segment:
    net: str
    layer: str
    width: float
    length: float
    start: tuple
    end: tuple
    uuid: str = ""


@dataclass
class Via:
    net: str
    pos: tuple
    size: float
    drill: float
    uuid: str = ""


@dataclass
class Pad:
    net: str
    ref: str
    number: str
    pos: tuple
    size: tuple
    kind: str            # smd / thru_hole / ...
    layers: list = field(default_factory=list)
    uuid: str = ""
    rot: float = 0.0

    def contains(self, pt, margin=0.0):
        """True if point is inside the pad rectangle (pad rotation included)."""
        dx, dy = pt[0] - self.pos[0], pt[1] - self.pos[1]
        x, y = _rot(dx, dy, -self.rot)
        return abs(x) <= self.size[0] / 2 + margin and abs(y) <= self.size[1] / 2 + margin

    @property
    def area(self):
        return self.size[0] * self.size[1]


@dataclass
class Footprint:
    ref: str
    value: str
    name: str            # library footprint name
    pos: tuple
    rot: float
    side: str            # "top" / "bottom"
    uuid: str = ""
    keepout: bool = False


@dataclass
class Board:
    segments: list = field(default_factory=list)
    vias: list = field(default_factory=list)
    pads: list = field(default_factory=list)
    zones: dict = field(default_factory=dict)       # net -> set of layers
    copper_mm: dict = field(default_factory=dict)   # layer name -> copper thickness
    nets: set = field(default_factory=set)
    footprints: list = field(default_factory=list)
    outline: list = field(default_factory=list)      # points on Edge.Cuts
    keepouts: int = 0
    layers: list = field(default_factory=list)       # copper layer names

    def bbox(self):
        if not self.outline:
            return None
        xs, ys = [p[0] for p in self.outline], [p[1] for p in self.outline]
        return min(xs), min(ys), max(xs), max(ys)


def top_blocks(text):
    """Yield (head, start, end) for each direct child of the root (kicad_pcb ...)."""
    depth, in_str, esc, start = 0, False, False, None
    for i, c in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "(":
            depth += 1
            if depth == 2:
                start = i
        elif c == ")":
            if depth == 2 and start is not None:
                m = re.match(r"\(\s*([A-Za-z_]+)", text[start:start + 40])
                yield (m.group(1) if m else ""), start, i + 1
                start = None
            depth -= 1


def _nums(block, head):
    m = re.search(r"\(\s*" + head + r"\s+(" + _NUM + r")(?:\s+(" + _NUM + r"))?(?:\s+(" + _NUM + r"))?", block)
    return tuple(float(g) for g in m.groups() if g is not None) if m else ()


def _str(block, head):
    m = re.search(r"\(\s*" + head + r'\s+"([^"]*)"', block)
    return m.group(1) if m else ""


def _net(block, table):
    m = _NET_NUM.search(block)
    if m:
        return m.group(2) if m.group(2) is not None else table.get(int(m.group(1)), "")
    m = _NET_STR.search(block)
    return m.group(1) if m else ""


def _uuid(block):
    m = _UUID.search(block)
    return m.group(1) if m else ""


def _rot(x, y, deg):
    """KiCad rotation: positive angle turns counter-clockwise on screen (Y points down)."""
    a = math.radians(-deg)
    return x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)


def _arc_len(s, m, e):
    """Length of the circular arc through start, mid, end."""
    ax, ay = s
    bx, by = m
    cx, cy = e
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    chord = math.dist(s, e)
    if abs(d) < 1e-12:
        return chord
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    r = math.dist((ux, uy), s)
    a1, a2, a3 = (math.atan2(p[1] - uy, p[0] - ux) for p in (s, m, e))

    def sweep(f, t):
        return (t - f) % (2 * math.pi)
    total = sweep(a1, a3)
    if sweep(a1, a2) > total:      # mid not on the CCW way -> go the other way
        total = 2 * math.pi - total
    return r * total


def parse(text, default_outer_mm=0.035, default_inner_mm=0.0175):
    b = Board()
    table = {}
    blocks = list(top_blocks(text))
    for head, s, e in blocks:
        if head == "net":
            m = _NET_NUM.match(text[s:e])
            if m and m.group(2) is not None:
                table[int(m.group(1))] = m.group(2)

    # copper thickness from the stackup
    setup = SF._find(text, "setup")
    st = SF._find(text, "stackup", setup[0], setup[1]) if setup else None
    if st:
        for ls, le in SF._children(text, st[0], st[1], "layer"):
            name, kind, th = SF._layer_info(text[ls:le])
            if kind == "copper" and th:
                b.copper_mm[name] = th[0]
    lay = SF._find(text, "layers")
    if lay:
        for name in re.findall(r'\(\s*\d+\s+"([^"]+\.Cu)"', text[lay[0]:lay[1]]):
            outer = name in ("F.Cu", "B.Cu")
            b.copper_mm.setdefault(name, default_outer_mm if outer else default_inner_mm)

    for head, s, e in blocks:
        blk = text[s:e]
        if head == "segment":
            st_, en = _nums(blk, "start")[:2], _nums(blk, "end")[:2]
            w = _nums(blk, "width")
            if len(st_) == 2 and len(en) == 2 and w:
                b.segments.append(Segment(_net(blk, table), _str(blk, "layer"), w[0], math.dist(st_, en),
                                          st_, en, _uuid(blk)))
        elif head == "arc":
            st_, md, en = _nums(blk, "start")[:2], _nums(blk, "mid")[:2], _nums(blk, "end")[:2]
            w = _nums(blk, "width")
            if len(st_) == 2 and len(md) == 2 and len(en) == 2 and w:
                b.segments.append(Segment(_net(blk, table), _str(blk, "layer"), w[0], _arc_len(st_, md, en),
                                          st_, en, _uuid(blk)))
        elif head == "via":
            at, size, drill = _nums(blk, "at")[:2], _nums(blk, "size"), _nums(blk, "drill")
            if len(at) == 2 and size and drill:
                b.vias.append(Via(_net(blk, table), at, size[0], drill[0], _uuid(blk)))
        elif head == "zone":
            net = _str(blk, "net_name") or _net(blk, table)
            layers = set(re.findall(r'"([^"]+\.Cu)"', blk[:blk.find("(polygon")] if "(polygon" in blk else blk))
            if net:
                b.zones.setdefault(net, set()).update(layers)
        elif head == "footprint" or head == "module":
            _footprint(blk, table, b)
        elif head in ("gr_line", "gr_rect", "gr_arc", "gr_circle", "gr_poly") and '"Edge.Cuts"' in blk:
            for key in ("start", "end", "mid", "center"):
                xy = _nums(blk, key)[:2]
                if len(xy) == 2:
                    b.outline.append(xy)
            for xy in re.findall(r"\(\s*xy\s+(" + _NUM + r")\s+(" + _NUM + r")", blk):
                b.outline.append((float(xy[0]), float(xy[1])))
        if head == "zone" and "(keepout" in blk:
            b.keepouts += 1
    b.nets = {x.net for x in b.segments + b.vias + b.pads if x.net} | set(b.zones)
    if lay:
        b.layers = re.findall(r'\(\s*\d+\s+"([^"]+\.Cu)"', text[lay[0]:lay[1]])
    return b


def _footprint(blk, table, b):
    pads = SF._children(blk, 0, len(blk), "pad")
    first_pad = pads[0][0] if pads else len(blk)
    head = blk[:first_pad]
    # the footprint's own (at x y [rot]) is the first one before any property / pad
    prop = head.find("(property")
    at = _nums(head[:prop] if prop > 0 else head, "at")
    fx, fy = (at[0], at[1]) if len(at) >= 2 else (0.0, 0.0)
    frot = at[2] if len(at) >= 3 else 0.0
    ref = ""
    m = re.search(r'\(\s*property\s+"Reference"\s+"([^"]*)"', head) or re.search(r'\(\s*fp_text\s+reference\s+"?([^"\s)]+)', head)
    if m:
        ref = m.group(1)
    vm = re.search(r'\(\s*property\s+"Value"\s+"([^"]*)"', head) or re.search(r'\(\s*fp_text\s+value\s+"?([^"\s)]+)', head)
    name = (re.match(r'\(\s*(?:footprint|module)\s+"?([^"\s)]+)', blk) or [None, ""])[1]
    side = "bottom" if re.search(r'\(\s*layer\s+"B\.Cu"', head[:400]) else "top"
    b.footprints.append(Footprint(ref, vm.group(1) if vm else "", name, (fx, fy), frot, side, _uuid(head),
                                  "(keepout" in blk))
    for s, e in pads:
        p = blk[s:e]
        hm = re.match(r'\(\s*pad\s+"([^"]*)"\s+(\w+)', p)
        pat = _nums(p, "at")
        size = _nums(p, "size")
        if not hm or len(pat) < 2 or len(size) < 2:
            continue
        dx, dy = _rot(pat[0], pat[1], frot)
        layers = re.findall(r'"([^"]+)"', (re.search(r"\(\s*layers\s+([^)]*)\)", p) or [None, ""])[1])
        b.pads.append(Pad(_net(p, table), ref, hm.group(1), (fx + dx, fy + dy), (size[0], size[1]),
                          hm.group(2), layers, _uuid(p), pat[2] if len(pat) >= 3 else frot))
