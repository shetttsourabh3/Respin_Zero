"""Card, OverviewPanel."""
from .common import *  # noqa: F401,F403


class Card(wx.Panel):
    def __init__(self, parent, title, bmp, tab_index, frame):
        super().__init__(parent, style=wx.BORDER_THEME)
        self.frame, self.tab_index = frame, tab_index
        s = wx.BoxSizer(wx.VERTICAL)
        head = wx.BoxSizer(wx.HORIZONTAL)
        head.Add(wx.StaticBitmap(self, bitmap=bmp), 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 8)
        tt = bold(wx.StaticText(self, label=title), 1)
        w, h = tt.GetTextExtent(title)
        tt.SetMinSize((w + 8, h + 2))
        head.Add(tt, 0, wx.ALIGN_CENTER_VERTICAL)
        s.Add(head, 0, wx.ALL, 12)
        self.state = bold(wx.StaticText(self, label=""))
        s.Add(self.state, 0, wx.LEFT | wx.RIGHT, 12)
        self.detail = muted(wx.StaticText(self, label=""))
        s.Add(self.detail, 0, wx.EXPAND | wx.ALL, 12)
        self.btn = wx.Button(self, label="Open")
        self.btn.Bind(wx.EVT_BUTTON, lambda e: frame.nb.SetSelection(tab_index))
        s.Add(self.btn, 0, wx.LEFT | wx.BOTTOM, 12)
        self.SetSizer(s)

    def set(self, state, colour, detail):
        self.state.SetLabel(state)
        self.state.SetForegroundColour(colour)
        self.detail.SetLabel(detail)
        self.detail.Wrap(max(240, self.GetSize()[0] - 30))
        self.Layout()



