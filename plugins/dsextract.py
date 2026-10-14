"""Pick the datasheet pages that matter for one exact part, so the AI gets the right facts, not 200 pages.

Pages are scored by: the exact part number (ordering and variant tables), the pin names used in the
schematic, and section titles (pin description, absolute maximum ratings, application circuit...).
Text is cached per file in datasheets/.cache so a datasheet is read only once.
"""
import hashlib
import json
import os
import re
import sys

_VENDOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor")

SECTIONS = [
    (r"absolute\s+maximum", 40, "absolute maximum ratings"),
    (r"pin\s+(description|function|definition|configuration|assignment|list)|pin[- ]?out", 40, "pin description"),
    (r"recommended\s+operating", 30, "recommended operating conditions"),
    (r"typical\s+application|application\s+(circuit|information|schematic)|reference\s+(design|schematic)", 25,
     "application circuit"),
    (r"ordering\s+information|part\s+number(ing)?\s+(system|guide|information)|device\s+marking", 20,
     "ordering information"),
    (r"electrical\s+characteristics|dc\s+characteristics", 20, "electrical characteristics"),
    (r"strapping|boot\s+mode|power[- ]on\s+sequence|reset\s+(circuit|timing)", 18, "boot and reset"),
    (r"layout\s+(guide|recommend|consideration)|pcb\s+layout", 15, "layout guidelines"),
    (r"decoupling|bypass\s+capacitor|input\s+capacitor|output\s+capacitor", 10, "capacitors"),
    (r"thermal\s+(information|characteristics|resistance)", 8, "thermal"),
]
GENERIC_PINS = {"GND", "VCC", "VDD", "VSS", "NC", "IN", "OUT", "EN", "EP", "PAD", "~", "-"}


def _pypdf():
    try:
        import pypdf
        return pypdf
    except ImportError:
        if _VENDOR not in sys.path:
            sys.path.append(_VENDOR)
        import pypdf
        return pypdf


def available():
    try:
        _pypdf()
        return True
    except Exception:
        return False


def norm(text):
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def pages(path, cache_dir=None):
    """List of page texts. Cached by file content hash."""
    key = None
    if cache_dir:
        st = os.stat(path)
        key = hashlib.sha1(f"{os.path.basename(path)}|{st.st_size}|{int(st.st_mtime)}".encode()).hexdigest()[:16]
        cp = os.path.join(cache_dir, key + ".json")
        if os.path.isfile(cp):
            try:
                with open(cp, encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, ValueError):
                pass
    out = []
    try:
        import logging
        logging.getLogger("pypdf").setLevel(logging.ERROR)
        reader = _pypdf().PdfReader(path)
        for pg in reader.pages:
            try:
                out.append(re.sub(r"[ \t]+", " ", pg.extract_text() or ""))
            except Exception:
                out.append("")
    except Exception:
        return []
    if cache_dir and key:
        try:
            os.makedirs(cache_dir, exist_ok=True)
            with open(os.path.join(cache_dir, key + ".json"), "w", encoding="utf-8") as f:
                json.dump(out, f)
        except OSError:
            pass
    return out


def mpn_variants(mpn):
    """'AP2112K-3.3TRG1' -> ['AP2112K33TRG1', 'AP2112K33', 'AP2112K', ...] most specific first."""
    n = norm(mpn)
    out = [n] if len(n) >= 4 else []
    # trim packaging/reel suffixes step by step, but keep at least 5 characters
    m = n
    while len(m) > 5:
        m = m[:-1]
        if m not in out and re.search(r"\d", m):
            out.append(m)
    return out


def select(page_texts, mpn="", pin_names=(), budget=24000):
    """Return (text, chosen pages [1-based], reasons {page: [..]}, mpn_found: exact|family|no|unknown)."""
    if not page_texts:
        return "", [], {}, "unknown"
    variants = mpn_variants(mpn)
    exact = variants[0] if variants else ""
    whole = norm(" ".join(page_texts))
    family = next((v for v in variants[1:] if len(v) >= 6 and v in whole), "")
    pins = {p.upper() for p in pin_names if p and p.upper() not in GENERIC_PINS and len(p) >= 2}
    scores, reasons, found = [], {}, "no" if variants else "unknown"
    for i, t in enumerate(page_texts):
        s, why = 0, []
        low = t.lower()
        nt = norm(t)
        if i == 0:
            s += 30
            why.append("summary")
        if exact and exact in nt:
            s += 50
            why.append("exact part number")
            found = "exact"
        elif family and family in nt:
            s += 10
            if found == "no":
                found = "family"
        for rx, w, name in SECTIONS:
            if re.search(rx, low):
                s += w
                why.append(name)
        if pins:
            words = set(re.findall(r"[A-Z][A-Z0-9_/+-]{1,15}", t.upper()))
            hit = len(pins & words)
            if hit:
                s += min(40, hit * 4)
                why.append(f"{hit} used pin name(s)")
        if len(t.strip()) < 200:
            s -= 20                     # figure-only or blank pages
        scores.append((s, i))
        reasons[i + 1] = why
    chosen, used = [], 0
    for s, i in sorted(scores, key=lambda x: -x[0]):
        if s <= 0:
            break
        size = len(page_texts[i])
        if used + size > budget and chosen:
            continue
        chosen.append(i)
        used += size
        if used >= budget:
            break
    chosen.sort()
    text = "\n".join(f"--- page {i + 1} ({', '.join(reasons[i + 1]) or 'other'}) ---\n{page_texts[i][:budget]}"
                     for i in chosen)
    return text[:budget + 2000], [i + 1 for i in chosen], {i + 1: reasons[i + 1] for i in chosen}, found
