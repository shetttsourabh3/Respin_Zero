"""Fabrication outputs: final checks, then Gerbers, drill, BOM, pick-and-place, STEP and a fab note with kicad-cli.

Pure Python (no wx). The UI passes in the review state; everything else is read from the saved files.
"""
import csv
import datetime
import io
import json
import os
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass

from . import checks as C
from . import pcbfile as PF

HERE = os.path.dirname(os.path.abspath(__file__))
BUNDLED = os.path.join(HERE, "fab_presets.json")
PERSONAL = os.path.join(os.path.expanduser("~"), ".kicad_review", "fab_presets.json")
OK, WARN, FAIL = "ok", "warn", "fail"
MPN_KEYS = ("mpn", "manufacturer_part_number", "manufacturer part number", "mfr part", "mfr_pn", "part number")
LCSC_KEYS = ("lcsc", "lcsc part", "lcsc part #", "lcsc_part", "jlcpcb part")
MFR_KEYS = ("manufacturer", "mfr", "manufacturer_name")


class FabError(RuntimeError):
    pass


@dataclass
class Check:
    level: str
    title: str
    detail: str = ""


# --------------------------------------------------------------------------------------------- presets
def load_presets():
    out, order = {}, []
    for path in (BUNDLED, PERSONAL):
        try:
            with open(path, encoding="utf-8") as f:
                items = json.load(f).get("presets", [])
        except (OSError, ValueError):
            continue
        for p in items:
            if isinstance(p, dict) and p.get("id"):
                if p["id"] not in out:
                    order.append(p["id"])
                out[p["id"]] = {**out.get(p["id"], {}), **p}
    return [out[i] for i in order]


def preset_for(fabricator_id, presets):
    return next((p for p in presets if fabricator_id and fabricator_id in p.get("fabricators", [])),
                next((p for p in presets if p["id"] == "generic"), presets[0]))


# --------------------------------------------------------------------------------------------- checks
def _mtime(p):
    try:
        return os.path.getmtime(p)
    except OSError:
        return 0


