"""Run an AI review through a command-line tool the user has installed and signed in to.

The plugin never sees passwords or tokens: it calls the user's own CLI, which uses the user's own
account. Tools are run with no file or shell access, in an empty temporary folder, at low priority.
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import re
import time

HOME = os.path.expanduser("~")


def _search_dirs():
    """KiCad started from the Dock/Start menu gets a short PATH, so look in the usual install places."""
    dirs = os.environ.get("PATH", "").split(os.pathsep)
    dirs += [os.path.join(HOME, ".local", "bin"), os.path.join(HOME, ".claude", "local"),
             "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", os.path.join(HOME, ".npm-global", "bin"),
             os.path.join(HOME, ".volta", "bin"), os.path.join(HOME, ".bun", "bin")]
    dirs += sorted(glob.glob(os.path.join(HOME, ".nvm", "versions", "node", "*", "bin")), reverse=True)
    if os.name == "nt":
        appdata = os.environ.get("APPDATA", "")
        local = os.environ.get("LOCALAPPDATA", "")
        dirs += [os.path.join(appdata, "npm"), os.path.join(HOME, ".local", "bin"),
                 os.path.join(local, "Programs", "claude"), os.path.join(local, "Microsoft", "WinGet", "Links")]
    seen, out = set(), []
    for d in dirs:
        if d and d not in seen and os.path.isdir(d):
            seen.add(d)
            out.append(d)
    return out


def find_exe(name):
    names = [name + ext for ext in (".exe", ".cmd", ".bat", "")] if os.name == "nt" else [name]
    for d in _search_dirs():
        for n in names:
            p = os.path.join(d, n)
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return p
    return None


def _env(drop=()):
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join(_search_dirs())          # npm-installed CLIs need node on PATH
    for k in drop:
        env.pop(k, None)
    return env


def _tail(text, n=400):
    """Last meaningful lines of an error output (the real cause is usually at the end)."""
    lines = [l for l in (text or "").strip().splitlines() if l.strip()]
    return "\n".join(lines[-4:])[-n:] if lines else ""


def _popen(cmd, env, cwd, stdin_text):
    kw = {"stdin": subprocess.PIPE, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE,
          "text": True, "encoding": "utf-8", "errors": "replace", "cwd": cwd, "env": env}
    if os.name == "nt":
        kw["creationflags"] = 0x08000000 | 0x00004000          # no window, below-normal priority
    else:
        kw["preexec_fn"] = lambda: os.nice(10)                  # keep KiCad responsive
    return subprocess.Popen(cmd, **kw)


class Cancelled(Exception):
    pass


class Result:
    def __init__(self, text, billing, cost=None, seconds=0.0, raw="", model="", files_shared=0):
        self.text, self.billing, self.cost, self.seconds, self.raw = text, billing, cost, seconds, raw
        self.model, self.files_shared = model, files_shared


def _stage_files(work, files):
    """Copy datasheets into the review folder with clear names; return the list text for the AI."""
    lines = []
    notes = []
    for i, f in enumerate(files, 1):
        label, refs, path = f[0], f[1], f[2]
        name = f"{i:02d}_{re.sub(r'[^A-Za-z0-9._-]+', '_', label)[:50]}{os.path.splitext(path)[1] or '.pdf'}"
        shutil.copy2(path, os.path.join(work, name))
        mpn = _info(f).get("mpn", label)
        hint = ""
        try:
            pg, _t, chosen, reasons, found = _relevant(f, 30000)
            if chosen:
                hint = (f"; start with pages {_pages(chosen)} of {len(pg)}"
                        f" ({'; '.join(sorted({w for p in chosen for w in reasons.get(p, [])}))[:160]})")
                notes.append(f"{label}: pages {_pages(chosen)} of {len(pg)} suggested")
            note = _mpn_note(found, mpn)
            hint += f"; {note}" if note else ""
        except Exception:
            pass
        lines.append(f"  {name}: datasheet of {label}, part number {mpn} (used as {', '.join(refs[:12])}){hint}")
    _stage_files.notes = notes
    return lines


MAX_TEXT_TOTAL = 150000


def _ds():
    from . import dsextract
    return dsextract


def text_extract_available():
    return _ds().available()


def _info(f):
    return f[4] if len(f) > 4 else {"mpn": f[0], "pins": [], "cache": None}


def _relevant(f, budget):
    label, refs, path = f[0], f[1], f[2]
    info = _info(f)
    pg = _ds().pages(path, info.get("cache"))
    text, chosen, reasons, found = _ds().select(pg, info.get("mpn", ""), info.get("pins", ()), budget)
    return pg, text, chosen, reasons, found


def _mpn_note(found, mpn):
    return {"exact": f"exact part number {mpn} found in the datasheet",
            "family": f"only the part family of {mpn} found: check the variant (voltage, package, temperature)",
            "no": f"part number {mpn} NOT found in this datasheet: it may be the wrong file",
            }.get(found, "")


def _text_block(files, budget_total=MAX_TEXT_TOTAL):
    """Relevant datasheet pages as text. Returns (text, number of files included, notes)."""
    if not files:
        return "", 0, []
    per = max(8000, budget_total // len(files))
    parts, n, notes = [], 0, []
    for f in files:
        pg, text, chosen, _r, found = _relevant(f, per)
        if not text.strip():
            notes.append(f"{f[0]}: no text in the PDF (scanned image?)")
            continue
        mpn = _info(f).get("mpn", f[0])
        parts.append(f"\n\n# DATASHEET: {f[0]} (part number {mpn}; used as {', '.join(f[1][:12])})\n"
                     f"# {len(chosen)} of {len(pg)} pages, chosen for this exact part and the pins it uses. "
                     f"{_mpn_note(found, mpn)}.\n{text}")
        notes.append(f"{f[0]}: pages {_pages(chosen)} of {len(pg)}" + (" - part number not found" if found == "no" else ""))
        n += 1
    if not parts:
        return "", 0, notes
    return ("\n\n# DATASHEETS. Text from the pages that matter for each part (tables can be garbled). Use the "
            "values for the EXACT part number given (variant, voltage, package). Cite datasheet and page in the "
            "finding detail." + "".join(parts)), n, notes


def _pages(nums):
    out, run = [], []
    for x in nums:
        if run and x == run[-1] + 1:
            run.append(x)
        else:
            if run:
                out.append(f"{run[0]}-{run[-1]}" if len(run) > 1 else str(run[0]))
            run = [x]
    if run:
        out.append(f"{run[0]}-{run[-1]}" if len(run) > 1 else str(run[0]))
    return ", ".join(out)


class Provider:
    id = name = exe_name = ""
    help_url = ""
    models = [("Default (the tool's own setting)", "")]
    files_mode = "text"          # "read": the tool opens the PDFs itself; "text": extracted text is sent; "none"
    billing = "your account"
    origin = "built-in"

    @property
    def reads_pdfs(self):
        return self.files_mode == "read" or (self.files_mode == "text" and text_extract_available())

    @property
    def short(self):
        return self.name.split(" (")[0]

    ds_notes = []

    def list_models(self):
        return self.models

    def __init__(self):
        self.exe = find_exe(self.exe_name)
        self.proc = None
        self.cancelled = False

    @property
    def installed(self):
        return bool(self.exe)

    def account(self):
        """(signed_in: bool, text for the user, env_drop list)."""
        return True, "", []

    def cancel(self):
        self.cancelled = True
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.kill()
            except OSError:
                pass

    def _run(self, cmd, env, stdin_text, timeout, cwd):
        self.cancelled = False
        t0 = time.time()
        self.proc = _popen(cmd, env, cwd, stdin_text)
        try:
            out, err = self.proc.communicate(stdin_text, timeout=timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            raise RuntimeError(f"The AI tool did not answer in {timeout // 60} minutes.")
        if self.cancelled:
            raise Cancelled()
        return out, err, self.proc.returncode, time.time() - t0


class ClaudeCode(Provider):
    id, name, exe_name = "claude", "Claude Code (Claude Pro / Max account)", "claude"
    help_url = "https://code.claude.com/docs/en/setup"
    models = [("Default (Claude Code setting)", ""), ("Opus", "opus"), ("Sonnet", "sonnet"), ("Haiku", "haiku")]
    files_mode = "read"

    def account(self):
        """Prefer the user's Claude subscription: an ANTHROPIC_API_KEY would otherwise be billed instead."""
        if not self.exe:
            return False, "Claude Code is not installed.", []
        has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
        for drop in ((["ANTHROPIC_API_KEY"], ) if has_key else ()) + ([],):
            try:
                r = subprocess.run([self.exe, "auth", "status"], capture_output=True, text=True, timeout=30,
                                   env=_env(drop), **({"creationflags": 0x08000000} if os.name == "nt" else {}))
            except (OSError, subprocess.TimeoutExpired) as e:
                return False, f"Claude Code did not answer ({e}).", []
            try:
                info = json.loads(r.stdout or "{}")
            except ValueError:
                info = {}
            method = info.get("authMethod", "")
            self.method = method
            if r.returncode == 0 and method in ("claude.ai", "oauth_token"):
                return True, "Signed in with your Claude account. Reviews use your plan's usage limits.", drop
            if r.returncode == 0 and method and drop == []:
                return True, f"Signed in with {method}. Reviews are billed to that API account.", []
        return False, "Claude Code is not signed in. In a terminal, run:  claude auth login", []

    def review(self, instructions, data, timeout=900, model="", files=()):
        ok, _msg, drop = self.account()
        if not ok:
            raise RuntimeError("Claude Code is not signed in. In a terminal, run:  claude auth login")
        work = tempfile.mkdtemp(prefix="kicad-ai-")
        sp = os.path.join(work, "instructions.txt")
        with open(sp, "w", encoding="utf-8") as f:
            f.write(instructions)
        if files:
            listing = _stage_files(work, files)
            self.ds_notes = getattr(_stage_files, "notes", [])
            data += ("\n\n# DATASHEETS in your working folder. Read the ones you need with the Read tool (PDF).\n"
                     "# Use them to confirm pin functions, absolute maximum ratings and required external parts.\n"
                     "# Use the values for the EXACT part number given (variant, voltage, package).\n"
                     "# Cite the datasheet file and page in the finding detail.\n" + "\n".join(listing))
            tools = ["--tools", "Read", "--allowedTools", "Read", "--permission-mode", "dontAsk", "--max-turns", "40"]
        else:
            tools = ["--tools", ""]
        cmd = [self.exe, "-p", "--output-format", "json"] + tools + ["--disallowedTools", "mcp__*",
               "--no-session-persistence", "--system-prompt-file", sp]
        if model:
            cmd += ["--model", model]
        cmd.append("Review the design in the input. Reply with the JSON object only.")
        out, err, code, secs = self._run(cmd, _env(drop), data, timeout, work)
        try:
            info = json.loads(out)
        except ValueError:
            raise RuntimeError(_tail(err or out) or "Claude Code gave no answer.")
        if info.get("is_error") or code != 0:
            raise RuntimeError(_tail(str(info.get("result") or err)) or "Claude Code reported an error.")
        billing = "Claude plan" if getattr(self, "method", "") in ("claude.ai", "oauth_token") else "API account"
        used = info.get("modelUsage") or {}
        model_used = ", ".join(used.keys()) if isinstance(used, dict) and used else str(info.get("model") or model or "")
        return Result(info.get("result", ""), billing, info.get("total_cost_usd"), secs, out,
                      model_used or "not reported", len(files))


