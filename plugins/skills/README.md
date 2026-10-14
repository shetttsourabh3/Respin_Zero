# Review skills

Put Markdown files with your own review rules in one of these folders:

* `<project>/review_skills/` – rules for one project (commit them with the design)
* `~/.kicad_review/skills/` – your personal rules for all projects

Each `*.md` file, or each folder with a `SKILL.md` file, is one skill. Optional front matter:

```
---
name: usb-layout-rules
description: Our USB 2.0 layout rules
applies_to: pcb        # schematic | pcb | both
---
```

The AI review adds the active skills to its instructions. Turn skills on or off in the
**Skills...** dialog. Each skill is limited to 20 000 characters, all skills together to 60 000.
