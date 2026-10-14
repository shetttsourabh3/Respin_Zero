"""Project datasheet library.

Files live in <project>/datasheets/<Category>/<name>.pdf, with datasheets/index.json recording which
part (by symbol part name / value / MPN) each file belongs to and whether it may go to the AI.
Pure Python (no wx, no KiCad).
"""
import datetime
import json
import os
import re
import shutil
import urllib.request
from dataclasses import dataclass, field, asdict

FOLDER = "datasheets"
INDEX = "index.json"
CATEGORIES = ["MCU and modules", "Power", "Interface and protection", "Sensors", "Analog",
              "Memory", "Connectors", "Discrete", "Passives", "Other"]
MAX_AI_FILES = 12
MAX_AI_MB = 40
MPN_FIELDS = ("mpn", "manufacturer_part_number", "mfr part", "mfr_pn", "mfr. part #", "part number",
              "lcsc", "partnumber", "manufacturer part number")

_CAT_RULES = [
    ("MCU and modules", r"ESP32|ESP8266|STM32|RP2040|RP2350|NRF5|ATMEGA|ATTINY|SAMD|PIC\d|MCU|WROOM|MINI-1|MODULE|CH32|GD32|EFR32|CC26"),
    ("Power", r"LDO|REG|AP2112|AMS1117|TPS|LM\d{3,4}|MP\d{4}|BQ\d|MCP73|TP4056|BUCK|BOOST|PMIC|CHARG|XC62|RT\d{4}|SY8\d|ME6211|HT7"),
    ("Interface and protection", r"USB|CH340|CP210|FT23|ESD|TVS|USBLC|PESD|TPD|CAN|RS485|MAX3|LEVEL|TXS|PCA9|ISO"),
    ("Sensors", r"BME|BMP|BMI|BNO|MPU|ICM|LIS|ADXL|SHT|HDC|MAX301|MAX86|SENSOR|HX711|INA\d|ACS7|VL53|TMP\d"),
    ("Analog", r"OPA|LM358|MCP60|AD\d{3,4}|ADS\d|DAC|COMPAR|INA\d"),
    ("Memory", r"W25|FLASH|EEPROM|24C|AT24|PSRAM|FRAM|SD"),
]
_KIND_CAT = {"J": "Connectors", "D": "Discrete", "LED": "Discrete", "Q": "Discrete", "XTAL": "Discrete",
             "R": "Passives", "C": "Passives", "L": "Passives", "FB": "Passives", "SW": "Connectors"}


@dataclass
class Entry:
    file: str                      # path relative to the datasheets folder
    keys: list = field(default_factory=list)    # part keys this datasheet belongs to
    title: str = ""
    send_to_ai: bool = True
    source: str = ""               # where it came from (file name or URL)
    added: str = ""


@dataclass
class PartGroup:
    key: str                       # normalised part key
    label: str                     # what the user sees
    refs: list
    kind: str
    category: str
    mpn: str = ""
    url: str = ""                  # datasheet field from the symbol
    entry: Entry = None


def norm_key(text):
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def category(kind, text):
    if kind in _KIND_CAT and kind != "IC":
        return _KIND_CAT[kind]
    for cat, rx in _CAT_RULES:
        if re.search(rx, text or "", re.I):
            return cat
    return "Other" if kind == "IC" else _KIND_CAT.get(kind, "Other")


def safe_name(text):
    s = re.sub(r"[^A-Za-z0-9._+-]+", "_", text or "datasheet").strip("_")
    return s[:80] or "datasheet"