def preflight(paths, req, state, profile=None, design=None, unsaved=None):
    """state: {"sch"|"check"|"power": None or {"counts": {...}, "ran_at": t, "ran": (...)}}.
    Returns [Check]. FAIL blocks the export unless the user gives a reason."""
    res = []
    board = paths.get("board", "")
    if not os.path.isfile(board):
        return [Check(FAIL, "No saved board file", "Save the board in the PCB editor first.")]
    newest = max(_mtime(board), _mtime(paths.get("sch", "")))
    names = {"sch": "Schematic review", "check": "ERC and DRC", "power": "Power and thermal check"}
    for key, name in names.items():
        st = state.get(key)
        if not st:
            res.append(Check(FAIL if key == "check" else WARN, f"{name} not run",
                             "Press 'Run all checks' (the fab files must come from a checked design)."))
            continue
        if key == "check" and "DRC" not in st.get("ran", ("DRC",)):
            res.append(Check(FAIL, "DRC not run", "kicad-cli could not run DRC. See the ERC / DRC tab."))
            continue
        if st.get("ran_at", 0) + 1 < newest:
            res.append(Check(FAIL if key == "check" else WARN, f"{name} is older than the saved files",
                             "The board or schematic was saved after the check. Run the checks again."))
            continue
        c = st["counts"]
        b = c.get("Blocks fabrication", 0)
        if b:
            res.append(Check(FAIL, f"{name}: {b} blocking finding(s)", "Fix them, or waive each one with a reason."))
        else:
            r = c.get("Reliability risk", 0)
            res.append(Check(WARN if r else OK, f"{name}: no blocking findings",
                             f"{r} risk(s), {c.get('Waived', 0)} waived." if r or c.get("Waived") else "Clear."))
    try:
        with open(board, encoding="utf-8", errors="replace") as f:
            text = f.read()
        b = PF.parse(text)
    except OSError as e:
        return res + [Check(FAIL, "Cannot read the board file", str(e))]
    if not b.outline:
        res.append(Check(FAIL, "No board outline", "Draw the board outline on the Edge.Cuts layer."))
    else:
        x0, y0, x1, y1 = b.bbox()
        res.append(Check(OK, "Board outline found", f"{x1 - x0:.1f} x {y1 - y0:.1f} mm."))
    n_layers = len(b.layers)
    if n_layers and req.layers and n_layers != req.layers:
        res.append(Check(WARN, f"Board has {n_layers} copper layers, the answers say {req.layers}",
                         "Correct the answers in Design Rules, or the layer count in Board Setup."))
    if profile:
        if n_layers > profile.get("max_layers", 99):
            res.append(Check(FAIL, f"{profile['name']} makes at most {profile['max_layers']} layers", ""))
        lo, hi = profile.get("thickness_mm", [0, 99])
        if not lo <= req.board_thickness_mm <= hi:
            res.append(Check(FAIL, f"Thickness {req.board_thickness_mm:g} mm is outside {profile['name']}'s "
                                   f"{lo:g}-{hi:g} mm", ""))
        res.append(Check(OK, f"Fabricator: {profile['name']}", "Rules were made for its capabilities."))
    else:
        res.append(Check(WARN, "No fabricator selected", "Select one in Design Rules so the rules match it."))
    if not os.path.isfile(paths.get("dru", "")):
        res.append(Check(WARN, "Design rules not applied", "Apply the rules in the Design Rules tab and run DRC."))
    if design is not None:
        parts = [c for c in design.comps.values() if c.kind not in ("ignore",) and not _dnp(c)]
        no_mpn = [c.ref for c in parts if not _field(c, MPN_KEYS + LCSC_KEYS) and c.kind not in ("R", "C", "L", "FB",
                                                                                                   "J", "TP")]
        if no_mpn:
            res.append(Check(WARN, f"{len(no_mpn)} part(s) without a part number",
                             "Needed for assembly: " + ", ".join(sorted(no_mpn)[:12]) + (" ..." if len(no_mpn) > 12 else "")))
        refs_pcb = {f.ref for f in b.footprints if getattr(f, "ref", "")}
        if refs_pcb:
            missing = sorted(c.ref for c in parts if c.ref not in refs_pcb and not c.ref.startswith("#"))
            if missing:
                res.append(Check(FAIL, f"{len(missing)} schematic part(s) not on the board",
                                 "Update the PCB from the schematic: " + ", ".join(missing[:12])))
    if unsaved is not None:
        res.append(Check(WARN if unsaved else OK, f"{unsaved} unsaved change(s) in History" if unsaved else
                         "History: all changes saved", "The export saves a version, so the files match it."
                         if unsaved else ""))
    return res


def blocking(checks):
    return [c for c in checks if c.level == FAIL]


# --------------------------------------------------------------------------------------------- outputs
def _field(c, keys):
    return next((c.fields[k] for k in keys if c.fields.get(k, "~") not in ("", "~")), "")


def _dnp(c):
    v = str(c.fields.get("dnp", "")).lower()
    return v not in ("", "0", "false", "no") or str(c.fields.get("exclude_from_bom", "")).lower() in ("1", "true", "yes")


def _refsort(r):
    m = re.match(r"([A-Za-z#]*)(\d*)", r)
    return (m.group(1), int(m.group(2) or 0), r)


def bom_rows(design, preset):
    """Rows for the preset's BOM columns, grouped by value + footprint + part number."""
    groups = {}
    for c in design.comps.values():
        if c.kind == "ignore" or _dnp(c) or c.ref.startswith("#"):
            continue
        fp = c.footprint.split(":")[-1]
        key = (c.value, fp, _field(c, MPN_KEYS), _field(c, LCSC_KEYS))
        groups.setdefault(key, []).append(c)
    rows = []
    for i, (key, comps) in enumerate(sorted(groups.items(), key=lambda kv: _refsort(min(c.ref for c in kv[1]))), 1):
        c0 = comps[0]
        smd = not re.search(r"THT|_TH\b|DIP|PinHeader|Through|TO-220|Axial|Radial", c0.footprint, re.I)
        vals = {"index": str(i), "refs": ",".join(sorted((c.ref for c in comps), key=_refsort)),
                "qty": str(len(comps)), "value": c0.value, "footprint": key[1], "mpn": key[2], "lcsc": key[3],
                "manufacturer": _field(c0, MFR_KEYS), "datasheet": c0.fields.get("datasheet", "").replace("~", ""),
                "mount": "SMD" if smd else "THT"}
        rows.append([tmpl.format(**vals) for _h, tmpl in preset["bom"]["columns"]])
    return [h for h, _ in preset["bom"]["columns"]], rows


