"""Compare two versions of a project: review findings fixed and new, parts, nets, board and files.

Findings are compared when both versions were saved with the review snapshot (.respin_zero/findings.json,
written by Save version and by the Fabrication tab). Parts come from the .kicad_sch files and nets from the
.kicad_pcb file of each version, so kicad-cli is not needed.
"""
import json
import os
import re

from . import pcbfile as PF

SNAPSHOT = os.path.join(".respin_zero", "findings.json")
OLD_SNAPSHOT = os.path.join(".board_review", "findings.json")   # beta versions 4.0-4.3
MPN_KEYS = ("mpn", "manufacturer_part_number", "manufacturer part number", "mfr part", "lcsc")


def write_snapshot(project_dir, findings_by_tab):
    """findings_by_tab: {"Schematic": (open, waived), ...} with checks.Finding objects."""
    data = {"version": 1, "findings": []}
    for tab, (open_, waived) in findings_by_tab.items():
        for f, state in [(x, "open") for x in open_] + [(x, "waived") for x in waived]:
            data["findings"].append({"key": f.key, "tab": tab, "tier": f.tier, "type": f.type,
                                     "text": f.description[:200], "where": (f.location or "")[:120],
                                     "state": state, "source": f.source})
    p = os.path.join(project_dir, SNAPSHOT)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1)
    return p


_PROP = re.compile(r'\(property\s+"([^"]+)"\s+"((?:[^"\\]|\\.)*)"')


