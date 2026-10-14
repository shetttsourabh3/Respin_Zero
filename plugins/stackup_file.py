"""Change the physical stackup inside a saved .kicad_pcb file.

KiCad 10 does not expose BOARD_STACKUP to Python plugins, so the plugin edits the
(setup (stackup ...)) block in the file and the user reloads with File > Revert.
Pure Python, no KiCad import, so it can be tested.
"""
import re
import shutil

OZ_MM = 0.035
_NUM = r"-?\d+(?:\.\d+)?(?:[eE]-?\d+)?"


def _match(text, i):
    """Index just after the ')' that closes the '(' at text[i]. Skips quoted strings."""
    depth, in_str, esc = 0, False, False
    for j in range(i, len(text)):
        c = text[j]
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
        elif c == ")":
            depth -= 1
            if depth == 0:
                return j + 1
    raise ValueError("Unbalanced parentheses in board file")


def _find(text, head, start=0, end=None):
    """(start, end) of the first '(head ...' block between start and end, or None."""
    end = len(text) if end is None else end
    m = re.compile(r"\(\s*" + re.escape(head) + r"(?=[\s)])").search(text, start, end)
    if not m:
        return None
    return m.start(), _match(text, m.start())


def _children(text, start, end, head):
    """All direct '(head ...' blocks inside text[start:end]."""
    out, i = [], start + 1
    pat = re.compile(r"\(\s*" + re.escape(head) + r"(?=[\s)])")
    while True:
        m = pat.search(text, i, end)
        if not m:
            return out
        e = _match(text, m.start())
        out.append((m.start(), e))
        i = e


def _copper_names(text):
    lay = _find(text, "layers")
    if not lay:
        return ["F.Cu", "B.Cu"]
    names = re.findall(r'\(\s*\d+\s+"([^"]+\.Cu)"', text[lay[0]:lay[1]])
    inner = sorted([n for n in names if n.startswith("In")], key=lambda n: int(re.sub(r"\D", "", n) or 0))
    return ["F.Cu"] + inner + ["B.Cu"]


def _fmt(x):
    return f"{x:.5f}".rstrip("0").rstrip(".")


def _layer_info(block):
    name = re.match(r'\(\s*layer\s+"([^"]*)"', block)
    typ = re.search(r'\(\s*type\s+"([^"]*)"', block)
    th = [float(x) for x in re.findall(r"\(\s*thickness\s+(" + _NUM + ")", block)]
    t = (typ.group(1) if typ else "").lower()
    kind = ("copper" if t == "copper" else "dielectric" if t in ("core", "prepreg") or "dielectric" in t
            else "mask" if "solder mask" in t else "other")
    return (name.group(1) if name else "?"), kind, th


def _default_stackup(copper, indent="\t\t"):
    """A KiCad-style default stackup block, used when the file has none."""
    i2 = indent + "\t"
    out = [f"{indent}(stackup",
           f'{i2}(layer "F.SilkS" (type "Top Silk Screen"))',
           f'{i2}(layer "F.Paste" (type "Top Solder Paste"))',
           f'{i2}(layer "F.Mask" (type "Top Solder Mask") (thickness 0.01))']
    for i, cu in enumerate(copper):
        out.append(f'{i2}(layer "{cu}" (type "copper") (thickness 0.035))')
        if i < len(copper) - 1:
            kind = "core" if i % 2 == 0 else "prepreg"
            out.append(f'{i2}(layer "dielectric {i + 1}" (type "{kind}") (thickness 0.1) (material "FR4") '
                       f'(epsilon_r 4.5) (loss_tangent 0.02))')
    out += [f'{i2}(layer "B.Mask" (type "Bottom Solder Mask") (thickness 0.01))',
            f'{i2}(layer "B.Paste" (type "Bottom Solder Paste"))',
            f'{i2}(layer "B.SilkS" (type "Bottom Silk Screen"))',
            f'{i2}(copper_finish "None")', f"{i2}(dielectric_constraints no)", f"{indent})"]
    return "\n".join(out)


