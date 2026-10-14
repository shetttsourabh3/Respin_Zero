# Contributing

Thank you for helping. Bug reports, chip profiles, fabricator formats, fixes and documentation are all welcome.

## Report a bug
1. In the plugin, open **Overview** and press **Report a problem...**. Copy the text.
2. Open a [bug report](../../issues/new?template=bug_report.yml) and paste it. The report has versions, the tools found and the log, and **no design data**. Read it before you post.
3. If you can, attach a small project that shows the problem.

## Add a chip profile (no Python needed)
Chip profiles are JSON files in `plugins/profiles/`. Read `plugins/profiles/README.md`, copy a profile that is close, and fill in the pins from the datasheet. **Every rule must name its datasheet source** (document, revision and section or table). Add a test design in `tests/` if you can.

## Add or correct a fabricator format
Output formats are in `plugins/fab_presets.json`; capability profiles are in `plugins/manufacturers.json`. Link the fabricator's current public guide in your pull request.

## Development setup
```bash
git clone https://github.com/YOUR-GITHUB-USERNAME/respin-zero.git
cd respin-zero
python3 -m pip install pytest
# Linux: sudo apt install python3-wxgtk4.0 xvfb
xvfb-run -a python3 -m pytest -q tests        # or: python -m pytest -q tests  (window test is skipped without wx)
python3 tools/build_zip.py                     # build the install zip
```
The tests run without KiCad: the package is imported in standalone mode, and `kicad-cli`, `git` and AI tools are replaced by small stand-ins.

To try your change in KiCad, build the zip and install it with **Plugin and Content Manager > Install from File**.

## Code layout
| Path | What |
|---|---|
| `plugins/gui/` | The window, one module per page (`tab_*.py`), sidebar (`nav.py`), shared widgets |
| `plugins/core.py` | Glue between the window and the checks |
| `plugins/rules.py`, `dru.py`, `manufacturers.py` | Questions, IPC rules, fabricator profiles |
| `plugins/schreview.py`, `profiles/` | Schematic checks and chip profiles |
| `plugins/checks.py`, `powercheck.py` | ERC/DRC sorting, power and thermal |
| `plugins/aiproviders.py`, `aireview.py`, `ailayout.py`, `dsextract.py` | AI tools, requests, reply checks, datasheet pages |
| `plugins/fab.py`, `vcs.py`, `compare.py` | Fabrication outputs, Git history, version compare |
| `plugins/board.py` | The only module that uses KiCad's SWIG `pcbnew` API (see [roadmap](docs/roadmap.md)) |

## Rules for changes
- **Keep KiCad's API in `board.py` only.** Everything else reads saved files or calls `kicad-cli`. This keeps the move to KiCad 11 small.
- **Never handle passwords, keys or tokens.** AI tools and Git use their own sign-in.
- **No network calls** except the ones the user starts (AI review, datasheet download, Git push/pull).
- **Write user text in plain, short sentences** (the project follows ASD-STE100 Simplified Technical English where it can): one instruction per sentence, active voice, no jargon without an explanation.
- Add or update a test for every change in behaviour. `python -m pytest -q tests` must pass.
- Update `CHANGELOG.md` under *Unreleased*.

## Pull requests
1. Fork, create a branch (`fix/short-name` or `feat/short-name`), make the change with tests.
2. Open the pull request with the template. Add screenshots for UI changes (light and dark mode if you can).
3. CI must pass on Linux, Windows and macOS.

By contributing you agree that your contribution is licensed under the [MIT License](LICENSE).
