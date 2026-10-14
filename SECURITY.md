# Security and privacy

## Privacy model
- The plugin **never asks for, stores or sends passwords, API keys or tokens**. AI tools and Git use their own sign-in.
- Nothing leaves your computer unless you start it: **Review with AI**, **Download from symbol link**, **Push** or **Pull**.
- **What is sent?** shows the exact AI request. **Never send this project to AI** turns the AI review off for a project.
- AI tools run without shell access, in an empty temporary folder. Commands come only from the bundled list and your personal `~/.kicad_review/ai_tools.json`; **a project folder can never define a command**.
- Local model servers are allowed only on `localhost`.
- **Report a problem** contains no part, net or file contents; home and project paths are shortened.

## Supported versions
| Version | Supported |
|---|---|
| 4.x | Yes |
| < 4.0 | No |

## Report a vulnerability
Please **do not open a public issue**. Use GitHub's [private vulnerability reporting](../../security/advisories/new) for this repository. Describe the problem, the steps to reproduce it and the impact. You get an answer within 7 days.