def write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def convert_cpl(kicad_csv_text, preset):
    """KiCad position csv (Ref,Val,Package,PosX,PosY,Rot,Side) -> the preset's columns."""
    rd = csv.DictReader(io.StringIO(kicad_csv_text))
    side = preset["cpl"].get("side", {})
    header = [h for h, _ in preset["cpl"]["columns"]]
    rows = []
    for r in rd:
        r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
        out = []
        for _h, src in preset["cpl"]["columns"]:
            v = r.get(src, "")
            if src == "Side":
                v = side.get(v.lower(), v)
            elif src in ("PosX", "PosY") and v and not v.endswith("mm"):
                v = v + "mm" if preset["id"] == "jlcpcb" else v
            out.append(v)
        rows.append(out)
    return header, rows


def gerber_layers(board_layers, with_paste=True):
    copper = board_layers or ["F.Cu", "B.Cu"]
    tech = ["F.Mask", "B.Mask", "F.Silkscreen", "B.Silkscreen", "Edge.Cuts"]
    if with_paste:
        tech += ["F.Paste", "B.Paste"]
    return copper + tech


def _run(cmd, step):
    kw = {"capture_output": True, "text": True, "encoding": "utf-8", "errors": "replace"}
    if os.name == "nt":
        kw["creationflags"] = 0x08000000
    try:
        r = subprocess.run(cmd, timeout=600, **kw)
    except subprocess.TimeoutExpired:
        raise FabError(f"{step}: kicad-cli did not finish in 10 minutes.")
    except OSError as e:
        raise FabError(f"{step}: cannot start kicad-cli ({e}).")
    if r.returncode != 0:
        tail = "\n".join((r.stderr or r.stdout).strip().splitlines()[-4:])
        raise FabError(f"{step} failed (kicad-cli exit code {r.returncode}).\n{tail}")
    return r


