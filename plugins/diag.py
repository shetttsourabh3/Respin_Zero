"""Log file and the 'Report a problem' text.

The report holds versions, the operating system, which tools were found and the end of the log. It holds no
design data: no part, net or file contents. Paths under the home folder are shortened to '~' and the project
folder is shown as '<project>'. The user reads the text before sending it anywhere.
"""
import json
import logging
import logging.handlers
import os
import platform
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(os.path.expanduser("~"), ".kicad_review", "logs")
LOG_FILE = os.path.join(LOG_DIR, "respin_zero.log")
log = logging.getLogger("respin_zero")


def setup_logging():
    if any(isinstance(h, logging.handlers.RotatingFileHandler) for h in log.handlers):
        return log
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        h = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=512 * 1024, backupCount=2, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(h)
        log.setLevel(logging.INFO)
    except OSError:
        pass
    return log


def _version_of(cmd):
    try:
        kw = {"creationflags": 0x08000000} if os.name == "nt" else {}
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15, **kw)
        return (r.stdout or r.stderr).strip().splitlines()[0][:80]
    except Exception:
        return "not found"


def scrub(text, project_dir=""):
    if project_dir:
        text = text.replace(project_dir, "<project>")
    home = os.path.expanduser("~")
    text = text.replace(home, "~")
    text = re.sub(r"(?i)(token|key|password|secret)=\S+", r"\1=<removed>", text)
    return text


def report(project_dir="", tab=""):
    from . import aiproviders as AP
    from . import checks as C
    from . import vcs as V
    from . import dsextract as E
    try:
        meta = json.load(open(os.path.join(os.path.dirname(HERE), "metadata.json")))
    except (OSError, ValueError):
        meta = {}
    try:
        import pcbnew
        kicad = pcbnew.Version()
    except Exception:
        kicad = "not loaded (window opened without the PCB editor)"
    try:
        import wx
        wxv = wx.version()
    except Exception:
        wxv = "?"
    cli = C.find_kicad_cli()
    git = V.git_exe()
    lines = ["RESPIN ZERO - PROBLEM REPORT",
             "Read this text before you send it. It has no part, net or file contents.", "",
             f"Plugin: {(meta.get('versions') or [{}])[0].get('version', '?')}   KiCad: {kicad}",
             f"OS: {platform.platform()}   Python: {sys.version.split()[0]}   wxPython: {wxv}",
             f"kicad-cli: {_version_of([cli, 'version']) if cli else 'not found'}",
             f"git: {_version_of([git, '--version']) if git else 'not found'}",
             f"PDF reader: {'bundled pypdf ok' if E.available() else 'not available'}",
             f"Open tab: {tab}", "", "AI tools:"]
    try:
        for p in AP.detect(all_tools=True):
            lines.append(f"  {p.id:14} {'found' if p.installed else 'not found':10} files={p.files_mode} ({p.origin})")
    except Exception as e:
        lines.append(f"  could not list: {e}")
    lines += ["", f"Last log lines ({LOG_FILE}):"]
    try:
        with open(LOG_FILE, encoding="utf-8", errors="replace") as f:
            lines += ["  " + l.rstrip() for l in f.readlines()[-120:]]
    except OSError:
        lines.append("  (no log yet)")
    return scrub("\n".join(lines), project_dir)