class OverviewPanel(scrolled.ScrolledPanel):
    def __init__(self, parent, frame):
        super().__init__(parent)
        self.frame = frame
        s = wx.BoxSizer(wx.VERTICAL)
        self.profile = muted(wx.StaticText(self, label=""))
        s.Add(self.profile, 0, wx.ALL, 12)
        self.next = bold(wx.StaticText(self, label=""), 1)
        self.next.SetForegroundColour(ACCENT)
        s.Add(self.next, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        grid = wx.GridSizer(4, 2, 12, 12)  # cards keep their natural height
        self.cards = {
            "rules": Card(self, "1  Design rules", icon("icon.png", 24), 1, frame),
            "nets": Card(self, "2  Nets", icon("icon_nets.png", 24), 2, frame),
            "sch": Card(self, "3  Schematic review", icon("icon_sch.png", 24), 4, frame),
            "check": Card(self, "4  ERC and DRC", icon("icon_check.png", 24), 5, frame),
            "power": Card(self, "5  Power and thermal", icon("icon_power.png", 24), 6, frame),
            "fab": Card(self, "6  Fabrication", icon("icon_fab.png", 24), 8, frame),
            "hist": Card(self, "7  Version history", icon("icon_hist.png", 24), 9, frame),
        }
        for c in self.cards.values():
            grid.Add(c, 1, wx.EXPAND)
        s.Add(grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        bar = wx.BoxSizer(wx.HORIZONTAL)
        self.run_all = primary_button(self, "Run all checks")
        self.run_all.SetToolTip("Run the schematic review, ERC and DRC, and the power and thermal check.")
        self.run_all.Bind(wx.EVT_BUTTON, self.on_run_all)
        doc = wx.Button(self, label="Help")
        doc.Bind(wx.EVT_BUTTON, lambda e: open_file(os.path.join(HERE, "README.md")))
        short = wx.Button(self, label="Shortcut for schematic work...")
        short.SetToolTip("KiCad 10 shows plugins only in the PCB editor. This makes a desktop launcher that opens "
                         "this window for this project without the PCB editor.")
        short.Bind(wx.EVT_BUTTON, self.on_shortcut)
        self.run_all.Hide()                     # the header has 'Run all checks' (Ctrl+R)
        bar.Add(self.run_all, 0, wx.RIGHT, 8)
        rep = wx.Button(self, label="Report a problem...")
        rep.SetToolTip("Makes a text with versions, tools found and the log, for a bug report. No design data.")
        rep.Bind(wx.EVT_BUTTON, self.on_report)
        bar.Add(doc, 0, wx.RIGHT, 8)
        bar.Add(short, 0, wx.RIGHT, 8)
        bar.Add(rep, 0)
        s.Add(bar, 0, wx.ALL, 12)
        self.SetSizer(s)
        self.SetupScrolling(scroll_x=False)
        self.Bind(wx.EVT_SIZE, lambda e: (e.Skip(), call_after(self.refresh)))

    def _fab_card(self):
        card, grey = self.cards["fab"], wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT)
        fab_dir = os.path.join(self.frame.paths["dir"], "fab")
        made = sorted((d for d in os.listdir(fab_dir) if os.path.isdir(os.path.join(fab_dir, d))),
                      key=lambda d: os.path.getmtime(os.path.join(fab_dir, d))) if os.path.isdir(fab_dir) else []
        if made:
            card.set(f"Last files: {made[-1]}", GOOD, f"{len(made)} fabrication set(s) in the fab folder. "
                     "Make new files after every change.")
        else:
            card.set("No files yet", grey, "Final checks, then Gerbers, drill, BOM and pick-and-place files.")

    def _hist_card(self):
        now = time.time()
        if now - getattr(self, "_hist_t", 0) < 5:
            return
        self._hist_t = now
        card, grey = self.cards["hist"], wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT)
        try:
            repo = VC.Repo(self.frame.paths["dir"])
            if not repo.exe:
                card.set("Git not installed", grey, "Install git to keep versions and track progress.")
                return
            if not repo.ok:
                card.set("Not started", grey, "Start version history to save versions and milestones.")
                return
            log, ch = repo.log(limit=200), repo.changes()
            ms = next((c for c in reversed(log) if c.tags or c.milestone), None)
            text = f"{len(log)} version(s)." + (f" Last milestone: {(ms.tags or [ms.milestone])[0]}." if ms else "")
            card.set(f"{len(ch)} unsaved change(s)" if ch else "Up to date",
                     TIER_COLOUR[C.RISK] if ch else GOOD, text)
        except VC.GitError as e:
            card.set("Git error", TIER_COLOUR[C.BLOCK], str(e)[:120])

    def on_report(self, _evt):
        from .. import diag
        with wx.BusyCursor():
            text = diag.report(self.frame.paths["dir"], self.frame.nb.GetPageText(self.frame.nb.GetSelection()))

        def copy():
            if wx.TheClipboard.Open():
                wx.TheClipboard.SetData(wx.TextDataObject(text))
                wx.TheClipboard.Close()
                self.frame.info("Problem report copied. Paste it into your bug report or e-mail.")

        def save():
            with wx.FileDialog(self, "Save problem report", defaultFile="respin-zero-problem.txt",
                               wildcard="Text (*.txt)|*.txt", style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as fd:
                if fd.ShowModal() == wx.ID_OK:
                    with open(fd.GetPath(), "w", encoding="utf-8") as f:
                        f.write(text)
        dlg = TextView(self, "Report a problem", text, [("Copy", copy), ("Save as...", save),
                                                         ("Open log folder", lambda: open_file(diag.LOG_DIR))])
        dlg.ShowModal()
        dlg.Destroy()

    def on_shortcut(self, _evt):
        from .. import standalone
        pro = os.path.splitext(self.frame.paths["board"])[0] + ".kicad_pro"
        try:
            path = standalone.create_shortcut(pro)
        except OSError as e:
            self.frame.info(f"Cannot make the shortcut: {e}", wx.ICON_ERROR)
            return
        self.frame.info(f"Shortcut made: {path}. Double-click it to open this window while you work in the "
                        "Schematic Editor (Schematic Review, Datasheets, AI review, ERC/DRC and History all work).")

    def on_run_all(self, _evt):
        f = self.frame
        self.run_all.Disable()
        f.status("Running the schematic review...")
        f.sch_tab.run(on_done=lambda: (f.status("Running ERC and DRC..."), f.check_tab.run(
            on_done=lambda: (f.status("Running the power and thermal check..."),
                             f.power_tab.findings.run(on_done=self._all_done)))))

    def _all_done(self):
        self.run_all.Enable()
        self.refresh()
        self.frame.info("All checks finished. " + self.next.GetLabel(), wx.ICON_INFORMATION)

    def refresh(self):
        f = self.frame
        if not f or not hasattr(f, "power_tab"):
            return
        r = f.req
        self.profile.SetLabel(f"IPC Class {r.ipc_class}{' medical' if r.medical else ''}  |  {r.layers} layers, "
                              f"{r.board_thickness_mm:g} mm  |  {r.manufacturer or 'no fabricator selected'}  |  "
                              f"level {r.level}")
        grey = wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT)
        nxt = None

        if core.rules_applied(f.paths):
            self.cards["rules"].set("Applied", GOOD, f"{os.path.basename(f.paths['dru'])} updated "
                                    f"{core.file_time(f.paths['dru'])}. Apply again after you change an answer.")
        else:
            self.cards["rules"].set("Not applied", TIER_COLOUR[C.RISK], "Answer the questions and apply the rules.")
            nxt = nxt or "Next: set up the design rules."

        groups = r.net_groups
        missing = [g.net for g in groups if g.group in ("Power", "Ground") and g.current_a <= 0]
        if not groups:
            self.cards["nets"].set("Not set", TIER_COLOUR[C.RISK], "Give currents and voltages to your power, "
                                   "ground and high-voltage nets.")
            nxt = nxt or "Next: give currents to your power nets."
        elif missing:
            self.cards["nets"].set(f"{len(missing)} without current", TIER_COLOUR[C.RISK], ", ".join(missing[:6]))
            nxt = nxt or "Next: give a current to every power and ground net."
        else:
            n_hv = sum(1 for g in groups if g.group == "High voltage")
            self.cards["nets"].set(f"{len(groups)} nets set", GOOD, f"{len(groups) - n_hv} power or ground, {n_hv} high voltage.")

        for key, panel in (("sch", f.sch_tab), ("check", f.check_tab), ("power", f.power_tab.findings)):
            if not panel.ran:
                t = core.file_time(panel.report_path)
                self.cards[key].set("Not run in this session", grey,
                                    f"Last report {t}." if t else "Run the check to see the findings.")
                nxt = nxt or {"sch": "Next: run the schematic review.", "check": "Next: run ERC and DRC.",
                              "power": "Next: run the power and thermal check."}[key]
                continue
            c = panel.counts()
            if c[C.BLOCK]:
                self.cards[key].set(f"{c[C.BLOCK]} blocking", TIER_COLOUR[C.BLOCK],
                                    f"{c[C.RISK]} risk{'' if c[C.RISK] == 1 else 's'}, {c[C.COSMETIC]} cosmetic, {c['Waived']} waived.")
                nxt = nxt or f"Next: fix the blocking findings in {dict(sch='Schematic review', check='ERC and DRC', power='Power and thermal')[key]}."
            elif c[C.RISK]:
                self.cards[key].set(f"{c[C.RISK]} risk{'' if c[C.RISK] == 1 else 's'}", TIER_COLOUR[C.RISK],
                                    f"No blocking findings. {c[C.COSMETIC]} cosmetic, {c['Waived']} waived.")
            else:
                self.cards[key].set("Clear", GOOD, f"No open findings. {c['Waived']} waived.")
        self._hist_card()
        self._fab_card()
        self.next.SetLabel(nxt or "All steps done. Open the Fabrication tab for the final checks and the fabrication files.")
        f.set_status_pill()
        self.Layout()
