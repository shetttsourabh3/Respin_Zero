# Roadmap

## KiCad 11 support (keeps KiCad 10 working)

KiCad 11 removes the SWIG `pcbnew` Python API and moves plugins to the **IPC API** ([kicad-python](https://pypi.org/project/kicad-python/)). KiCad 11 also lets plugins run in the **Schematic Editor**.

Respin Zero is in a good position: the reviews, ERC/DRC, Power, Production, Fabrication, History and AI read the saved files or call `kicad-cli`. Only `plugins/board.py` uses the SWIG API, for six jobs: the toolbar button, saving the board, net names / layer count / thickness, Board Setup minimums, zoom to an item, and screen refresh.

| Step | Work | Result |
|---|---|---|
| A. Isolate | One small interface for those six jobs with three back ends: SWIG (KiCad 10), IPC (KiCad 11) and none (the standalone window). Board Setup minimums and the stackup are written to the project files. | KiCad 10 users see no change. |
| B. Spike on KiCad 11 nightly | A minimal IPC plugin (`plugin.json`) that opens the window from the PCB and Schematic Editors. Main question: does wxPython load in the plugin's Python environment on Windows, macOS and Linux? Fallback: open the window as its own process, as the standalone launcher already does. | The one real unknown is answered. |
| C. IPC back end | Save, nets, zoom to item, open from the Schematic Editor; tests with a fake IPC connection. | Same window on KiCad 11, also in the Schematic Editor. |
| D. One package, two entries | The SWIG action for KiCad 10 and the IPC action for KiCad 11. The desktop launcher stays for KiCad 10. | One install for both versions. |

## Reviews
- Chip profiles: ESP32-S3, ESP32-C6, nRF52, STM32G0/C0, RP2350, CH32V.
- Medical and safety skill pack: IEC 60601 creepage and clearance, isolation and leakage-current checklist.
- Assembly checks: missing part numbers, footprint package not matching the part number, parts not recommended for new designs.
- Learn from AI feedback: mark AI findings correct or wrong; wrong ones become a project skill.

## Release
- Verified BOM and pick-and-place formats from real orders (JLCPCB, PCBWay and Indian fabricators). Reports from real orders are very welcome.
- Publish in the KiCad Plugin and Content Manager after the beta.
