"""FindingsPanel."""
from .common import *  # noqa: F401,F403
from .dialogs import SkillsDialog
from . import findings_view as FV


class FindingsPanel(wx.Panel):
    """Run button, filter toggles with counts, search, list, detail and actions."""

    def __init__(self, parent, frame, kind):
        super().__init__(parent)
        self.frame, self.kind = frame, kind            # kind: "check", "power" or "sch"
        self.all, self.rows, self.notes, self.ran, self.appendix = [], [], [], (), None
        self.running, self._uuids, self.on_done = False, None, None
        self.waivers = W.Waivers(frame.paths["dir"])
        base = os.path.splitext(frame.paths["board"])[0]
        self.report_path = {"check": frame.paths["report"], "power": base + "-ipc-ste-power.txt",
                            "sch": base + "-review-schematic.txt"}[kind]

        s = wx.BoxSizer(wx.VERTICAL)
        top = wx.BoxSizer(wx.HORIZONTAL)
        self.run_btn = primary_button(self, {"check": "Run ERC and DRC", "power": "Run power and thermal check",
                                             "sch": "Run schematic review"}[kind])
        self.run_btn.Bind(wx.EVT_BUTTON, lambda e: self.run())
        self.save_first = wx.CheckBox(self, label="Save the board first")
        self.save_first.SetValue(True)
        self.save_first.SetToolTip("The checks read the saved files.")
        if kind == "sch" or frame.board is None:
            self.save_first.Hide()
        self.gauge = wx.Gauge(self, range=100, size=(140, 12))
        self.gauge.Hide()
        self.progress = muted(wx.StaticText(self, label=""))
        top.Add(self.run_btn, 0, wx.RIGHT, 10)
        top.Add(self.save_first, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)
        top.Add(self.gauge, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        top.Add(self.progress, 1, wx.ALIGN_CENTER_VERTICAL)
        self.report_btn = wx.Button(self, label="Open report")
        self.report_btn.SetToolTip("The full text report, with notes and the waiver audit record.")
        self.report_btn.Bind(wx.EVT_BUTTON, lambda e: self.on_report(None))
        self.report_btn.Disable()
        top.Add(self.report_btn, 0, wx.ALIGN_CENTER_VERTICAL)
        s.Add(top, 0, wx.EXPAND | wx.ALL, 10)
        if kind == "sch":
            s.Add(self._ai_bar(), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        elif kind == "check":
            s.Add(self._ai_bar(), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # stale banner: the files changed after the last run
        self.stale = wx.Panel(self)
        self.stale.SetBackgroundColour(FV._soft(TIER_COLOUR[C.RISK]))
        sb = wx.BoxSizer(wx.HORIZONTAL)
        self.stale_text = wx.StaticText(self.stale, label="")
        rerun = wx.Button(self.stale, label="Run again", style=wx.BU_EXACTFIT)
        rerun.Bind(wx.EVT_BUTTON, lambda e: self.run())
        sb.Add(self.stale_text, 1, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 8)
        sb.Add(rerun, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.stale.SetSizer(sb)
        self.stale.Hide()
        s.Add(self.stale, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.headline = bold(wx.StaticText(self, label=""), 2)
        s.Add(self.headline, 0, wx.LEFT | wx.RIGHT, 10)

        flt = wx.BoxSizer(wx.HORIZONTAL)
        self.toggles = {}
        for key in (C.BLOCK, C.RISK, C.COSMETIC, "Waived"):
            t = FV.Chip(self, key, TIER_COLOUR.get(key, wx.Colour(120, 120, 120)), self.refresh)
            t.SetValue(key in (C.BLOCK, C.RISK) or (key == C.COSMETIC and frame.req.level != "Beginner"))
            self.toggles[key] = t
            flt.Add(t, 0, wx.RIGHT, 8)
        flt.AddStretchSpacer()
        flt.Add(muted(wx.StaticText(self, label="Group by")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.group = wx.Choice(self, choices=["Severity", "Part", "Check", "None"])
        self.group.SetSelection(wx.Config("IPC_STE_Assistant").ReadInt("group_" + kind, 0))
        self.group.Bind(wx.EVT_CHOICE, self._group_changed)
        flt.Add(self.group, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        self.search = wx.SearchCtrl(self, size=(220, -1))
        self.search.ShowCancelButton(True)
        self.search.SetDescriptiveText("Search  (Ctrl+F)")
        self.search.Bind(wx.EVT_TEXT, lambda e: self.refresh())
        flt.Add(self.search, 0, wx.ALIGN_CENTER_VERTICAL)
        s.Add(flt, 0, wx.EXPAND | wx.ALL, 10)

        split = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE | wx.SP_THIN_SASH)
        left = wx.Panel(split)
        self.lst = wx.ListCtrl(left, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_THEME)
        il = wx.ImageList(14, 14)
        self._img = {t: il.Add(FV.dot_bitmap(TIER_COLOUR[t])) for t in (C.BLOCK, C.RISK, C.COSMETIC)}
        self._img["waived"] = il.Add(FV.dot_bitmap(wx.Colour(150, 150, 150), ring=True))
        self._img["group"] = -1
        self.lst.AssignImageList(il, wx.IMAGE_LIST_SMALL)
        for i, (c, w) in enumerate([("Finding", 330), ("Where", 230), ("From", 90)]):
            self.lst.InsertColumn(i, c, width=w)
        self.lst.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_select)
        self.lst.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda e: self.on_locate(None))
        self.lst.Bind(wx.EVT_KEY_DOWN, self._list_key)
        self.lst.Bind(wx.EVT_SIZE, self._fit_columns)
        ls = wx.BoxSizer(wx.VERTICAL)
        ls.Add(self.lst, 1, wx.EXPAND)
        left.SetSizer(ls)
        right = wx.Panel(split)
        rs = wx.BoxSizer(wx.VERTICAL)
        self.detail = FV.DetailCard(right)
        self.detail.on_link = self._card_link
        rs.Add(self.detail, 1, wx.EXPAND)
        bar = wx.BoxSizer(wx.HORIZONTAL)
        self.btns = {}
        for key, label, fn, tip in [
                ("locate", "Show on board", self.on_locate, "Zoom to it in the PCB editor.   Enter"),
                ("waive", "Waive...", self._waive_toggle, "Accept it with a reason (kept in the audit record).   W"),
                ("copy", "Copy", self.on_copy, "Copy the finding as text, for a ticket or a message.   Ctrl+C")]:
            b = wx.Button(right, label=label)
            b.Bind(wx.EVT_BUTTON, fn)
            if tip:
                b.SetToolTip(tip)
            self.btns[key] = b
            bar.Add(b, 0, wx.RIGHT, 6)
        rs.Add(bar, 0, wx.TOP, 8)
        right.SetSizer(rs)
        split.SplitVertically(left, right, -440)
        split.SetSashGravity(0.6)
        split.SetMinimumPaneSize(280)
        s.Add(split, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.split = split
        self.SetSizer(s)
        self._row_map = []
        find_id = wx.NewIdRef()
        self.Bind(wx.EVT_MENU, lambda e: self.search.SetFocus(), id=find_id)
        self.SetAcceleratorTable(wx.AcceleratorTable([wx.AcceleratorEntry(wx.ACCEL_CTRL, ord("F"), find_id)]))
        self._empty()

    # --- AI review (Schematic Review tab only)
    def _ai_bar(self):
        self.ai_mode = "pcb" if self.kind == "check" else "schematic"
        outer = wx.BoxSizer(wx.VERTICAL)
        head = wx.BoxSizer(wx.HORIZONTAL)
        title = bold(wx.StaticText(self, label="AI layout review" if self.ai_mode == "pcb" else "AI schematic review"))
        tag = muted(wx.StaticText(self, label="optional"))
        self.ai_summary = muted(wx.StaticText(self, label=""))
        self.ai_toggle = wx.Button(self, label="Show", style=wx.BU_EXACTFIT)
        self.ai_toggle.Bind(wx.EVT_BUTTON, lambda e: self._ai_show(not self.ai_pane.IsShown()))
        head.Add(title, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        head.Add(tag, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 14)
        head.Add(self.ai_summary, 1, wx.ALIGN_CENTER_VERTICAL)
        head.Add(self.ai_toggle, 0, wx.ALIGN_CENTER_VERTICAL)
        outer.Add(head, 0, wx.EXPAND | wx.TOP | wx.BOTTOM, 4)
        pp = self.ai_pane = wx.Panel(self)
        box = wx.BoxSizer(wx.VERTICAL)
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.providers = [p for p in AP.detect() if p.installed]
        names = [p.name for p in self.providers] or ["No AI command-line tool found"]
        self.ai_choice = wx.Choice(pp, choices=names, size=(330, -1))
        cfg = wx.Config("IPC_STE_Assistant")
        last = cfg.Read("ai_provider", "")
        idx = next((i for i, p in enumerate(self.providers) if p.id == last), 0)
        self.ai_choice.SetSelection(idx)
        self.ai_choice.Bind(wx.EVT_CHOICE, lambda e: (self._fill_models(), self._ai_status()))
        self.ai_model = wx.Choice(pp, choices=[], size=(220, -1))
        self.ai_model.SetToolTip("The model the AI tool uses. 'Default' keeps the tool's own setting.")
        self.ai_model.Bind(wx.EVT_CHOICE, self._model_changed)
        self.ai_btn = wx.Button(pp, label="Review with AI")
        self.ai_btn.Bind(wx.EVT_BUTTON, self.on_ai)
        self.ai_preview = wx.Button(pp, label="What is sent?")
        self.ai_preview.Bind(wx.EVT_BUTTON, self.on_ai_preview)
        self.ai_skills = wx.Button(pp, label="Skills...")
        self.ai_skills.SetToolTip("Your own review rules (SKILL.md / Markdown files) for the AI.")
        self.ai_skills.Bind(wx.EVT_BUTTON, self.on_skills)
        self.ai_tools = wx.Button(pp, label="AI tools...")
        self.ai_tools.SetToolTip("Which AI tools were found, and how to add your own (any command-line tool or "
                                 "a local model server).")
        self.ai_tools.Bind(wx.EVT_BUTTON, self.on_ai_tools)
        self.ai_cancel = wx.Button(pp, label="Cancel")
        self.ai_cancel.Bind(wx.EVT_BUTTON, self.on_ai_cancel)
        self.ai_cancel.Hide()
        self.ai_off = wx.CheckBox(pp, label="Never send this project to AI")
        self.ai_off.SetValue(self.frame.req.ai_disabled)
        self.ai_off.Bind(wx.EVT_CHECKBOX, self.on_ai_off)
        for w in (wx.StaticText(pp, label="Tool"), self.ai_choice, wx.StaticText(pp, label="Model"), self.ai_model,
                  self.ai_tools):
            row.Add(w, 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 8)
        row.AddStretchSpacer()
        row.Add(self.ai_off, 0, wx.ALIGN_CENTER_VERTICAL)
        box.Add(row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 6)
        row2 = wx.BoxSizer(wx.HORIZONTAL)
        for w in (self.ai_btn, self.ai_preview, self.ai_skills, self.ai_cancel):
            row2.Add(w, 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 8)
        box.Add(row2, 0, wx.EXPAND | wx.ALL, 6)
        self.ai_info = muted(wx.StaticText(pp, label=""))
        box.Add(self.ai_info, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        self.ai_last_model = ""
        pp.SetSizer(box)
        outer.Add(pp, 0, wx.EXPAND)
        self._fill_models()
        open_ = wx.Config("IPC_STE_Assistant").ReadBool("ai_open_" + self.ai_mode, False)
        self._ai_show(open_, save=False)
        call_after(self._ai_status)
        return outer

    def _ai_show(self, show, save=True):
        self.ai_pane.Show(show)
        self.ai_toggle.SetLabel("Hide" if show else "Show")
        self._ai_summary_update()
        if save:
            cfg = wx.Config("IPC_STE_Assistant")
            cfg.WriteBool("ai_open_" + self.ai_mode, show)
            cfg.Flush()
        self.Layout()

    def _ai_summary_update(self):
        p = self._provider()
        if not self.providers:
            text = "No AI tool found. Show for how to add one."
        elif self.ai_off.GetValue():
            text = "Off for this project."
        else:
            m = self.ai_model.GetStringSelection() if self.ai_model.GetCount() else ""
            text = f"{p.short}" + (f"  \u00b7  {m}" if m and not m.startswith("Default") else "") + \
                (f"  \u00b7  last: {self.ai_last_model}" if getattr(self, "ai_last_model", "") else "")
        self.ai_summary.SetLabel(text)

    def on_ai_tools(self, _evt):
        lines = ["AI TOOLS", "", "The plugin works with any AI tool. It never handles passwords or keys: each tool uses",
                 "the account you signed in with in that tool, or runs a model on this computer.", ""]
        for p in AP.detect(all_tools=True):
            state = "found" if p.installed else ("not running" if isinstance(p, AP.LocalServer) else "not installed")
            files = {"read": "opens PDF datasheets", "text": "gets datasheet text", "none": "no datasheets"}[p.files_mode]
            lines.append(f"  [{state:13}] {p.name}  ({files}; {p.origin})")
            if p.help_url and not p.installed:
                lines.append(f"                  {p.help_url}")
        lines += ["", "PDF text extractor: " + ("found" if AP.text_extract_available() else
                  "not found. Install poppler (pdftotext) so tools without PDF support get datasheet text."),
                  "", "ADD YOUR OWN TOOL", f"  Edit {AP.PERSONAL_TOOLS}",
                  "  Any command-line tool: the plugin runs it with no shell, in an empty temporary folder, and",
                  "  sends the request on stdin or in a file. Any OpenAI-compatible server on localhost works too.",
                  "  Project folders cannot define tools, so a downloaded project can never run a command.", "",
                  "Press 'Open my tools file' to create and open it, then close and open this window again."]
        dlg = TextView(self, "AI tools", "\n".join(lines),
                       [("Open my tools file", lambda: wx.LaunchDefaultApplication(AP.ensure_personal_file()))])
        dlg.ShowModal()
        dlg.Destroy()

    def _fill_models(self):
        p = self._provider()
        models = p.list_models() if p else []
        self._models = models
        self.ai_model.Set([label for label, _ in models] or ["-"])
        cfg = wx.Config("IPC_STE_Assistant")
        saved = cfg.Read("ai_model_" + p.id, "") if p else ""
        idx = next((i for i, (_, v) in enumerate(models) if v == saved), 0)
        self.ai_model.SetSelection(idx)
        self.ai_model.Enable(len(models) > 1)

    def _model_value(self):
        p = self._provider()
        i = self.ai_model.GetSelection()
        m = getattr(self, "_models", [])
        return m[i][1] if p and 0 <= i < len(m) else ""

    def _model_changed(self, _evt):
        p = self._provider()
        if p:
            cfg = wx.Config("IPC_STE_Assistant")
            cfg.Write("ai_model_" + p.id, self._model_value())
            cfg.Flush()

    def _provider(self):
        i = self.ai_choice.GetSelection()
        return self.providers[i] if 0 <= i < len(self.providers) else None

    def _ai_status(self):
        p = self._provider()
        off = self.ai_off.GetValue()
        if not self.providers:
            self.ai_info.SetLabel("No AI tool found. Install any supported command-line tool (Claude Code, Codex CLI, "
                                  "llm, Ollama) or start a local model server, or add your own tool with 'AI tools...'. "
                                  "The AI always uses your own account or your own computer.")
            enable = False
        elif off:
            self.ai_info.SetLabel("AI review is off for this project. Nothing is sent.")
            enable = False
        else:
            self.ai_info.SetLabel("Checking the account...")
            self.ai_btn.Disable()

            def check():
                ok, text, _ = p.account()
                call_after(self._ai_account_done, p, ok, text)
            threading.Thread(target=check, daemon=True).start()
            enable = False
        self.ai_info.Wrap(1000)
        self.ai_pane.Layout()
        self._ai_summary_update()
        self.ai_btn.Enable(enable and not self.running)
        self.ai_preview.Enable(bool(self.providers))
        self.ai_choice.Enable(bool(self.providers) and not off)
        self.Layout()

    def _ai_account_done(self, p, ok, text):
        if p is not self._provider() or self.ai_off.GetValue():
            return
        self._ai_ok, self._ai_text = ok, text
        p = self._provider()
        ds = "" 
        if p is not None:
            n = sum(1 for e in DS.Library(self.frame.paths["dir"]).entries if e.send_to_ai)
            ds = (f"Datasheets: {n} marked for AI ("
                  + ("read-only files" if p.files_mode == "read" else "sent as extracted text") + ")."
                  if p.reads_pdfs else "Datasheets: not shared (this tool takes no files and no PDF text "
                  "extractor was found; install poppler 'pdftotext').") if n else "Datasheets: none (see the Datasheets tab)."
        last = f"  Last model used: {self.ai_last_model}." if getattr(self, "ai_last_model", "") else ""
        self.ai_info.SetLabel(text + "  " + self._skills_line() + "  " + ds + last +
                              "  The AI sees only what 'What is sent?' shows.")
        self.ai_info.Wrap(1000)
        self.ai_pane.Layout()
        self._ai_summary_update()
        self.ai_btn.Enable(ok and not self.running)
        self.Layout()

    def _skills_line(self):
        act = SK.active(self.frame.paths["dir"], self.ai_mode, self.frame.req.ai_skills_off)
        return f"Skills: {', '.join(s.name for s in act)}." if act else "Skills: none."

    def _prior(self):
        """DRC and power findings the layout AI should know about (not repeat)."""
        if self.ai_mode != "pcb":
            return []
        own = [f for f in self.all if f.source != "AI"]
        return own + [f for f in self.frame.power_tab.findings.all if f.source != "AI"]

    def on_skills(self, _evt):
        dlg = SkillsDialog(self, self.frame)
        if dlg.ShowModal() == wx.ID_OK:
            self.frame.req.ai_skills_off = dlg.disabled()
            core.save_req(self.frame.req, self.frame.paths)
        dlg.Destroy()
        for p in (self.frame.sch_tab, self.frame.check_tab):
            p._ai_status()

    def _ds_preview(self):
        p = self._provider()
        if not p or not p.reads_pdfs:
            return "Datasheets: not shared with this tool.\n"
        files = core.ai_datasheets(self.frame.paths)
        if not files:
            return "Datasheets shared: none.\n"
        if p.files_mode == "read":
            work = tempfile.mkdtemp(prefix="kicad-ai-preview-")
            try:
                lines = AP._stage_files(work, files)
            finally:
                shutil.rmtree(work, ignore_errors=True)
            return (f"Datasheets given as read-only PDF files ({sum(f[3] for f in files):.1f} MB), with the pages "
                    "that matter for each exact part:\n" + "\n".join(lines) + "\n")
        text, _n, notes = AP._text_block(files)
        return ("Datasheets sent as text (only the pages chosen for each exact part number and the pins used):\n"
                + "".join(f"  {n}\n" for n in notes) + text + "\n")

    def on_ai_off(self, _evt):
        self.frame.req.ai_disabled = self.ai_off.GetValue()
        core.save_req(self.frame.req, self.frame.paths)
        for p in (self.frame.sch_tab, self.frame.check_tab):
            if hasattr(p, "ai_off"):
                p.ai_off.SetValue(self.frame.req.ai_disabled)
                p._ai_status()

    def on_ai_preview(self, _evt):
        try:
            with wx.BusyCursor():
                _ctx, ins, data, trunc, used = core.ai_request(self.frame.paths, self.ai_mode, self.frame.req,
                                                              self._prior())
        except Exception as e:
            self.frame.info(f"Cannot build the AI request: {e}", wx.ICON_ERROR)
            return
        text = ("This is the complete text the AI tool receives. Nothing else from your computer is sent.\n"
                + ("(The design is large: the summary is cut.)\n" if trunc else "")
                + f"Skills included: {', '.join(used) or 'none'}\n"
                + self._ds_preview()
                + "\n===== INSTRUCTIONS =====\n" + ins + "\n===== DESIGN =====\n" + data)
        TextView(self, "What the AI review sends", text).ShowModal()

    def on_ai(self, _evt):
        p = self._provider()
        if not p or self.running:
            return
        req = self.frame.req
        if not req.ai_consent:
            msg = ("The AI review sends a text summary of this schematic (parts, values, pins and nets) to "
                   f"{p.name.split(' (')[0]}, using your own account. Your files are not sent, and the tool "
                   "cannot open them.\n\nClick 'What is sent?' to read the exact text.\n\nContinue?")
            if wx.MessageBox(msg, "AI review", wx.YES_NO | wx.ICON_QUESTION, self) != wx.YES:
                return
            req.ai_consent = True
            core.save_req(req, self.frame.paths)
        cfg = wx.Config("IPC_STE_Assistant")
        cfg.Write("ai_provider", p.id)
        cfg.Flush()
        self._start_busy("Starting the AI review...")
        self.ai_cancel.Show()
        self.ai_btn.Disable()
        self.Layout()
        paths, model = self.frame.paths, self._model_value()
        mode, req, prior = self.ai_mode, self.frame.req, self._prior()

        def prog(m):
            call_after(self.progress.SetLabel, m)

        def work():
            try:
                rule, found, notes, res = core.run_ai(paths, p, model, prog, mode, req, prior)
                out = ("ok", rule, found, notes, res)
            except AP.Cancelled:
                out = ("cancel", None, None, ["The AI review was cancelled."], None)
            except Exception as e:
                out = ("error", None, None, [str(e)], None)
            call_after(self._ai_finished, out)
        threading.Thread(target=work, daemon=True).start()

    def on_ai_cancel(self, _evt):
        p = self._provider()
        if p:
            p.cancel()

    def _ai_finished(self, out):
        state, rule, found, notes, res = out
        self._stop_busy()
        self.ai_cancel.Hide()
        self.ai_btn.Enable(getattr(self, "_ai_ok", False) and not self.ai_off.GetValue())
        if state != "ok":
            self.progress.SetLabel(notes[0].splitlines()[-1][:160] if notes[0] else "")
            self.frame.info(notes[0], wx.ICON_WARNING if state == "cancel" else wx.ICON_ERROR)
            return
        if self.ai_mode == "pcb":
            base = [f for f in self.all if f.source != "AI"]
            ran = tuple(r for r in self.ran if r != "AI") + ("AI",)
        else:
            base, ran = list(rule), ("SCH", "AI")
        self.all = C.sort_findings(base + list(found))
        self.notes = [n for n in self.notes if not n.startswith("AI ")] + notes
        self.ran = ran
        self.ai_last_model = res.model
        if getattr(self, "_ai_ok", False):
            self._ai_account_done(self._provider(), True, getattr(self, "_ai_text", ""))
        self.progress.SetLabel(f"AI review {time.strftime('%H:%M')}: {len(found)} finding(s), model {res.model}"
                               + (f", {res.files_shared} datasheet(s) read" if res.files_shared else "") + ".")
        self.refresh()
        self.frame.overview.refresh()
        self.frame.info(f"AI {'layout' if self.ai_mode == 'pcb' else 'schematic'} review finished with {res.model}: "
                        f"{len(found)} finding(s) marked AI. Check them against the datasheets.",
                        wx.ICON_INFORMATION)

    def _start_busy(self, text):
        self.running = True
        self.run_btn.Disable()
        self.gauge.Show()
        self._timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, lambda e: self.gauge.Pulse(), self._timer)
        self._timer.Start(80)
        self.progress.SetLabel(text)
        self.Layout()

    def _stop_busy(self):
        self._timer.Stop()
        self.gauge.Hide()
        self.running = False
        self.run_btn.Enable()

    # --- running
    def run(self, on_done=None):
        if self.running:
            return
        self.on_done = on_done
        if self.kind != "sch" and self.save_first.GetValue() and not B.save_board(self.frame.board, self.frame.paths["board"]):
            self.frame.info("The plugin could not save the board. The check uses the last saved file.", wx.ICON_WARNING)
        if self.kind == "power" and not any(g.current_a > 0 for g in self.frame.req.net_groups):
            self.frame.info("No power or ground net has a current yet. Give currents in the Nets tab.", wx.ICON_WARNING)
        self.running = True
        self.run_btn.Disable()
        if self.kind in ("sch", "check"):
            self.ai_btn.Disable()
        self.gauge.Show()
        self.Layout()
        self._timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, lambda e: self.gauge.Pulse(), self._timer)
        self._timer.Start(80)
        self.progress.SetLabel("Starting...")
        req, paths = self.frame.req, self.frame.paths

        def prog(msg):
            call_after(self.progress.SetLabel, msg)

        def work():
            try:
                if self.kind == "check":
                    f, n, ran = core.run_erc_drc(paths, prog)
                    out = (f, n, ran, None)
                elif self.kind == "sch":
                    f, n, _m = core.run_schematic(paths, prog)
                    out = (f, n, ("SCH",), None)
                else:
                    f, sm, n = core.run_power(paths, req, prog)
                    out = (f, n, ("PWR",), sm)
            except Exception as e:     # never leave the UI stuck
                out = ([], [f"The check stopped: {e}"], (), None)
            call_after(self._finished, out)
        threading.Thread(target=work, daemon=True).start()

    def _finished(self, out):
        findings, notes, ran, summaries = out
        self._timer.Stop()
        self.gauge.Hide()
        self.running = False
        self.run_btn.Enable()
        if self.kind in ("sch", "check"):
            ai = [f for f in self.all if f.source == "AI"]
            findings = list(findings) + ai
            ran = tuple(ran) + (("AI",) if ai else ())
            notes = list(notes) + [n for n in self.notes if n.startswith("AI ")]
        self.all, self.notes, self.ran = C.sort_findings(findings), notes, ran
        self.ran_at = time.time()
        self._uuids = None
        if self.kind in ("sch", "check"):
            self.ai_btn.Enable(getattr(self, "_ai_ok", False) and not self.ai_off.GetValue())
        if summaries is not None:
            self.appendix = "NET SUMMARY\n" + PC.summary_table(summaries, self.frame.req.temp_rise_c)
            self.frame.power_tab.show_summary(summaries)
        self.waivers = W.Waivers(self.frame.paths["dir"])
        self.progress.SetLabel(f"Last run {time.strftime('%H:%M')}  \u00b7  {len(self.all)} finding(s)" +
                               (f"  \u00b7  {len(notes)} note(s) in the report" if notes else ""))
        self.refresh()
        self.frame.overview.refresh()
        self.frame.status(self.headline.GetLabel())
        if self.on_done:
            cb, self.on_done = self.on_done, None
            cb()

    # --- list
    def counts(self):
        open_, waived = self.waivers.split(self.all)
        c = {t: sum(1 for f in open_ if f.tier == t) for t in (C.BLOCK, C.RISK, C.COSMETIC)}
        c["Waived"] = len(waived)
        return c

    def _empty(self):
        self.headline.SetLabel("Not run yet")
        self.headline.SetForegroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT))
        what = {"check": ("Run ERC and DRC", "KiCad's own checks on the saved schematic and board, sorted by risk."),
                "power": ("Run the power check", "Give currents to your power nets on the Nets page first."),
                "sch": ("Run the schematic review", "Save the schematic in the Schematic Editor, then run the review.")}
        t, d = what[self.kind]
        self.detail.message("Not run yet", d, action=("run:", t))
        for b in self.btns.values():
            b.Enable(False)
        self.report_btn.Disable()

    def _card_link(self, href):
        if href == "run:":
            self.run()
        elif href.startswith("ref:") and href[4:]:
            if self.frame.board is not None and B.locate_ref(self.frame.board, href[4:]):
                self.frame.status(f"Showing {href[4:]} on the board")
            else:
                self.on_locate(None)

    def _group_changed(self, _evt):
        cfg = wx.Config("IPC_STE_Assistant")
        cfg.WriteInt("group_" + self.kind, self.group.GetSelection())
        cfg.Flush()
        self.refresh()

    def _fit_columns(self, evt):
        evt.Skip()
        w = self.lst.GetClientSize()[0]
        if w > 300:
            self.lst.SetColumnWidth(2, 90)
            self.lst.SetColumnWidth(1, max(140, int((w - 90) * 0.38)))
            self.lst.SetColumnWidth(0, max(160, w - 90 - self.lst.GetColumnWidth(1) - 4))

    def _list_key(self, evt):
        k = evt.GetKeyCode()
        if k in (ord("W"), ord("w")) and not evt.HasAnyModifiers() and self.btns["waive"].IsEnabled():
            self.on_waive(None)
        elif k in (ord("C"), ord("c")) and evt.ControlDown():
            self.on_copy(None)
        else:
            evt.Skip()

    def _source_files(self):
        p = self.frame.paths
        return [p.get("sch", "")] if self.kind == "sch" else [p.get("board", "")] if self.kind == "power" \
            else [p.get("sch", ""), p.get("board", "")]

    def update_stale(self):
        """Show the banner when the saved files are newer than the last run."""
        ran_at = getattr(self, "ran_at", 0)
        newest = max([os.path.getmtime(f) for f in self._source_files() if f and os.path.isfile(f)] or [0])
        stale = bool(self.ran) and ran_at and newest > ran_at + 1
        if stale:
            what = {"sch": "The schematic", "power": "The board"}.get(self.kind, "The schematic or board")
            mins = int((time.time() - ran_at) / 60)
            ago = "just now" if mins < 1 else f"{mins} min ago" if mins < 90 else f"{mins // 60} h ago"
            self.stale_text.SetLabel(f"{what} changed after this run (run {ago}). These results can be out of date.")
        if stale != self.stale.IsShown():
            self.stale.Show(stale)
            self.Layout()

    def _group_key(self, f, mode):
        if mode == "Severity":
            return ({C.BLOCK: 0, C.RISK: 1, C.COSMETIC: 2}.get(f.tier, 3), f.tier)
        if mode == "Part":
            return (0, FV.part_of(f))
        if mode == "Check":
            return (0, FV.SOURCE.get(f.source, f.source))
        return (0, "")

    def refresh(self):
        self.update_stale()
        if not self.ran and not self.all:
            self._empty()
            return
        c = self.counts()
        for key, t in self.toggles.items():
            t.SetLabel(f"{key}  {c[key]}")
        q = self.search.GetValue().strip().lower()
        self.rows = []
        for f in self.all:
            w = self.waivers.get(f)
            if w and not self.toggles["Waived"].GetValue():
                continue
            if not w and not self.toggles[f.tier].GetValue():
                continue
            if q and q not in f"{FV.title_of(f)} {f.type} {f.description} {f.location} {f.action}".lower():
                continue
            self.rows.append(f)
        mode = self.group.GetStringSelection()
        if mode != "None":
            self.rows.sort(key=lambda f: self._group_key(f, mode))
        sel = self._selected()
        self.lst.Freeze()
        self.lst.DeleteAllItems()
        self._row_map = []
        last = None
        bold_font = self.lst.GetFont().Bold()
        head_bg = wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNFACE)
        for f in self.rows:
            if mode != "None":
                g = self._group_key(f, mode)[1]
                if g != last:
                    n = sum(1 for x in self.rows if self._group_key(x, mode)[1] == g)
                    idx = self.lst.InsertItem(self.lst.GetItemCount(), f"{g}   ({n})", -1)
                    self.lst.SetItemFont(idx, bold_font)
                    self.lst.SetItemBackgroundColour(idx, head_bg)
                    self._row_map.append(None)
                    last = g
            w = self.waivers.get(f)
            img = self._img["waived"] if w else self._img.get(f.tier, -1)
            idx = self.lst.InsertItem(self.lst.GetItemCount(), ("  " if mode != "None" else "") + FV.title_of(f), img)
            self.lst.SetItem(idx, 1, FV.where_of(f))
            self.lst.SetItem(idx, 2, FV.SHORT_SOURCE.get(f.source, f.source))
            if w:
                self.lst.SetItemTextColour(idx, wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT))
            self._row_map.append(f)
        self.lst.Thaw()
        if c[C.BLOCK]:
            self.headline.SetLabel(f"Not ready: {c[C.BLOCK]} finding(s) block fabrication")
            self.headline.SetForegroundColour(TIER_COLOUR[C.BLOCK])
        elif c[C.RISK]:
            self.headline.SetLabel(f"No blocking findings. {c[C.RISK]} reliability risk(s) to examine")
            self.headline.SetForegroundColour(TIER_COLOUR[C.RISK])
        else:
            self.headline.SetLabel("No open findings")
            self.headline.SetForegroundColour(GOOD)
        if self.notes and self.kind == "sch":
            used = "; ".join(n.replace("Chip profile used: ", "") for n in self.notes if n.startswith("Chip profile used"))
            self.progress.SetLabel(self.progress.GetLabel().split("  ")[0] + "  Profiles: " + (used or "none")[:120])
        for k in ("locate", "waive", "copy"):
            self.btns[k].Enable(False)
        self.report_btn.Enable(True)
        restored = False
        if sel is not None and sel in self._row_map:
            i = self._row_map.index(sel)
            self.lst.Select(i)
            self.lst.EnsureVisible(i)
            restored = True
        if not restored:
            if not self.all or not any(self._row_map):
                if not any(self.counts()[t] for t in (C.BLOCK, C.RISK, C.COSMETIC)):
                    self.detail.message("All clear", "No open findings." + (" Next: the Fabrication page." if
                                                                          self.kind == "check" else ""), GOOD)
                else:
                    self.detail.message("Nothing to show", "No finding matches the filters or the search.")
            else:
                first = next(i for i, f in enumerate(self._row_map) if f is not None)
                self.lst.Select(first)          # show the most important one straight away
                self.lst.Focus(first)
        self.Layout()
        self._write_report()

    def _selected(self):
        i = self.lst.GetFirstSelected()
        return self._row_map[i] if 0 <= i < len(self._row_map) else None

    def on_select(self, evt):
        f = self._selected()
        if f is None:
            i = self.lst.GetFirstSelected()             # a group header: move to its first finding
            if i >= 0 and i + 1 < len(self._row_map) and self._row_map[i + 1] is not None:
                self.lst.Select(i + 1)
            return
        w = self.waivers.get(f)
        can_locate = any(i.get("ref") for i in f.items) if f.source in ("SCH", "AI") else f.source != "ERC"
        self.btns["locate"].Enable(can_locate)
        self.btns["locate"].SetLabel("Show part on board" if f.source in ("SCH", "AI") else "Show on board")
        self.btns["waive"].Enable(True)
        self.btns["waive"].SetLabel("Remove waiver" if w else "Waive...")
        self.btns["copy"].Enable(True)
        self.detail.show(f, w, self.frame.req.level)
        self.btns["locate"].GetParent().Layout()

    def _waive_toggle(self, _evt):
        f = self._selected()
        if f is None:
            return
        if self.waivers.get(f):
            self.on_unwaive(None)
        else:
            self.on_waive(None)

    def on_copy(self, _evt):
        f = self._selected()
        if not f:
            return
        text = (f"[{f.tier}] {FV.title_of(f)}\nWhere: {FV.where_of(f)}\n{FV.detail_of(f)}\nFix: {f.action}"
                + (f"\nWhy: {f.why}" if f.why else "") + f"\nSource: {FV.SOURCE.get(f.source, f.source)}")
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(text))
            wx.TheClipboard.Close()
            self.frame.status("Finding copied.")

    def on_locate(self, _evt):
        f = self._selected()
        if not f:
            return
        if self.frame.board is None:
            self.frame.info("This window was opened without the PCB editor. Open the board in the PCB editor and "
                            "start the assistant from its toolbar to show items on the board.", wx.ICON_INFORMATION)
            return
        if f.source == "ERC":
            self.frame.info("This finding is in the schematic. Open the Schematic Editor and use "
                            "Inspect > Electrical Rules Checker.", wx.ICON_INFORMATION)
            return
        if f.source in ("SCH", "AI"):
            for it in f.items:
                if it.get("ref") and B.locate_ref(self.frame.board, it["ref"]):
                    self.frame.status(f"Showing {it['ref']} on the board")
                    return
            self.frame.info("This part is not on the board yet. Update the PCB from the schematic.", wx.ICON_INFORMATION)
            return
        if self._uuids is None:
            self._uuids = B.uuid_map(self.frame.board)
        for it in f.items:
            item = self._uuids.get(it.get("uuid", ""))
            if item and B.locate(self.frame.board, item):
                self.frame.status(f"Showing {f.location}")
                return
        pos = (f.items[0].get("pos") if f.items else None) or {}
        self.frame.info(f"The item is not on the open board any more (near X {pos.get('x', '?')}, "
                        f"Y {pos.get('y', '?')} mm). Run the check again.", wx.ICON_WARNING)

    def on_waive(self, _evt):
        f = self._selected()
        if not f:
            return
        if f.tier == C.BLOCK and self.frame.req.level != "Expert":
            if wx.MessageBox("This finding blocks fabrication. Waive it only if you are sure that the "
                             "fabricator and the design can accept it. Continue?", "Respin Zero",
                             wx.YES_NO | wx.ICON_WARNING, self) != wx.YES:
                return
        dlg = wx.TextEntryDialog(self, "Give the reason. It goes into the audit record.", "Waive finding")
        if dlg.ShowModal() == wx.ID_OK:
            if dlg.GetValue().strip():
                self.waivers.add(f, dlg.GetValue())
                self.waivers.save()
                self.refresh()
                self.frame.overview.refresh()
            else:
                self.frame.info("A waiver needs a reason.", wx.ICON_WARNING)
        dlg.Destroy()

    def on_unwaive(self, _evt):
        f = self._selected()
        if f and self.waivers.get(f):
            self.waivers.remove(f)
            self.waivers.save()
            self.refresh()
            self.frame.overview.refresh()

    def _report_text(self):
        open_, waived = self.waivers.split(self.all)
        return C.build_report(self.frame.paths["board"], open_, waived, self.notes, self.frame.req.level,
                              self.ran, self.appendix)

    def _write_report(self):
        try:
            with open(self.report_path, "w", encoding="utf-8") as fh:
                fh.write(self._report_text())
        except OSError:
            pass

    def on_report(self, _evt):
        self._write_report()
        open_file(self.report_path)
        self.frame.status(f"Report: {self.report_path}")