def parts_from_schematics(texts):
    """{ref: {"value", "footprint", "mpn", "lib"}} from the text of all .kicad_sch files of a version."""
    parts = {}
    for text in texts:
        i = text.find("(lib_symbols")
        if i >= 0:                                    # skip the embedded symbol library
            depth, j = 0, i
            while j < len(text):
                if text[j] == "(":
                    depth += 1
                elif text[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            text = text[:i] + text[j + 1:]
        for m in re.finditer(r'\(symbol\s*\n?\s*\(lib_id\s+"([^"]+)"', text):
            start = m.start()
            depth, j = 0, start
            while j < len(text):
                if text[j] == "(":
                    depth += 1
                elif text[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            block = text[start:j + 1]
            props = {k.lower(): v for k, v in _PROP.findall(block)}
            ref = props.get("reference", "")
            if not ref or ref.startswith("#"):
                continue
            refs = re.findall(r'\(reference\s+"([^"]+)"', block) or [ref]
            for r in refs:
                if r.startswith("#") or r.endswith("?"):
                    continue
                parts[r] = {"value": props.get("value", ""), "footprint": props.get("footprint", "").split(":")[-1],
                            "mpn": next((props[k] for k in MPN_KEYS if props.get(k, "~") not in ("", "~")), ""),
                            "lib": m.group(1)}
    return parts


def snapshot(repo, rev=None):
    """What a version contains. rev=None: the current files on disk."""
    if rev:
        files = repo.tracked(rev)
        read = lambda p: repo.read(rev, p)              # noqa: E731
    else:
        files = []
        for d, dirs, names in os.walk(repo.dir):
            dirs[:] = [x for x in dirs if not x.startswith(".") and x not in ("fab",) and not x.endswith("-backups")]
            files += [os.path.relpath(os.path.join(d, n), repo.dir) for n in names]
        files += [SNAPSHOT, OLD_SNAPSHOT]

        def read(p):
            try:
                with open(os.path.join(repo.dir, p), encoding="utf-8", errors="replace") as f:
                    return f.read()
            except OSError:
                return ""
    sch = [read(p) for p in files if p.endswith(".kicad_sch")]
    pcb = next((p for p in files if p.endswith(".kicad_pcb")), "")
    b = PF.parse(read(pcb)) if pcb else None
    snap = read(SNAPSHOT) or read(OLD_SNAPSHOT)
    try:
        findings = json.loads(snap)["findings"] if snap else None
    except (ValueError, KeyError):
        findings = None
    stats = {}
    if b is not None:
        bb = b.bbox()
        stats = {"layers": len(b.layers), "footprints": len(b.footprints), "tracks": len(b.segments),
                 "vias": len(b.vias), "track_mm": round(sum(getattr(s, "length", 0) for s in b.segments), 1),
                 "size": f"{bb[2] - bb[0]:.1f} x {bb[3] - bb[1]:.1f} mm" if bb else "no outline"}
    return {"parts": parts_from_schematics(sch), "nets": set(b.nets) if b else set(), "board": stats,
            "findings": findings}


def compare(a, b):
    res = {}
    pa, pb = a["parts"], b["parts"]
    res["parts_added"] = sorted(set(pb) - set(pa))
    res["parts_removed"] = sorted(set(pa) - set(pb))
    res["parts_changed"] = []
    for r in sorted(set(pa) & set(pb)):
        ch = [f"{k}: {pa[r][k] or '-'} -> {pb[r][k] or '-'}" for k in ("value", "footprint", "mpn", "lib")
              if pa[r][k] != pb[r][k]]
        if ch:
            res["parts_changed"].append((r, ch))
    res["nets_added"] = sorted(n for n in b["nets"] - a["nets"] if n)
    res["nets_removed"] = sorted(n for n in a["nets"] - b["nets"] if n)
    res["board"] = [(k, a["board"].get(k), b["board"].get(k)) for k in ("size", "layers", "footprints", "tracks",
                                                                       "vias")
                    if a["board"].get(k) != b["board"].get(k)]
    if a["findings"] is None or b["findings"] is None:
        res["findings"] = None
    else:
        fa = {f["key"]: f for f in a["findings"] if f["state"] == "open"}
        fb = {f["key"]: f for f in b["findings"] if f["state"] == "open"}
        wb = {f["key"] for f in b["findings"] if f["state"] == "waived"}
        res["findings"] = {"fixed": [fa[k] for k in fa if k not in fb and k not in wb],
                           "waived": [fa[k] for k in fa if k in wb],
                           "new": [fb[k] for k in fb if k not in fa],
                           "still": [fb[k] for k in fb if k in fa]}
    return res


def _tier_order(f):
    return {"Blocks fabrication": 0, "Reliability risk": 1}.get(f["tier"], 2)


def report_text(res, name_a, name_b, files):
    L = [f"COMPARE  {name_a}  ->  {name_b}", ""]
    fd = res["findings"]
    if fd is None:
        L += ["REVIEW FINDINGS", "  Not compared: one of the versions was saved without review results.",
              "  (Run the checks before 'Save version', so the next comparison has them.)", ""]
    else:
        nb = lambda xs: sum(1 for f in xs if f["tier"] == "Blocks fabrication")   # noqa: E731
        L += [f"REVIEW FINDINGS  fixed {len(fd['fixed'])} ({nb(fd['fixed'])} blocking), new {len(fd['new'])} "
              f"({nb(fd['new'])} blocking), waived {len(fd['waived'])}, still open {len(fd['still'])}"]
        for title, key in (("Fixed", "fixed"), ("New", "new"), ("Waived since", "waived")):
            if fd[key]:
                L.append(f"  {title}:")
                L += [f"    [{f['tier']}] {f['tab']}: {f['text'][:110]}" for f in sorted(fd[key], key=_tier_order)[:40]]
        L.append("")
    L.append(f"PARTS  added {len(res['parts_added'])}, removed {len(res['parts_removed'])}, "
             f"changed {len(res['parts_changed'])}")
    if res["parts_added"]:
        L.append("  Added: " + ", ".join(res["parts_added"][:60]))
    if res["parts_removed"]:
        L.append("  Removed: " + ", ".join(res["parts_removed"][:60]))
    L += [f"  {r}: {'; '.join(ch)}" for r, ch in res["parts_changed"][:60]]
    L += ["", f"NETS ON THE BOARD  added {len(res['nets_added'])}, removed {len(res['nets_removed'])}"]
    if res["nets_added"]:
        L.append("  Added: " + ", ".join(res["nets_added"][:60]))
    if res["nets_removed"]:
        L.append("  Removed: " + ", ".join(res["nets_removed"][:60]))
    L += ["", "BOARD"] + ([f"  {k}: {x} -> {y}" for k, x, y in res["board"]] or ["  No change in size, layers, "
                                                                                    "parts, tracks or vias."])
    L += ["", f"FILES  {len(files)} changed"] + [f"  {st:8} {p}" for st, p in files[:80]]
    return "\n".join(L) + "\n"
