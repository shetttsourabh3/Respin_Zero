"""Open the assistant without the PCB editor, for example while you work in the Schematic Editor.

KiCad 10 runs plugins only in the PCB editor (schematic plugins arrive in KiCad 11). This module opens the same
window from a project file. Tabs that need the live board (apply Board Setup values, show on board) say so.
"""
import os
import sys


def project_paths(pro):
    base = os.path.splitext(os.path.abspath(pro))[0]
    d = os.path.dirname(base)
    from .board import CFG_NAME
    return {"board": base + ".kicad_pcb", "sch": base + ".kicad_sch", "dru": base + ".kicad_dru",
            "cfg": os.path.join(d, CFG_NAME), "dir": d, "report": base + "-ipc-ste-report.txt"}


def find_project(path):
    """Accept a .kicad_pro, .kicad_sch, .kicad_pcb or a folder."""
    if not path:
        return None
    path = os.path.abspath(path)
    if os.path.isdir(path):
        pros = sorted(f for f in os.listdir(path) if f.endswith(".kicad_pro"))
        return os.path.join(path, pros[0]) if pros else None
    base, ext = os.path.splitext(path)
    if ext in (".kicad_pro", ".kicad_sch", ".kicad_pcb"):
        return base + ".kicad_pro"
    return None


def main(argv=None):
    import wx
    argv = sys.argv[1:] if argv is None else argv
    app = wx.App(False)
    cfg = wx.Config("IPC_STE_Assistant")
    pro = find_project(argv[0]) if argv else None
    if not pro:
        last = cfg.Read("standalone_last", "")
        with wx.FileDialog(None, "Open a KiCad project", defaultDir=os.path.dirname(last) if last else "",
                           wildcard="KiCad project (*.kicad_pro)|*.kicad_pro", style=wx.FD_OPEN) as fd:
            if fd.ShowModal() != wx.ID_OK:
                return 0
            pro = fd.GetPath()
    cfg.Write("standalone_last", pro)
    cfg.Flush()
    from . import core, ui
    paths = project_paths(pro)
    core._STANDALONE_BOARD["path"] = paths["board"]
    frame = ui.show(None, paths)
    frame.Bind(wx.EVT_CLOSE, lambda e: (e.Skip(), app.ExitMainLoop()))
    app.MainLoop()
    return 0


def python_for_launch():
    """The Python that has wxPython and KiCad's modules: KiCad's own when we run inside KiCad."""
    exe = sys.executable or ""
    cands = []
    if os.name == "nt":
        cands += [os.path.join(os.path.dirname(exe), "python.exe"), os.path.join(sys.prefix, "python.exe"),
                  os.path.join(sys.prefix, "bin", "python.exe")]
    elif sys.platform == "darwin":
        cands += [os.path.join(sys.prefix, "bin", "python3"), exe]
    else:
        cands += [exe if "python" in os.path.basename(exe) else "", "/usr/bin/python3"]
    for c in cands:
        if c and os.path.isfile(c) and "python" in os.path.basename(c).lower():
            return c
    return "python3"


def create_shortcut(pro, desktop=None):
    """Write a double-click launcher for one project on the desktop. Returns its path."""
    here = os.path.dirname(os.path.abspath(__file__))
    launch = os.path.join(here, "launch.py")
    py = python_for_launch()
    name = os.path.splitext(os.path.basename(pro))[0]
    desktop = desktop or os.path.join(os.path.expanduser("~"), "Desktop")
    if not os.path.isdir(desktop):
        desktop = os.path.dirname(pro)
    if os.name == "nt":
        path = os.path.join(desktop, f"Respin Zero - {name}.bat")
        body = f'@echo off\r\nstart "" "{py.replace("python.exe", "pythonw.exe") if os.path.isfile(py.replace("python.exe", "pythonw.exe")) else py}" "{launch}" "{pro}"\r\n'
    elif sys.platform == "darwin":
        path = os.path.join(desktop, f"Respin Zero - {name}.command")
        body = f'#!/bin/sh\nexec "{py}" "{launch}" "{pro}"\n'
    else:
        path = os.path.join(desktop, f"respin-zero-{name}.desktop")
        body = ("[Desktop Entry]\nType=Application\nName=Respin Zero - " + name + "\n"
                f'Exec="{py}" "{launch}" "{pro}"\nIcon={os.path.join(here, "icon.png")}\nTerminal=false\n')
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(body)
    if os.name != "nt":
        os.chmod(path, 0o755)
    return path