class Codex(Provider):
    id, name, exe_name = "codex", "OpenAI Codex CLI (ChatGPT account)", "codex"
    help_url = "https://learn.chatgpt.com/docs/auth"

    def account(self):
        if not self.exe:
            return False, "Codex CLI is not installed.", []
        signed = os.path.isfile(os.path.join(os.environ.get("CODEX_HOME", os.path.join(HOME, ".codex")), "auth.json"))
        return True, ("Uses the account you signed in with in Codex CLI." if signed else
                      "If the review fails, sign in first: run  codex  in a terminal."), []

    def configured_model(self):
        cfg = os.path.join(os.environ.get("CODEX_HOME", os.path.join(HOME, ".codex")), "config.toml")
        try:
            with open(cfg, encoding="utf-8") as f:
                for line in f:
                    m = re.match(r'\s*model\s*=\s*"([^"]+)"', line)
                    if m:
                        return m.group(1)
        except OSError:
            pass
        return ""

    def review(self, instructions, data, timeout=900, model="", files=()):
        work = tempfile.mkdtemp(prefix="kicad-ai-")
        out_file = os.path.join(work, "reply.txt")
        cmd = [self.exe, "exec", "--sandbox", "read-only", "--skip-git-repo-check", "--ephemeral",
               "-o", out_file]
        if model:
            cmd += ["--model", model]
        cmd.append("-")
        extra, nfiles, self.ds_notes = _text_block(files) if files else ("", 0, [])
        out, err, code, secs = self._run(cmd, _env(), instructions + "\n\n" + data + extra, timeout, work)
        text = ""
        if os.path.isfile(out_file):
            with open(out_file, encoding="utf-8", errors="replace") as f:
                text = f.read()
        if code != 0 and not text:
            raise RuntimeError(_tail(err or out) or "Codex reported an error.")
        return Result(text or out, "ChatGPT account", None, secs, out,
                      model or self.configured_model() or "Codex default (not reported)", nfiles)


