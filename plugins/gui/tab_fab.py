"""FabPanel: final checks, then the fabrication files, saved as a 'Sent to fab' version."""
from .common import *  # noqa: F401,F403
from .. import fab as FB

LEVEL_TEXT = {FB.OK: "OK", FB.WARN: "Check", FB.FAIL: "Blocks"}


class FabPanel(wx.Panel):
    def __init__(self, parent, frame):
        super().__init__(parent)
        self.frame, self.busy, self.checks, self.design, self.files = frame, False, [], None, []
        self.presets = FB.load_presets()
        s = wx.BoxSizer(wx.VERTICAL)
        intro = muted(wx.StaticText(self, label=(
            "The last step. The final checks make sure the files come from a checked, saved design. Then the "
            "plugin makes the Gerbers, drill files, BOM and pick-and-place files in your fabricator's format, "
            "with a fab note, and saves them as a 'Sent to fab' version in History.")))
        intro.Wrap(1000)
        s.Add(intro, 0, wx.ALL, 10)

        g = wx.FlexGridSizer(cols=4, vgap=8, hgap=10)
        self.preset = wx.Choice(self, choices=[p["name"] for p in self.presets], size=(340, -1))
        self.label = wx.TextCtrl(self, size=(160, -1))
        self.label.SetHint("for example rev-A")
        self.label.SetToolTip("Version name. Used in the file names, the fab note and History.")
        g.Add(wx.StaticText(self, label="Output format"), 0, wx.ALIGN_CENTER_VERTICAL)
        g.Add(self.preset, 0)
        g.Add(wx.StaticText(self, label="Version name"), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 20)
        g.Add(self.label, 0)
        s.Add(g, 0, wx.LEFT | wx.RIGHT, 10)
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.opt = {}
        for key, label, val, tip in (
                ("bom", "BOM", True, "Bill of materials in the fabricator's columns (from the schematic)."),
                ("cpl", "Pick and place", True, "Part positions for assembly."),
                ("paste", "Paste layers", True, "Solder paste layers, needed for assembly and stencils."),
                ("step", "3D model (STEP)", False, "For enclosure design. Can take a minute."),
                ("history", "Save as a version in History", True, "Saves the design and these files as a "
                                                                   "'Sent to fab' version with the version name.")):
            cb = wx.CheckBox(self, label=label)
            cb.SetValue(val)
            cb.SetToolTip(tip)
            self.opt[key] = cb
            row.Add(cb, 0, wx.RIGHT, 16)
        s.Add(row, 0, wx.ALL, 10)

        head = wx.BoxSizer(wx.HORIZONTAL)
        self.headline = bold(wx.StaticText(self, label="Final checks"), 1)
        head.Add(self.headline, 1, wx.ALIGN_CENTER_VERTICAL)
        self.run_btn = wx.Button(self, label="Run all checks")
        self.run_btn.Bind(wx.EVT_BUTTON, self.on_run_all)
        self.refresh_btn = wx.Button(self, label="Check again")
        self.refresh_btn.Bind(wx.EVT_BUTTON, lambda e: self.load())
        head.Add(self.run_btn, 0, wx.RIGHT, 6)
        head.Add(self.refresh_btn, 0)
        s.Add(head, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        self.lst = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for i, (h, w) in enumerate((("Status", 80), ("Check", 380), ("What to do", 560))):
            self.lst.InsertColumn(i, h, width=w)
        s.Add(self.lst, 1, wx.EXPAND | wx.ALL, 10)

        bot = wx.BoxSizer(wx.HORIZONTAL)
        self.export_btn = primary_button(self, "Make fabrication files")
        self.export_btn.Bind(wx.EVT_BUTTON, self.on_export)
        self.open_btn = wx.Button(self, label="Open output folder")
        self.open_btn.Bind(wx.EVT_BUTTON, lambda e: self.files and open_file(os.path.dirname(self.files[0])))
        self.open_btn.Disable()
        self.gauge = wx.Gauge(self, range=100, size=(140, 12))
        self.gauge.Hide()
        self.progress = muted(wx.StaticText(self, label=""))
        bot.Add(self.export_btn, 0, wx.RIGHT, 8)
        bot.Add(self.open_btn, 0, wx.RIGHT, 12)
        bot.Add(self.gauge, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        bot.Add(self.progress, 1, wx.ALIGN_CENTER_VERTICAL)
        s.Add(bot, 0, wx.EXPAND | wx.ALL, 10)
        self.SetSizer(s)
        self._timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, lambda e: self.gauge.Pulse(), self._timer)

    # --- state
    def profile(self):
        return self.frame.profiles.get(self.frame.req.manufacturer)

    def review_state(self):
        st = {}
        f = self.frame
        for key, panel in (("sch", f.sch_tab), ("check", f.check_tab), ("power", f.power_tab.findings)):
            st[key] = ({"counts": panel.counts(), "ran_at": getattr(panel, "ran_at", 0), "ran": panel.ran}
                       if panel.ran else None)
        return st

    def _repo(self):
        r = VC.Repo(self.frame.paths["dir"])
        return r if r.ok else None

    def _suggest_label(self, repo):
        if self.label.GetValue().strip():
            return
        tags = set()
        if repo:
            try:
                for c in repo.log():
                    tags |= set(c.tags)
            except VC.GitError:
                pass
        for ch in "ABCDEFGHJKLMNPRSTUVWXYZ":
            if f"rev-{ch}" not in tags:
                self.label.SetValue(f"rev-{ch}")
                return

    def load(self):
        if self.busy:
            return
        prof = self.profile()
        pid = prof.get("id", "") if prof else ""
        want = FB.preset_for(pid, self.presets)
        if self.preset.GetSelection() < 0 or not getattr(self, "_user_preset", False):
            self.preset.SetSelection(self.presets.index(want))
        self.preset.Bind(wx.EVT_CHOICE, lambda e: setattr(self, "_user_preset", True))
        repo = self._repo()
        self.opt["history"].Enable(bool(repo))
        if not repo:
            self.opt["history"].SetValue(False)
            self.opt["history"].SetToolTip("Start version history in the History tab to save fab versions.")
        self._suggest_label(repo)
        self.busy = True
        self._start("Checking...")
        paths, req, state = self.frame.paths, self.frame.req, self.review_state()

        def work():
            try:
                design = core.load_design(paths)
            except Exception:
                design = None
            try:
                unsaved = len(repo.changes()) if repo else None
            except VC.GitError:
                unsaved = None
            checks = FB.preflight(paths, req, state, prof, design, unsaved)
            if design is None and os.path.isfile(paths.get("sch", "")):
                checks.append(FB.Check(FB.WARN, "Cannot read the schematic", "The BOM cannot be made. Save the "
                                       "schematic, and make sure kicad-cli works (ERC / DRC tab)."))
            call_after(self._loaded, checks, design)
        threading.Thread(target=work, daemon=True).start()

    def _loaded(self, checks, design):
        self.busy = False
        self._stop()
        self.checks, self.design = checks, design
        self.lst.DeleteAllItems()
        col = {FB.OK: GOOD, FB.WARN: TIER_COLOUR[C.RISK], FB.FAIL: TIER_COLOUR[C.BLOCK]}
        order = {FB.FAIL: 0, FB.WARN: 1, FB.OK: 2}
        for c in sorted(checks, key=lambda c: order[c.level]):
            i = self.lst.InsertItem(self.lst.GetItemCount(), LEVEL_TEXT[c.level])
            self.lst.SetItem(i, 1, c.title)
            self.lst.SetItem(i, 2, c.detail)
            self.lst.SetItemTextColour(i, col[c.level])
        nb = len(FB.blocking(checks))
        self.headline.SetLabel(f"Final checks: {nb} blocking" if nb else "Final checks: ready to make the files")
        self.headline.SetForegroundColour(TIER_COLOUR[C.BLOCK] if nb else GOOD)
        self.progress.SetLabel("")
        self.Layout()

    def on_run_all(self, _evt):
        self.frame.overview.run_all.Disable()
        f = self.frame
        self.run_btn.Disable()
        f.sch_tab.run(on_done=lambda: f.check_tab.run(on_done=lambda: f.power_tab.findings.run(
            on_done=lambda: (self.run_btn.Enable(), f.overview.run_all.Enable(), f.overview.refresh(), self.load()))))

    # --- export
    def _start(self, text):
        self.gauge.Show()
        self._timer.Start(80)
        self.progress.SetLabel(text)
        for b in (self.export_btn, self.run_btn, self.refresh_btn):
            b.Disable()
        self.Layout()

    def _stop(self):
        self._timer.Stop()
        self.gauge.Hide()
        for b in (self.export_btn, self.run_btn, self.refresh_btn):
            b.Enable()
        self.Layout()

    def on_export(self, _evt):
        if self.busy:
            return
        label = self.label.GetValue().strip()
        if not label or not re.match(r"^[A-Za-z0-9._-]+$", label):
            self.frame.info("Give a version name with letters, digits, '.', '-' or '_' (for example rev-A).",
                            wx.ICON_ERROR)
            return
        reason = ""
        blocks = FB.blocking(self.checks)
        if not self.checks:
            self.frame.info("Run the final checks first ('Check again').", wx.ICON_WARNING)
            return
        if blocks:
            dlg = wx.TextEntryDialog(
                self, f"{len(blocks)} final check(s) block fabrication:\n\n" +
                "\n".join(f"  - {c.title}" for c in blocks[:8]) +
                "\n\nFix them first. To make the files anyway, give the reason. It is written in the fab note "
                "and in History.", "Blocking checks")
            ok = dlg.ShowModal() == wx.ID_OK
            reason = dlg.GetValue().strip()
            dlg.Destroy()
            if not ok or not reason:
                return
        if self.frame.board is not None:
            B.save_board(self.frame.board, self.frame.paths["board"])
        preset = self.presets[self.preset.GetSelection()]
        out = os.path.join(self.frame.paths["dir"], "fab", label)
        opts = {k: cb.GetValue() for k, cb in self.opt.items()}
        repo = self._repo() if opts["history"] else None
        snapshot = self.frame.hist_tab.snapshot()[0] if repo else {}
        if repo:
            self.frame.hist_tab.write_findings()
        paths, req, prof, design, checks = self.frame.paths, self.frame.req, self.profile(), self.design, self.checks
        self.busy = True
        self._start("Making files...")

        def work():
            err, files, notes, saved = None, [], [], ""
            try:
                files, notes = FB.export(paths, req, preset, out, opts, design,
                                         lambda m: call_after(self.progress.SetLabel, m), prof, checks, reason, label)
                if repo:
                    tr = {"Milestone": "Sent to fab", **snapshot}
                    msg = f"Sent to fab: {label} ({preset['name']})" + (f"\n\nBlocking checks waived: {reason}"
                                                                         if reason else "")
                    repo.save(msg, tr, tag=label)
                    saved = label
            except (FB.FabError, VC.GitError, OSError) as e:
                err = str(e)
            call_after(self._exported, err, files, notes, saved, out)
        threading.Thread(target=work, daemon=True).start()

    def _exported(self, err, files, notes, saved, out):
        self.busy = False
        self._stop()
        if err:
            self.progress.SetLabel("Failed.")
            self.frame.info(err, wx.ICON_ERROR)
            if files:
                self.files = files
                self.open_btn.Enable()
            return
        self.files = files
        self.open_btn.Enable()
        self.progress.SetLabel(f"{len(files)} file(s) in {os.path.relpath(out, self.frame.paths['dir'])}.  "
                               + "  ".join(notes[:3]))
        self.frame.hist_tab.load()
        self.frame.overview.refresh()
        self.frame.info(f"Fabrication files made in fab/{os.path.basename(out)}." +
                        (f" Saved as version '{saved}' (Sent to fab) in History." if saved else "") +
                        " Read FAB_NOTE.txt before you upload.", wx.ICON_INFORMATION)
