"""Everything that touches the KiCad board (SWIG API, KiCad 10). Kept apart from the UI."""
import os
try:
    import pcbnew
except ImportError:          # standalone window without KiCad's pcbnew module
    pcbnew = None

OZ_MM = 0.035  # 1 oz copper is about 35 um
CFG_NAME = "ipc_ste_requirements.json"


def project_paths(board):
    bp = board.GetFileName()
    base = os.path.splitext(bp)[0]
    d = os.path.dirname(bp)
    return {"board": bp, "sch": base + ".kicad_sch", "dru": base + ".kicad_dru",
            "cfg": os.path.join(d, CFG_NAME), "dir": d, "report": base + "-ipc-ste-report.txt"}


def net_names(board, path=None):
    if board is None:
        try:
            from . import pcbfile
            with open(path, encoding="utf-8", errors="replace") as f:
                return sorted(n for n in pcbfile.parse(f.read()).nets if n)
        except (OSError, TypeError):
            return []
    names = []
    try:
        for code, net in board.GetNetInfo().NetsByNetcode().items():
            if code > 0:
                names.append(str(net.GetNetname()))
    except Exception:
        try:
            names = [str(k) for k in board.GetNetsByName().keys()]
        except Exception:
            pass
    return [n for n in names if n]


def board_defaults(board, req):
    """Start the questions from the board's real layer count and thickness."""
    try:
        req.layers = board.GetCopperLayerCount()
        req.board_thickness_mm = round(pcbnew.ToMM(board.GetDesignSettings().GetBoardThickness()), 3)
    except Exception:
        pass
    return req


def apply_board_settings(board, rules):
    """Write the general minimums into Board Setup > Constraints."""
    ds = board.GetDesignSettings()
    mm = pcbnew.FromMM
    pairs = [("m_MinClearance", "clearance"), ("m_TrackMinWidth", "track_width"),
             ("m_MinThroughDrill", "min_drill"), ("m_ViasMinSize", "via_diameter"),
             ("m_ViasMinAnnularWidth", "annular_ring"), ("m_HoleToHoleMin", "hole_to_hole"),
             ("m_CopperEdgeClearance", "copper_edge"), ("m_SolderMaskMinWidth", "solder_mask_web"),
             ("m_MinSilkTextHeight", "silk_height"), ("m_MinSilkTextThickness", "silk_line")]
    done, skipped = [], []
    for attr, key in pairs:
        try:
            setattr(ds, attr, mm(rules[key]))
            done.append(f"{attr} = {rules[key]:g} mm")
        except Exception:
            skipped.append(attr)
    return done, skipped


def _kind(it):
    """'copper', 'dielectric', 'mask', 'other' - by type constant, else by type name."""
    t = it.GetType()
    for name, const in (("copper", "BS_ITEM_TYPE_COPPER"), ("dielectric", "BS_ITEM_TYPE_DIELECTRIC"),
                        ("mask", "BS_ITEM_TYPE_SOLDERMASK")):
        c = getattr(pcbnew, const, None)
        if c is not None and t == c:
            return name
    try:
        n = str(it.GetTypeName()).lower()
        for name in ("copper", "dielectric", "core", "prepreg", "mask"):
            if name in n:
                return "dielectric" if name in ("core", "prepreg") else name
    except Exception:
        pass
    return "other"


def _thick(it, k=0):
    try:
        return pcbnew.ToMM(it.GetThickness(k))
    except Exception:
        return 0.0


def stackup_dump(board):
    """One line per stackup item, for the report."""
    try:
        ds = board.GetDesignSettings()
        items = list(ds.GetStackupDescriptor().GetList())
    except Exception as e:
        return [f"(stackup not readable: {e})"]
    out = []
    for it in items:
        kind = _kind(it)
        if kind == "other":
            continue
        try:
            name = str(it.GetLayerName()) or kind
        except Exception:
            name = kind
        subs = getattr(it, "GetSublayersCount", lambda: 1)()
        out.append(f"{name:14} {kind:10} " + " + ".join(f"{_thick(it, k):.3f}" for k in range(subs)) + " mm")
    try:
        out.append(f"custom stackup flag (m_HasStackup): {ds.m_HasStackup}")
    except Exception:
        pass
    return out


class StackupUnavailable(Exception):
    """KiCad 10 does not expose BOARD_STACKUP to Python. Use stackup_file instead."""


