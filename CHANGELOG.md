# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]
### Fixed
- Tests: the stand-in command-line tools now run on Windows (through a `.cmd` launcher), so CI passes on Windows.
### Planned
- KiCad 11 support through the IPC API, including the Schematic Editor. See [docs/roadmap.md](docs/roadmap.md).

## [4.4.0] - 2026-10-14
### Changed
- New name: **Respin Zero** (formerly *Board Review Assistant*). Your settings, waivers and saved versions are kept; the review snapshot folder is now `.respin_zero/` and the old `.board_review/` is still read.
- New logo and plugin icon.
- Overview text says "1 risk", not "1 risks".
### Added
- Repository files for GitHub: README with screenshots, license, contributing guide, security policy, issue and pull-request templates, user guide and roadmap.

## [4.3.0] - 2026-10-14
### Changed
- Review pages show results first: filter chips with counts, **Group by** severity, part or check, plain-language titles, severity dots and a side-by-side detail card (where, what is wrong, how to fix, why it matters).
- An orange bar warns when the schematic or board changed after the last run, with **Run again**.
- Keys: Enter shows on board, W waives, Ctrl+C copies a finding, Ctrl+F searches.
### Fixed
- Filter chips could fail to draw on some wxPython versions.
- The "Next" button dropped the "&" in "Power & thermal".

## [4.2.0] - 2026-10-14
### Changed
- Sidebar navigation grouped by stage (Set up, Review, Release) with live status badges, page headers, a **Next** button, a status chip and **Run all checks** in the header.
- Keyboard shortcuts Ctrl+1…0, Ctrl+Page Up/Down, Ctrl+R, Ctrl+B, F1. The sidebar can collapse to icons.
- The AI review box folds to one line.

## [4.1.0] - 2026-10-14
### Added
- **Production files** page: one-click Gerber zip, position file and BOM.

## [4.0.0] - 2026-10-13
### Added
- **Fabrication** page: final checks, Gerbers, drill, BOM, pick-and-place, STEP and a fab note in JLCPCB, PCBWay or generic format, saved as a *Sent to fab* version.
- **Compare** two versions in History.
- **Report a problem** and a log file.
- Automated tests and a CI workflow.
### Changed
- Renamed from *IPC STE Design Assistant* to *Respin Zero*. Settings are kept.
- One entry for local model servers, found on the usual ports.
- The standalone window no longer edits the stackup.
### Fixed
- Two imports broken by the move to one module per page.
- A crash when the window closed while a check was still running.

## [3.5.0] - 2026-10-13
### Added
- History page with Git: versions, milestones, push and pull, timeline.
- Datasheet pages chosen for each exact part number, with a bundled PDF reader.
- Standalone launcher to use the window beside the Schematic Editor.

## [3.4.0] - 2026-10-13
### Added
- Datasheets page and datasheets shared with the AI review.
- Works with any AI tool: Claude Code, Codex CLI, `llm`, Ollama, local servers or your own command-line tool. The model used is shown.

## [3.3.0] and earlier
- AI schematic and layout review with your own account, review skills, schematic review with chip profiles, power and thermal check, waivers, fabricator profiles, experience levels and KiCad 10 support.

[Unreleased]: https://github.com/YOUR-GITHUB-USERNAME/respin-zero/compare/v4.4.0...HEAD
[4.4.0]: https://github.com/YOUR-GITHUB-USERNAME/respin-zero/releases/tag/v4.4.0
[4.3.0]: https://github.com/YOUR-GITHUB-USERNAME/respin-zero/releases/tag/v4.3.0