class Library:
    def __init__(self, project_dir):
        self.root = os.path.join(project_dir, FOLDER)
        self.entries = []
        self.load()

    # --- index
    def load(self):
        self.entries = []
        p = os.path.join(self.root, INDEX)
        if os.path.isfile(p):
            try:
                with open(p, encoding="utf-8") as f:
                    for e in json.load(f).get("datasheets", []):
                        self.entries.append(Entry(**{k: v for k, v in e.items() if k in Entry.__dataclass_fields__}))
            except (OSError, ValueError):
                pass
        self.entries = [e for e in self.entries if os.path.isfile(self.path(e))]

    def save(self):
        os.makedirs(self.root, exist_ok=True)
        with open(os.path.join(self.root, INDEX), "w", encoding="utf-8") as f:
            json.dump({"version": 1, "datasheets": [asdict(e) for e in self.entries]}, f, indent=2)

    def path(self, e):
        return os.path.join(self.root, e.file)

    def for_key(self, key):
        return next((e for e in self.entries if key in e.keys), None)

    # --- adding
    def add(self, src, group, title=""):
        """Copy a PDF into <Category>/<part>.pdf and link it to the part group."""
        cat_dir = os.path.join(self.root, group.category)
        os.makedirs(cat_dir, exist_ok=True)
        base = safe_name(group.mpn or group.label)
        ext = os.path.splitext(src)[1].lower() or ".pdf"
        dest = os.path.join(cat_dir, base + ext)
        n = 2
        while os.path.exists(dest) and os.path.abspath(dest) != os.path.abspath(src):
            dest = os.path.join(cat_dir, f"{base}_{n}{ext}")
            n += 1
        if os.path.abspath(dest) != os.path.abspath(src):
            shutil.copy2(src, dest)
        return self._link(dest, group, title or os.path.basename(src), os.path.basename(src))

    def _link(self, dest, group, title, source):
        rel = os.path.relpath(dest, self.root)
        for e in self.entries:
            if group.key in e.keys and e.file != rel:
                e.keys.remove(group.key)
        e = next((e for e in self.entries if e.file == rel), None)
        if e is None:
            e = Entry(rel, [], title, True, source, datetime.date.today().isoformat())
            self.entries.append(e)
        if group.key not in e.keys:
            e.keys.append(group.key)
        self.entries = [x for x in self.entries if x.keys]
        self.save()
        return e

    def unlink(self, group, delete_file=False):
        e = self.for_key(group.key)
        if not e:
            return
        e.keys.remove(group.key)
        if not e.keys:
            self.entries.remove(e)
            if delete_file:
                try:
                    os.remove(self.path(e))
                except OSError:
                    pass
        self.save()

    def set_ai(self, group, on):
        e = self.for_key(group.key)
        if e:
            e.send_to_ai = bool(on)
            self.save()

    def download(self, url, group, timeout=30):
        """Download a PDF from the symbol's Datasheet link. Raises on failure."""
        if not re.match(r"^https?://", url or "", re.I):
            raise ValueError("The symbol has no web link to a datasheet.")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (KiCad datasheet library)"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read(60 * 1024 * 1024)
            ctype = r.headers.get("Content-Type", "")
        if not data.startswith(b"%PDF") and "pdf" not in ctype.lower():
            raise ValueError("The link opens a web page, not a PDF. Download the PDF in your browser and use "
                             "Add datasheet.")
        cat_dir = os.path.join(self.root, group.category)
        os.makedirs(cat_dir, exist_ok=True)
        dest = os.path.join(cat_dir, safe_name(group.mpn or group.label) + ".pdf")
        with open(dest, "wb") as f:
            f.write(data)
        return self._link(dest, group, os.path.basename(dest), url)

    def auto_match(self, groups):
        """Link PDFs already in the folder whose file name contains a part's MPN or name."""
        linked = 0
        files = []
        for dirpath, _d, names in os.walk(self.root):
            files += [os.path.join(dirpath, n) for n in names if n.lower().endswith(".pdf")]
        for g in groups:
            if g.entry or g.kind in ("R", "C", "L", "FB"):
                continue
            keys = [k for k in (norm_key(g.mpn), norm_key(g.label)) if len(k) >= 4]
            for f in files:
                fk = norm_key(os.path.splitext(os.path.basename(f))[0])
                if any(k in fk or fk in k for k in keys if fk):
                    self._link(f, g, os.path.basename(f), "found in folder")
                    linked += 1
                    break
        return linked

    # --- for the AI
    def ai_files(self, groups, design=None):
        """[(label, refs, abs_path, size_mb, info)] for linked datasheets marked 'send to AI', within limits.
        info = {"mpn", "pins" (pin names used in the schematic), "cache"}."""
        out, total = [], 0.0
        for g in groups:
            e = g.entry
            if not e or not e.send_to_ai:
                continue
            p = self.path(e)
            mb = os.path.getsize(p) / 1e6
            if len(out) >= MAX_AI_FILES or total + mb > MAX_AI_MB:
                break
            if any(x[2] == p for x in out):
                continue
            pins = set()
            if design is not None:
                for r in g.refs:
                    c = design.comps.get(r)
                    if c:
                        pins |= {pn.name for pn in c.pins.values() if pn.name and pn.net}
            out.append((g.label, g.refs, p, mb, {"mpn": g.mpn or g.label, "pins": sorted(pins),
                                                 "cache": os.path.join(self.root, ".cache")}))
            total += mb
        return out


def groups_from_design(d, lib):
    """Group the design's parts by part name/value; attach linked datasheets."""
    groups = {}
    for c in d.comps.values():
        if c.kind == "ignore":
            continue
        mpn = next((c.fields[k] for k in MPN_FIELDS if c.fields.get(k) and c.fields[k] not in ("~", "")), "")
        label = c.value if c.kind in ("R", "C", "L", "FB") else (mpn or c.value or c.part)
        key = norm_key(mpn or (c.part if c.kind in ("R", "C", "L", "FB") else c.value or c.part))
        if c.kind in ("R", "C", "L", "FB"):
            key = norm_key(c.part + "_" + c.footprint.split(":")[-1])
            label = f"{c.part} {c.footprint.split(':')[-1]}".strip()
        g = groups.get(key)
        if not g:
            url = c.fields.get("datasheet", "")
            g = groups[key] = PartGroup(key, label, [], c.kind, category(c.kind, f"{c.value} {c.part} {mpn}"),
                                        mpn, "" if url in ("~", "") else url)
        g.refs.append(c.ref)
    for g in groups.values():
        g.refs.sort(key=lambda r: (re.sub(r"\d", "", r), int(re.sub(r"\D", "", r) or 0)))
        g.entry = lib.for_key(g.key)
    order = {c: i for i, c in enumerate(CATEGORIES)}
    return sorted(groups.values(), key=lambda g: (order.get(g.category, 99), g.label))