# ---------------------------------------------------------------------------------------------------------
# Generic tools, defined in JSON (bundled ai_tools.json + the user's ~/.kicad_review/ai_tools.json).
# No vendor code: any command-line tool, or any OpenAI-compatible server on this computer.
# Project folders cannot define tools: a downloaded project must never be able to run a command.

BUNDLED_TOOLS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai_tools.json")
PERSONAL_TOOLS = os.path.join(HOME, ".kicad_review", "ai_tools.json")
PLACEHOLDERS = ("{model}", "{system_file}", "{prompt_file}", "{output_file}", "{workdir}")


def _subst(args, values):
    out = []
    for a in args:
        for k, v in values.items():
            a = a.replace(k, v)
        out.append(a)
    return out


class CommandTool(Provider):
    """A command-line tool. The command is run directly (no shell), in an empty temporary folder.

    Definition keys: id, name, command (list), prompt: stdin | file, system: separate | merged,
    output: stdout | file | json:<key>, model_args (list, added when a model is chosen), models,
    list_models (command whose first column is a model name), files: read | text | none,
    billing, timeout, help_url, env_drop.
    """

    def __init__(self, d, origin):
        self.d, self.origin = d, origin
        self.id, self.name = d["id"], d.get("name", d["id"])
        self.exe_name = d["command"][0]
        self.help_url = d.get("help_url", "")
        self.files_mode = d.get("files", "text")
        self.billing = d.get("billing", "the tool's own account")
        self.models = [tuple(m) for m in d.get("models", [])]
        if not self.models and not d.get("model_required"):
            self.models = [("Default (the tool's own setting)", "")]
        if not any(v == "" for _, v in self.models) and not d.get("model_required"):
            self.models.insert(0, ("Default (the tool's own setting)", ""))
        self._listed = None
        super().__init__()

    def list_models(self):
        cmd = self.d.get("list_models")
        if not cmd or not self.exe:
            return self.models
        if self._listed is None:
            self._listed = []
            exe = find_exe(cmd[0])
            try:
                r = subprocess.run([exe] + cmd[1:], capture_output=True, text=True, timeout=10, env=_env(),
                                   **({"creationflags": 0x08000000} if os.name == "nt" else {}))
                for line in r.stdout.splitlines()[1 if self.d.get("list_skip_header", True) else 0:]:
                    if line.split():
                        name = line.split(": ", 1)[1].split()[0] if ": " in line else line.split()[0]
                        self._listed.append((name, name))
            except (OSError, subprocess.TimeoutExpired, TypeError):
                pass
        known = {v for _, v in self.models}
        return self.models + [m for m in self._listed if m[1] not in known]

    def account(self):
        if not self.exe:
            return False, f"{self.short} is not installed (no '{self.exe_name}' found).", []
        return True, f"Uses {self.billing}.", []

    def review(self, instructions, data, timeout=None, model="", files=()):
        d = self.d
        if d.get("model_required") and not model:
            raise RuntimeError(f"{self.short} needs a model. Choose one in the Model list.")
        work = tempfile.mkdtemp(prefix="kicad-ai-")
        sysf, promptf, outf = (os.path.join(work, n) for n in ("instructions.txt", "request.txt", "reply.txt"))
        nfiles = 0
        if files and self.files_mode == "read":
            data += ("\n\n# DATASHEETS in your working folder (PDF). Read the ones you need. Use the values for the "
                     "EXACT part number given. Name the datasheet and page in the finding detail.\n"
                     + "\n".join(_stage_files(work, files)))
            self.ds_notes = getattr(_stage_files, "notes", [])
            nfiles = len(files)
        elif files and self.files_mode == "text":
            extra, nfiles, self.ds_notes = _text_block(files)
            data += extra
        merged = d.get("system", "merged") == "merged"
        body = (instructions + "\n\n" + data) if merged else data
        with open(sysf, "w", encoding="utf-8") as f:
            f.write(instructions)
        with open(promptf, "w", encoding="utf-8") as f:
            f.write(body)
        vals = {"{model}": model, "{system_file}": sysf, "{prompt_file}": promptf, "{output_file}": outf,
                "{workdir}": work}
        cmd = [self.exe] + _subst(d["command"][1:], vals)
        if model and d.get("model_args"):
            at = d.get("model_at", len(cmd))
            cmd[at:at] = _subst(d["model_args"], vals)
        stdin = body if d.get("prompt", "stdin") == "stdin" else ""
        out, err, code, secs = self._run(cmd, _env(d.get("env_drop", ())), stdin,
                                         int(timeout or d.get("timeout", 900)), work)
        mode = d.get("output", "stdout")
        text = out
        if mode == "file" and os.path.isfile(outf):
            with open(outf, encoding="utf-8", errors="replace") as f:
                text = f.read()
        elif mode.startswith("json:"):
            try:
                text = str(json.loads(out).get(mode[5:], ""))
            except ValueError:
                pass
        if code != 0 and not text.strip():
            raise RuntimeError(_tail(err or out) or f"{self.short} reported an error (exit code {code}).")
        if not text.strip():
            raise RuntimeError(f"{self.short} gave no answer. " + _tail(err))
        return Result(text, self.billing, None, secs, out, model or "tool default (not reported)", nfiles)


