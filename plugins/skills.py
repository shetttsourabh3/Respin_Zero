"""Review skills: Markdown files with your own review rules, added to the AI instructions.

Where the plugin looks (a skill with the same name in a later place replaces an earlier one):
  1. bundled:   <plugin>/skills/
  2. personal:  ~/.kicad_review/skills/           (all your projects)
  3. project:   <project>/review_skills/          (this project; commit it with the design)
In each place: any *.md file, or a folder with a SKILL.md file (the Claude skill layout).

Optional front matter at the top of the file:
  ---
  name: usb-layout-rules
  description: Our USB 2.0 layout rules
  applies_to: pcb          # schematic | pcb | both (default both)
  ---
"""
import glob
import os
import re
import shutil
from dataclasses import dataclass

HERE = os.path.dirname(__file__)
PERSONAL = os.path.join(os.path.expanduser("~"), ".kicad_review", "skills")
PROJECT_DIR = "review_skills"
MAX_SKILL_CHARS = 20_000
MAX_TOTAL_CHARS = 60_000


@dataclass
class Skill:
    name: str
    description: str
    applies_to: str      # schematic / pcb / both
    path: str
    origin: str          # bundled / personal / project
    text: str

    def applies(self, mode):
        return self.applies_to in ("both", mode)


def _parse(path, origin):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            raw = f.read()
    except OSError:
        return None
    meta, body = {}, raw
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", raw, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip().lower()] = v.strip().strip('"\'')
        body = m.group(2)
    base = os.path.basename(path)
    default = os.path.basename(os.path.dirname(path)) if base.upper() == "SKILL.MD" else os.path.splitext(base)[0]
    scope = meta.get("applies_to", meta.get("scope", "both")).lower()
    if scope not in ("schematic", "pcb", "both"):
        scope = "both"
    first = next((l.strip("# ").strip() for l in body.splitlines() if l.strip()), "")
    return Skill(meta.get("name", default), meta.get("description", first[:100]), scope, path, origin,
                 body.strip()[:MAX_SKILL_CHARS])


def _files(folder):
    if not folder or not os.path.isdir(folder):
        return []
    files = sorted(glob.glob(os.path.join(folder, "*.md")))
    files += sorted(glob.glob(os.path.join(folder, "*", "SKILL.md")))
    return [f for f in files if os.path.basename(f).upper() != "README.MD"]


def folders(project_dir):
    return [("bundled", os.path.join(HERE, "skills")), ("personal", PERSONAL),
            ("project", os.path.join(project_dir, PROJECT_DIR) if project_dir else "")]


def discover(project_dir):
    found = {}
    for origin, folder in folders(project_dir):
        for f in _files(folder):
            s = _parse(f, origin)
            if s and s.text:
                found[s.name] = s
    return sorted(found.values(), key=lambda s: ({"project": 0, "personal": 1, "bundled": 2}[s.origin], s.name))


def active(project_dir, mode, disabled=()):
    return [s for s in discover(project_dir) if s.applies(mode) and s.name not in set(disabled)]


def instructions_block(skills):
    """Text appended to the AI instructions, within a size budget."""
    if not skills:
        return "", []
    out, used, total = ["", "ADDITIONAL REVIEW RULES FROM THE USER'S SKILL FILES.",
                        "Apply them in this review. They come before general practice when they conflict.",
                        "Name the skill in the finding detail when a finding comes from it."], [], 0
    for s in skills:
        if total + len(s.text) > MAX_TOTAL_CHARS:
            break
        out += ["", f"=== SKILL: {s.name} ({s.description}) ===", s.text]
        used.append(s.name)
        total += len(s.text)
    return "\n".join(out), used


def add_file(src, project_dir, personal=False):
    """Copy a skill file (or a folder's SKILL.md) into the project or personal skills folder."""
    dest_dir = PERSONAL if personal else os.path.join(project_dir, PROJECT_DIR)
    os.makedirs(dest_dir, exist_ok=True)
    if os.path.basename(src).upper() == "SKILL.MD":
        name = os.path.basename(os.path.dirname(src)) or "skill"
        target = os.path.join(dest_dir, name)
        os.makedirs(target, exist_ok=True)
        dest = os.path.join(target, "SKILL.md")
    else:
        dest = os.path.join(dest_dir, os.path.basename(src))
    shutil.copy2(src, dest)
    return dest


TEMPLATE = """---
name: my-review-rules
description: What these rules are for (one line)
applies_to: both        # schematic | pcb | both
---

# My review rules

Write each rule as a short instruction with the reason. Examples:

- Every connector pin that leaves the board has an ESD diode within 5 mm of the connector.
- Decoupling capacitors for MCU power pins are placed within 2 mm of the pin, on the same layer.
- USB D+/D- length mismatch is below 0.5 mm, with no vias and a solid ground plane under the pair.
- We use only 0402 or larger passives (our assembler cannot place 0201).
- Patient-connected circuits need 4 mm creepage to any mains-referenced copper (IEC 60601-1, 2 MOPP).
"""


def create_template(project_dir):
    folder = os.path.join(project_dir, PROJECT_DIR)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "my-review-rules.md")
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(TEMPLATE)
    return path
