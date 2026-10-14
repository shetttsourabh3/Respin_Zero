# Third-party notices

Respin Zero bundles the following third-party software.

| Component | Version | License | Where | Used for |
|---|---|---|---|---|
| [pypdf](https://github.com/py-pdf/pypdf) | 6.20.1 | BSD 3-Clause | `plugins/vendor/pypdf/` (license in `plugins/vendor/pypdf/LICENSE`) | Reading text from datasheet PDFs. An installed pypdf is used first. |

The plugin runs these external programs if they are installed. They are not bundled and keep their own licenses:
KiCad's `kicad-cli`, `git`, and the AI command-line tools you choose (for example Claude Code, OpenAI Codex CLI, `llm`, Ollama).

Fabricator names (JLCPCB, PCBWay, NextPCB, PCB Power, Lion Circuits) are used only to name output formats and capability profiles. They are trademarks of their owners.