class LocalServer(Provider):
    """An OpenAI-compatible chat server on this computer (Ollama, LM Studio, llama.cpp, vLLM, Jan...).

    Only loopback addresses are allowed, so no key or token is ever needed or handled by the plugin.
    Definition keys: id, name, type: "local_server", base_url, models, files (text | none), timeout.
    """

    def __init__(self, d, origin):
        import urllib.parse
        self.d, self.origin = d, origin
        self.id, self.name = d["id"], d.get("name", d["id"])
        self.base = d.get("base_url", "http://127.0.0.1:11434/v1").rstrip("/")
        self.ports = [int(p) for p in d.get("ports", [])]
        host = urllib.parse.urlparse(self.base).hostname or ""
        self.local = host in ("localhost", "127.0.0.1", "::1")
        self.files_mode = d.get("files", "text")
        self.billing = "this computer (local model)"
        self.models = [tuple(m) for m in d.get("models", [])]
        self.help_url = d.get("help_url", "")
        self._listed = None
        self.proc, self.cancelled, self.exe = None, False, self.base

    @property
    def installed(self):
        """Find a running server: the configured address first, then the usual ports on this computer."""
        if not self.local:
            return False
        import urllib.parse
        u = urllib.parse.urlparse(self.base)
        cands = [self.base] + [f"{u.scheme}://127.0.0.1:{p}{u.path}" for p in self.ports if p != u.port]
        for base in cands:
            try:
                self.base = base
                self._get("/models", timeout=1)
                return True
            except Exception:
                continue
        self.base = cands[0]
        return False

    def _get(self, path, timeout=3):
        import urllib.request
        with urllib.request.urlopen(self.base + path, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))

    def list_models(self):
        if self._listed is None:
            try:
                self._listed = [(m["id"], m["id"]) for m in self._get("/models").get("data", [])]
            except Exception:
                self._listed = []
        known = {v for _, v in self.models}
        return (self.models + [m for m in self._listed if m[1] not in known]) or [("(no model found)", "")]

    def account(self):
        if not self.local:
            return False, "Only servers on this computer (localhost) are allowed.", []
        try:
            self._get("/models")
        except Exception:
            return False, f"No server answers at {self.base}. Start {self.short} first.", []
        return True, f"Local server at {self.base}. Nothing leaves this computer.", []

    def cancel(self):
        self.cancelled = True

    def review(self, instructions, data, timeout=None, model="", files=()):
        import urllib.request
        ok, msg, _ = self.account()
        if not ok:
            raise RuntimeError(msg)
        model = model or next((v for _, v in self.list_models() if v), "")
        if not model:
            raise RuntimeError("The local server has no model loaded.")
        nfiles = 0
        if files and self.files_mode != "none":
            extra, nfiles, self.ds_notes = _text_block(files)
            data += extra
        body = json.dumps({"model": model, "temperature": 0.1, "stream": False,
                           "messages": [{"role": "system", "content": instructions},
                                        {"role": "user", "content": data}]}).encode("utf-8")
        req = urllib.request.Request(self.base + "/chat/completions", data=body,
                                     headers={"Content-Type": "application/json"})
        self.cancelled = False
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=int(timeout or self.d.get("timeout", 1800))) as r:
                info = json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:
            if self.cancelled:
                raise Cancelled()
            raise RuntimeError(f"The local server failed: {e}")
        if self.cancelled:
            raise Cancelled()
        text = ((info.get("choices") or [{}])[0].get("message") or {}).get("content", "")
        return Result(text, self.billing, None, time.time() - t0, json.dumps(info)[:4000],
                      info.get("model") or model, nfiles)