def export(paths, req, preset, out_dir, opts, design=None, progress=lambda m: None, profile=None, checks=(),
           override_reason="", version_label="", clean=True, note=True):
    """opts: {"bom", "cpl", "step", "paste", "raw_pos"}: bool. Returns (files, notes).
    clean=True empties out_dir first (fab/<version>); with clean=False only the files made here are replaced."""
    cli = C.find_kicad_cli()
    if not cli:
        raise FabError("The plugin cannot find kicad-cli. Make sure that KiCad 10 is installed correctly.")
    board = paths["board"]
    name = os.path.splitext(os.path.basename(board))[0]
    with open(board, encoding="utf-8", errors="replace") as f:
        b = PF.parse(f.read())
    gdir = os.path.join(out_dir, "gerbers")
    if clean and os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    elif os.path.isdir(gdir):
        shutil.rmtree(gdir)                     # only the plugin's own Gerber folder
    os.makedirs(gdir)
    files, notes = [], []
    g = preset["gerber"]

    progress("Gerbers...")
    cmd = [cli, "pcb", "export", "gerbers", "-o", gdir + os.sep,
           "-l", ",".join(gerber_layers(b.layers, opts.get("paste", True)))]
    if not g.get("protel_ext", True):
        cmd.append("--no-protel-ext")
    if not g.get("x2", True):
        cmd.append("--no-x2")
    if not g.get("netlist", True):
        cmd.append("--no-netlist")
    if g.get("subtract_mask"):
        cmd.append("--subtract-soldermask")
    _run(cmd + [board], "Gerber export")

    progress("Drill files...")
    d = preset["drill"]
    cmd = [cli, "pcb", "export", "drill", "-o", gdir + os.sep, "--format", "excellon", "--excellon-units", "mm",
           "--generate-map", "--map-format", d.get("map", "gerberx2")]
    if d.get("separate_pth_npth", True):
        cmd.append("--excellon-separate-th")
    _run(cmd + [board], "Drill export")

    made = sorted(os.listdir(gdir))
    if not made:
        raise FabError("kicad-cli made no Gerber files.")
    zpath = os.path.join(out_dir, f"{name}{'-' + version_label if version_label else ''}-gerbers.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for fn in made:
            z.write(os.path.join(gdir, fn), fn)
    files.append(zpath)
    notes.append(f"Gerbers and drill: {len(made)} files in the zip ({', '.join(gerber_layers(b.layers, opts.get('paste', True)))}).")

    if opts.get("bom"):
        if design is None:
            notes.append("BOM: not made (the schematic could not be read).")
        else:
            progress("BOM...")
            header, rows = bom_rows(design, preset)
            p = os.path.join(out_dir, f"{name}-BOM-{preset['id']}.csv")
            write_csv(p, header, rows)
            files.append(p)
            notes.append(f"BOM: {len(rows)} lines.")

    if opts.get("cpl"):
        progress("Pick and place...")
        raw = os.path.join(out_dir, f"{name}-pos-kicad.csv")
        _run([cli, "pcb", "export", "pos", "-o", raw, "--format", "csv", "--units", "mm", "--side", "both",
              "--exclude-dnp", board], "Pick-and-place export")
        with open(raw, encoding="utf-8", errors="replace") as f:
            header, rows = convert_cpl(f.read(), preset)
        p = os.path.join(out_dir, f"{name}-CPL-{preset['id']}.csv")
        write_csv(p, header, rows)
        if opts.get("raw_pos"):
            keep = os.path.join(out_dir, f"{name}-pos.csv")
            os.replace(raw, keep)
            files.append(keep)
        else:
            os.remove(raw)
        files.append(p)
        notes.append(f"Pick and place: {len(rows)} parts.")

    if opts.get("step"):
        progress("3D model (STEP)...")
        p = os.path.join(out_dir, f"{name}.step")
        _run([cli, "pcb", "export", "step", "-o", p, "--subst-models", "-f", board], "STEP export")
        files.append(p)

    if note:
        p = os.path.join(out_dir, "FAB_NOTE.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write(fab_note(name, req, preset, b, profile, checks, override_reason, version_label, notes))
        files.append(p)
    return files, notes


def fab_note(name, req, preset, b, profile, checks, override_reason, version_label, notes):
    bb = b.bbox()
    lines = [f"FABRICATION NOTE - {name}", f"Made {datetime.datetime.now():%Y-%m-%d %H:%M} by Respin Zero",
             f"Version: {version_label or 'not saved in History'}", "",
             "BOARD",
             f"  Size: {bb[2] - bb[0]:.1f} x {bb[3] - bb[1]:.1f} mm" if bb else "  Size: no outline",
             f"  Copper layers: {len(b.layers)} ({', '.join(b.layers)})",
             f"  Finished thickness: {req.board_thickness_mm:g} mm",
             f"  Copper: outer {req.outer_copper_oz:g} oz" + (f", inner {req.inner_copper_oz:g} oz" if len(b.layers) > 2 else ""),
             f"  IPC-6012 class: {req.ipc_class}",
             f"  Minimum track / space: {req.fab_min_track_mm:g} / {req.fab_min_space_mm:g} mm",
             f"  Minimum drill: {req.fab_min_drill_mm:g} mm",
             f"  Fabricator: {profile['name'] if profile else 'not selected'}   Output format: {preset['name']}", "",
             "FINAL CHECKS"]
    lines += [f"  [{c.level.upper():4}] {c.title}" + (f" - {c.detail}" if c.detail else "") for c in checks]
    if override_reason:
        lines += ["", f"EXPORTED WITH BLOCKING CHECKS. Reason given: {override_reason}"]
    lines += ["", "FILES"] + [f"  {n}" for n in notes]
    if preset.get("note"):
        lines += ["", "UPLOAD", "  " + preset["note"]]
    return "\n".join(lines) + "\n"