def describe(text):
    """Lines describing the stackup in the file text."""
    setup = _find(text, "setup")
    st = _find(text, "stackup", setup[0], setup[1]) if setup else None
    if not st:
        return ["(no stackup block in the file)"]
    out = []
    for s, e in _children(text, st[0], st[1], "layer"):
        name, kind, th = _layer_info(text[s:e])
        if th:
            out.append(f"{name:14} {kind:10} " + " + ".join(f"{t:.3f}" for t in th) + " mm")
    gen = _find(text, "general")
    if gen:
        m = re.search(r"\(\s*thickness\s+(" + _NUM + ")", text[gen[0]:gen[1]])
        if m:
            out.append(f"general board thickness: {float(m.group(1)):g} mm")
    return out


def edit(text, target_mm, outer_oz, inner_oz):
    """Return (new_text, lines, warnings). Raises ValueError if the file cannot be edited."""
    lines, warn = [], []
    setup = _find(text, "setup")
    if not setup:
        raise ValueError("The board file has no (setup) block.")
    st = _find(text, "stackup", setup[0], setup[1])
    if not st:
        indent = re.search(r"\n([ \t]*)\(\s*setup", text)
        ind = (indent.group(1) if indent else "\t") + "\t"
        insert_at = text.index("\n", setup[0]) + 1 if "\n" in text[setup[0]:setup[1]] else setup[0] + len("(setup")
        block = _default_stackup(_copper_names(text), ind)
        text = text[:insert_at] + block + "\n" + text[insert_at:]
        lines.append("The board had no stackup. The plugin added the KiCad default stackup first.")
        setup = _find(text, "setup")
        st = _find(text, "stackup", setup[0], setup[1])

    layers = _children(text, st[0], st[1], "layer")
    infos = [(s, e) + _layer_info(text[s:e]) for s, e in layers]
    copper = [x for x in infos if x[3] == "copper"]
    diel = [x for x in infos if x[3] == "dielectric"]
    masks = [x for x in infos if x[3] == "mask"]
    if not copper or not diel:
        raise ValueError("The plugin could not find the copper and dielectric layers in the stackup.")

    cu_new = {x[0]: (outer_oz if i in (0, len(copper) - 1) else inner_oz) * OZ_MM for i, x in enumerate(copper)}
    mask_total = sum(sum(x[4]) for x in masks)
    want = target_mm - sum(cu_new.values()) - mask_total
    if want <= 0.05:
        raise ValueError(f"{target_mm:g} mm is too thin: copper and solder mask alone are "
                         f"{target_mm - want:.3f} mm.")
    cur = sum(sum(x[4]) for x in diel)
    n_sub = sum(len(x[4]) for x in diel)

    def new_dielectric(t):
        return want * (t / cur) if cur > 0 else want / n_sub

    # Rewrite from the end, so earlier offsets stay valid.
    num = re.compile(r"(\(\s*thickness\s+)(" + _NUM + ")")
    for s, e, name, kind, th in sorted(copper + diel, key=lambda x: -x[0]):
        block = text[s:e]
        if kind == "copper":
            block = num.sub(lambda m: f"{m.group(1)}{_fmt(cu_new[s])}", block, count=1)
        else:
            block = num.sub(lambda m: f"{m.group(1)}{_fmt(new_dielectric(float(m.group(2))))}", block)
        text = text[:s] + block + text[e:]

    gen = _find(text, "general")
    if gen:
        g = text[gen[0]:gen[1]]
        if re.search(r"\(\s*thickness\s+" + _NUM, g):
            g = re.sub(r"(\(\s*thickness\s+)" + _NUM, lambda m: f"{m.group(1)}{target_mm:g}", g, count=1)
            text = text[:gen[0]] + g + text[gen[1]:]

    _match(text, text.index("("))   # whole file still balanced?
    lines.append(f"Copper: outer {outer_oz:g} oz, inner {inner_oz:g} oz; solder mask kept at {mask_total:.3f} mm")
    lines.append(f"Dielectric: {cur:.3f} mm scaled to {want:.3f} mm over {n_sub} layer(s)")
    return text, lines, warn


def edit_file(path, target_mm, outer_oz, inner_oz):
    """Edit the board file in place, keeping a backup. Return (lines, warnings)."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    before = describe(text)
    new, lines, warn = edit(text, target_mm, outer_oz, inner_oz)
    shutil.copy2(path, path + ".ipcste.bak")
    with open(path, "w", encoding="utf-8") as f:
        f.write(new)
    after = describe(new)
    return (lines + ["Stackup before:"] + [f"    {x}" for x in before]
            + ["Stackup after:"] + [f"    {x}" for x in after]
            + [f"Backup of the board file: {path}.ipcste.bak"]), warn
