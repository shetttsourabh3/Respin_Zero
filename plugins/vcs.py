"""Version history for a KiCad project through the user's own git (no passwords or tokens are handled here:
push and pull use the user's git credential manager or SSH key).

Each saved version is a git commit. The plugin adds trailers with the review state at that moment, so the
History tab can show progress over time. Milestones are annotated tags.
"""
import os
import re
import subprocess
import tempfile

from .aiproviders import find_exe, _env

GITIGNORE = """# KiCad (added by Respin Zero)
*-backups/
.history/
_autosave-*
*.kicad_prl
fp-info-cache
*.lck
~*.lck
*.bak
*.ipcste.bak
datasheets/.cache/
production/
*-ipc-ste-report.txt
*-ipc-ste-power.txt
*-review-schematic.txt
"""

MILESTONES = ["", "Design started", "Schematic done", "Layout done", "Review passed", "Sent to fab",
              "Boards received", "Bring-up done", "Release"]
TRAILERS = ("Milestone", "Review-Blocks", "Review-Risks", "Review-Cosmetic", "Review-Waived", "Review-Checks",
            "Board")
CATEGORY = [(r"^\.(respin_zero|board_review)/", "Review"), (r"\.kicad_sch$", "Schematic"), (r"\.kicad_pcb$", "Board"), (r"\.kicad_(dru|pro)$|ipc_ste_", "Rules"),
            (r"^datasheets/|/datasheets/", "Datasheets"), (r"\.(kicad_sym|kicad_mod|pretty/)|sym-lib|fp-lib", "Libraries"),
            (r"^fab/|/fab/|\.(gbr|drl|zip|pos|csv|step)$|gerber|production", "Fabrication")]


class GitError(RuntimeError):
    pass


def git_exe():
    return find_exe("git")


def category(path):
    for rx, name in CATEGORY:
        if re.search(rx, path, re.I):
            return name
    return "Other"


class Commit:
    def __init__(self, h, short, author, date, subject, body, refs):
        self.hash, self.short, self.author, self.date, self.subject = h, short, author, date, subject
        self.body = body
        self.refs = refs
        self.tags = [r[5:] for r in refs if r.startswith("tag: ")]
        self.trailers = {}
        for line in body.splitlines():
            m = re.match(r"^([A-Za-z-]+):\s*(.*)$", line.strip())
            if m and m.group(1) in TRAILERS:
                self.trailers[m.group(1)] = m.group(2)
        self.message = "\n".join(l for l in body.splitlines()
                                 if not re.match(r"^(%s):" % "|".join(TRAILERS), l.strip())).strip()

    def num(self, key):
        try:
            return int(self.trailers.get(key, ""))
        except ValueError:
            return None

    @property
    def milestone(self):
        return self.trailers.get("Milestone", "")

    @property
    def state(self):
        """'block', 'risk', 'ok' or '' (not recorded)."""
        b, r = self.num("Review-Blocks"), self.num("Review-Risks")
        if b is None:
            return ""
        return "block" if b else ("risk" if r else "ok")


