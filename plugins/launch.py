#!/usr/bin/env python3
"""Open the Respin Zero without the PCB editor.

    <KiCad's python> launch.py [project.kicad_pro | project folder | .kicad_sch]

Use KiCad's own Python (it has wxPython and kicad-cli on its path):
  Windows:  "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" launch.py my_board.kicad_pro
  macOS:    /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 launch.py ...
  Linux:    python3 launch.py ...   (with python3-wxgtk4.0 and KiCad installed)
Or press 'Shortcut for schematic work' on the Overview tab once, inside KiCad, to make a desktop launcher.
"""
import importlib
import os
import sys

if __name__ == "__main__":
    os.environ["IPCSTE_STANDALONE"] = "1"
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.dirname(here))
    pkg = importlib.import_module(os.path.basename(here))
    sys.exit(importlib.import_module(pkg.__name__ + ".standalone").main())