BUILTIN = {"claude": ClaudeCode, "codex": Codex}


def load_definitions():
    """[(definition, origin)]. The personal file can add tools, replace a bundled one by id,
    or hide one with {"id": "...", "disabled": true}."""
    defs, order = {}, []
    for path, origin in ((BUNDLED_TOOLS, "bundled"), (PERSONAL_TOOLS, "personal")):
        try:
            with open(path, encoding="utf-8") as f:
                items = json.load(f).get("tools", [])
        except (OSError, ValueError):
            continue
        for d in items:
            if not isinstance(d, dict) or not d.get("id"):
                continue
            if d["id"] not in defs:
                order.append(d["id"])
            base = defs.get(d["id"], ({}, origin))[0]
            defs[d["id"]] = ({**base, **d}, origin)
    return [defs[i] for i in order if not defs[i][0].get("disabled")]


def make(d, origin):
    t = d.get("type", "command")
    if t == "builtin":
        p = BUILTIN[d["id"]]()
        if d.get("models"):
            p.models = [tuple(m) for m in d["models"]]
        p.origin = origin
        return p
    if t == "local_server":
        return LocalServer(d, origin)
    if not d.get("command"):
        raise ValueError("no command")
    return CommandTool(d, origin)


def detect(all_tools=False):
    out = []
    for d, origin in load_definitions():
        try:
            p = make(d, origin)
        except (KeyError, ValueError, TypeError):
            continue
        if all_tools or p.installed:
            out.append(p)
    return out