def apply_stackup(board, req):
    """Set copper thickness and scale the dielectrics so the stackup totals the requested thickness.

    KiCad 10 counts copper + dielectric + solder mask in "Board thickness from stackup".
    The copper layer count is NOT changed, because that can delete tracks on removed layers.
    """
    lines, warn = [], []
    ds = board.GetDesignSettings()
    mm, to_mm = pcbnew.FromMM, pcbnew.ToMM
    target = req.board_thickness_mm

    n_cu = board.GetCopperLayerCount()
    if n_cu != req.layers:
        warn.append(f"The board has {n_cu} copper layers, but the answers give {req.layers}. "
                    "Change the layer count in Board Setup > Board Stackup > Physical Stackup.")

    before = stackup_dump(board)
    # Without this flag KiCad ignores the stored stackup and rebuilds a default one.
    had = None
    try:
        had = bool(ds.m_HasStackup)
        ds.m_HasStackup = True
    except Exception as e:
        warn.append(f"The plugin could not mark the board as having a custom stackup ({e}).")

    try:
        stack = ds.GetStackupDescriptor()
        items = list(stack.GetList())
        if not items:
            stack.BuildDefaultStackupList(ds, n_cu)
            items = list(stack.GetList())
            lines.append("No stackup existed. The plugin made the KiCad default stackup first.")
    except Exception as e:
        raise StackupUnavailable(str(e))

    copper = [it for it in items if _kind(it) == "copper"]
    diel = [it for it in items if _kind(it) == "dielectric"]
    masks = [it for it in items if _kind(it) == "mask"]
    if not copper or not diel:
        warn.append("The plugin could not identify the copper and dielectric layers in the stackup. Nothing changed.")
        return lines, warn + ["Stackup seen: " + "; ".join(before)]

    cu_t = [(req.outer_copper_oz if i in (0, len(copper) - 1) else req.inner_copper_oz) * OZ_MM
            for i in range(len(copper))]
    mask_total = sum(_thick(m) for m in masks)
    fixed = sum(cu_t) + mask_total
    want = target - fixed
    if want <= 0.05:
        warn.append(f"{target:g} mm is too thin: copper and solder mask alone are {fixed:.3f} mm. "
                    "The stackup is not changed.")
        return lines, warn

    for it, t in zip(copper, cu_t):
        it.SetThickness(mm(t))
    subs = [(it, k, _thick(it, k)) for it in diel for k in range(it.GetSublayersCount())]
    cur = sum(s[2] for s in subs)
    for it, k, t in subs:
        it.SetThickness(mm(want * (t / cur) if cur > 0 else want / len(subs)), k)

    try:
        ds.SetBoardThickness(mm(target))
    except Exception:
        try:
            ds.m_boardThickness = mm(target)
        except Exception as e:
            warn.append(f"The board thickness setting was not changed ({e}).")

    lines.append(f"Copper: outer {req.outer_copper_oz:g} oz ({req.outer_copper_oz * OZ_MM:.3f} mm), "
                 f"inner {req.inner_copper_oz:g} oz ({req.inner_copper_oz * OZ_MM:.3f} mm)")
    lines.append(f"Solder mask kept: {mask_total:.3f} mm total")
    lines.append(f"Dielectric: {cur:.3f} mm scaled to {want:.3f} mm over {len(subs)} layer(s)")

    # Read back from a fresh descriptor, to prove the change is on the board itself.
    after_items = list(board.GetDesignSettings().GetStackupDescriptor().GetList())
    actual = sum(_thick(it, k) for it in after_items if _kind(it) in ("copper", "dielectric", "mask")
                 for k in range(it.GetSublayersCount() if _kind(it) == "dielectric" else 1))
    lines.append(f"Board thickness from stackup: {actual:.3f} mm (requested {target:g} mm)")
    if had is False:
        lines.append("The board had no custom stackup before. The plugin turned it on.")
    if abs(actual - target) > 0.01:
        warn.append("The stackup on the board did not change. Send the 'Stackup before/after' lines to support.")
    lines += ["Stackup before:"] + [f"    {s}" for s in before]
    lines += ["Stackup after:"] + [f"    {s}" for s in stackup_dump(board)]
    return lines, warn


def mark_modified(board):
    for fn in ("OnModify", "SetModified"):
        try:
            getattr(board, fn)()
            return
        except Exception:
            continue


# ---------- click to locate ----------

def uuid_map(board):
    m = {}

    def add(it):
        try:
            m[it.m_Uuid.AsString()] = it
        except Exception:
            pass

    for t in board.GetTracks():
        add(t)
    for fp in board.GetFootprints():
        add(fp)
        for p in fp.Pads():
            add(p)
        for g in fp.GraphicalItems():
            add(g)
        for z in getattr(fp, "Zones", lambda: [])():
            add(z)
        add(fp.Reference())
        add(fp.Value())
    for z in board.Zones():
        add(z)
    for d in board.GetDrawings():
        add(d)
    return m


def locate(board, item):
    """Zoom to and select an item. Return True on success."""
    try:
        pcbnew.FocusOnItem(item)
        return True
    except Exception:
        pass
    try:
        for fp in board.GetFootprints():
            fp.ClearSelected()
        item.SetSelected()
        pcbnew.Refresh()
        return True
    except Exception:
        return False


def save_board(board, path):
    if board is None:              # standalone window: the PCB editor saves its own file
        return True
    try:
        pcbnew.SaveBoard(path, board)
        return True
    except Exception:
        return False


def locate_ref(board, ref):
    """Zoom to a footprint by its reference designator."""
    try:
        fp = board.FindFootprintByReference(ref)
    except Exception:
        fp = None
    if not fp:
        for f in board.GetFootprints():
            try:
                if f.GetReference() == ref:
                    fp = f
                    break
            except Exception:
                continue
    return bool(fp) and locate(board, fp)