class Repo:
    def __init__(self, project_dir):
        self.dir = project_dir
        self.exe = git_exe()
        self.top = None
        if self.exe:
            code, out, _ = self._git(["rev-parse", "--show-toplevel"], check=False)
            self.top = out.strip() if code == 0 and out.strip() else None

    # --- plumbing
    def _git(self, args, check=True, timeout=60, cwd=None):
        if not self.exe:
            raise GitError("Git is not installed. Install it from https://git-scm.com/ and open this window again.")
        env = _env()
        env["GIT_TERMINAL_PROMPT"] = "0"          # never wait for a password the user cannot see
        env["GIT_OPTIONAL_LOCKS"] = "0"
        kw = {"creationflags": 0x08000000} if os.name == "nt" else {}
        try:
            r = subprocess.run([self.exe] + args, cwd=cwd or self.top or self.dir, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=timeout, env=env, **kw)
        except subprocess.TimeoutExpired:
            raise GitError(f"git {args[0]} did not finish in {timeout} s.")
        if check and r.returncode != 0:
            raise GitError(_explain(args, (r.stderr or r.stdout).strip()))
        return r.returncode, r.stdout, r.stderr

    @property
    def ok(self):
        return bool(self.top)

    def rel_project(self):
        return os.path.relpath(self.dir, self.top) if self.top else "."

    # --- setup
    def init(self):
        self._git(["init"], cwd=self.dir)
        self.top = self.dir
        gi = os.path.join(self.dir, ".gitignore")
        old = open(gi, encoding="utf-8").read() if os.path.isfile(gi) else ""
        if "IPC STE Design Assistant" not in old and "Respin Zero" not in old:
            with open(gi, "a", encoding="utf-8") as f:
                f.write(("\n" if old and not old.endswith("\n") else "") + GITIGNORE)

    def identity(self):
        name = self._git(["config", "user.name"], check=False)[1].strip()
        mail = self._git(["config", "user.email"], check=False)[1].strip()
        return name, mail

    def set_identity(self, name, mail):
        self._git(["config", "user.name", name])
        self._git(["config", "user.email", mail])

    # --- state
    def branch(self):
        code, out, _ = self._git(["rev-parse", "--abbrev-ref", "HEAD"], check=False)
        return out.strip() if code == 0 else "(no versions yet)"

    def has_commits(self):
        return self._git(["rev-parse", "--verify", "-q", "HEAD"], check=False)[0] == 0

    def changes(self):
        """[(status, path)] for files in this project folder that differ from the last version."""
        _c, out, _ = self._git(["status", "--porcelain=v1", "-uall", "--", self.rel_project()])
        res = []
        for line in out.splitlines():
            if len(line) > 3:
                st, path = line[:2].strip() or "M", line[3:].strip().strip('"')
                if " -> " in path:
                    path = path.split(" -> ")[1]
                res.append(({"??": "new", "A": "new", "D": "deleted", "R": "renamed"}.get(st, "changed"), path))
        return res

    def remote(self):
        code, out, _ = self._git(["remote", "get-url", "origin"], check=False)
        return out.strip() if code == 0 else ""

    def set_remote(self, url):
        if self.remote():
            self._git(["remote", "set-url", "origin", url])
        else:
            self._git(["remote", "add", "origin", url])

    def ahead_behind(self):
        code, out, _ = self._git(["rev-list", "--left-right", "--count", "@{u}...HEAD"], check=False)
        if code != 0:
            return None
        behind, ahead = (int(x) for x in out.split())
        return ahead, behind

    def log(self, limit=300):
        if not self.has_commits():
            return []
        fmt = "%H%x1f%h%x1f%an%x1f%aI%x1f%s%x1f%b%x1f%D%x1e"
        rel = self.rel_project()
        _c, out, _ = self._git(["log", f"-n{limit}", f"--format={fmt}"] + (["--", rel] if rel != "." else []))
        res = []
        for rec in out.split("\x1e"):
            parts = rec.strip("\n").split("\x1f")
            if len(parts) >= 7:
                refs = [r.strip() for r in parts[6].split(",") if r.strip()]
                res.append(Commit(parts[0], parts[1], parts[2], parts[3], parts[4], parts[5], refs))
        return list(reversed(res))                       # oldest first, like a timeline

    def files(self, commit):
        _c, out, _ = self._git(["show", "--name-status", "--format=", commit.hash])
        res = []
        for line in out.splitlines():
            bits = line.split("\t")
            if len(bits) >= 2:
                st = {"A": "new", "D": "deleted", "M": "changed"}.get(bits[0][:1], "changed")
                res.append((st, bits[-1]))
        return res

    def tracked(self, rev):
        """Paths (relative to the project folder) of the files in a version."""
        rel = self.rel_project()
        _c, out, _ = self._git(["ls-tree", "-r", "--name-only", rev, "--", rel])
        return [os.path.relpath(os.path.join(self.top, l), self.dir) for l in out.splitlines() if l.strip()]

    def read(self, rev, path):
        """Text of a project file in a version ('' if it is not there)."""
        rel = os.path.relpath(os.path.join(self.dir, path), self.top).replace(os.sep, "/")
        code, out, _ = self._git(["show", f"{rev}:{rel}"], check=False)
        return out if code == 0 else ""

    def diff_names(self, a, b=None):
        """[(status, path)] between two versions, or between a version and the current files (b=None)."""
        args = ["diff", "--name-status", a] + ([b] if b else []) + ["--", self.rel_project()]
        _c, out, _ = self._git(args)
        res = []
        for line in out.splitlines():
            bits = line.split("\t")
            if len(bits) >= 2:
                res.append(({"A": "new", "D": "deleted", "M": "changed", "R": "renamed"}.get(bits[0][:1], "changed"),
                            os.path.relpath(os.path.join(self.top, bits[-1]), self.dir)))
        return res

    # --- actions
    def save(self, message, trailers, tag="", tag_message=""):
        if not message.strip():
            raise GitError("Write what changed in this version.")
        self._git(["add", "-A", "--", self.rel_project()])
        if not self._git(["diff", "--cached", "--quiet"], check=False)[0] and not tag:
            raise GitError("Nothing changed since the last version. Save the schematic and board first.")
        body = message.strip() + "\n\n" + "\n".join(f"{k}: {v}" for k, v in trailers.items() if v != "")
        fd, path = tempfile.mkstemp(suffix=".txt")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body + "\n")
        try:
            args = ["commit", "-F", path]
            if self._git(["diff", "--cached", "--quiet"], check=False)[0] == 0:
                args.append("--allow-empty")            # milestone on an unchanged design
            self._git(args)
        finally:
            os.remove(path)
        if tag:
            self.tag(tag, tag_message or message)

    def tag(self, name, message, commit="HEAD"):
        if self._git(["check-ref-format", f"refs/tags/{name}"], check=False)[0] != 0:
            raise GitError(f"'{name}' cannot be a version name. Use letters, digits, '.', '-' or '_', no spaces.")
        self._git(["tag", "-a", name, "-m", message, commit])

    def push(self):
        if not self.remote():
            raise GitError("No remote yet. Use 'Remote...' to add the address of your GitHub/GitLab repository.")
        self._git(["push", "-u", "origin", "HEAD", "--follow-tags"], timeout=300)

    def pull(self):
        if not self.remote():
            raise GitError("No remote yet. Use 'Remote...' first.")
        self._git(["pull", "--ff-only"], timeout=300)

    def export(self, commit, dest_zip):
        self._git(["archive", "--format=zip", "-o", dest_zip, commit.hash, "--", self.rel_project()])


def _explain(args, err):
    low = err.lower()
    if "could not read username" in low or "authentication failed" in low or "permission denied (publickey)" in low \
            or "terminal prompts disabled" in low:
        return ("Git could not sign in to the remote. Sign in once outside KiCad (for example run 'git push' in a "
                "terminal, or set up Git Credential Manager or an SSH key); the plugin never asks for passwords.\n\n"
                + err[-300:])
    if "please tell me who you are" in low or "user.email" in low:
        return "Git needs your name and e-mail for the history. Set them in the History tab (Save version)."
    if "non-fast-forward" in low or "fetch first" in low or "rejected" in low:
        return "The remote has newer versions. Use Pull first, then Push.\n\n" + err[-300:]
    if "not possible to fast-forward" in low or "diverg" in low:
        return ("Your versions and the remote versions went different ways. Merge them with a Git tool; KiCad files "
                "cannot be merged automatically.\n\n" + err[-300:])
    return f"git {args[0]} failed: {err[-400:]}"