PERSONAL_TEMPLATE = {
    "_help": ("Your own AI tools. Each tool is run with no shell, in an empty temporary folder. "
              "Placeholders: {model} {system_file} {prompt_file} {output_file} {workdir}. "
              "prompt: stdin|file. system: merged|separate. output: stdout|file|json:<key>. "
              "files: read (tool opens PDFs in its folder) | text (extracted text is sent) | none. "
              "type: command | local_server (OpenAI-compatible, localhost only). "
              "Hide a bundled tool with {\"id\": \"ollama\", \"disabled\": true}."),
    "tools": [
        {"id": "my-tool", "name": "My AI tool (example, edit me)", "disabled": True,
         "command": ["mytool", "--no-history"], "prompt": "stdin", "system": "merged", "output": "stdout",
         "model_args": ["--model", "{model}"], "models": [["Default", ""]], "files": "text",
         "billing": "my company account", "timeout": 900}
    ]
}


def ensure_personal_file():
    if not os.path.isfile(PERSONAL_TOOLS):
        os.makedirs(os.path.dirname(PERSONAL_TOOLS), exist_ok=True)
        with open(PERSONAL_TOOLS, "w", encoding="utf-8") as f:
            json.dump(PERSONAL_TEMPLATE, f, indent=2)
    return PERSONAL_TOOLS
