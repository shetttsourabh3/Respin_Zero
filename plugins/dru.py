"""Write the generated rules into .kicad_dru without touching the user's own rules."""
import os
import re

BEGIN = "# >>> IPC-STE generated rules: do not edit between these markers >>>"
END = "# <<< IPC-STE generated rules <<<"
USER_HEADER = ("# Your own rules go below this line. The plugin keeps them.\n"
               "# A later rule wins when two rules match, so your rules override the generated ones.")
_VERSION = re.compile(r"^\s*\(version\s+\d+\)\s*$", re.M)


def split(existing):
    """Return (generated_block_or_None, user_text)."""
    if not existing:
        return None, ""
    b, e = existing.find(BEGIN), existing.find(END)
    if b != -1 and e > b:
        gen = existing[b + len(BEGIN):e]
        user = existing[:b] + existing[e + len(END):]
    else:
        gen, user = None, existing
    user = _VERSION.sub("", user)
    user = user.replace(USER_HEADER, "")
    return gen, user.strip("\n")


def merge(existing, block):
    _, user = split(existing)
    parts = ["(version 1)", BEGIN, block.strip("\n"), END, "", USER_HEADER]
    if user.strip():
        parts.append(user)
    return "\n".join(parts) + "\n"


def write(path, block):
    """Merge and write. Keep one .bak of the previous file. Return True if user rules were kept."""
    existing = None
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            existing = f.read()
        with open(path + ".bak", "w", encoding="utf-8") as f:
            f.write(existing)
    text = merge(existing, block)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return bool(split(existing)[1].strip()) if existing else False
