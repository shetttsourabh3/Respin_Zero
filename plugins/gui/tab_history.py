"""Timeline, SaveVersionDialog, HistoryPanel."""
from .common import *  # noqa: F401,F403
from .. import compare as CMP


class Timeline(wx.ScrolledWindow):
    """Fusion 360 style strip: one node per saved version, oldest left. Milestones are diamonds with a flag,
    the colour is the review state recorded with that version, and a thin line under it plots the number of
    blocking findings. The last dashed node is 'unsaved changes'."""
    STEP, H = 88, 170

    def __init__(self, parent, on_select):
        super().__init__(parent, size=(-1, self.H), style=wx.HSCROLL | wx.BORDER_SIMPLE)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetBackgroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW))
        self.commits, self.pending, self.sel, self.on_select = [], 0, -1, on_select
        self.SetScrollRate(16, 0)
        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_LEFT_DOWN, self.on_click)
        self.Bind(wx.EVT_SIZE, lambda e: (self.Refresh(), e.Skip()))

    def set(self, commits, pending):
        self.commits, self.pending = commits, pending
        n = len(commits) + (1 if pending else 0)
        self.SetVirtualSize((max(n * self.STEP + 120, 200), self.H - 20))
        self.sel = len(commits) - 1 if commits else (0 if pending else -1)
        self.Refresh()
        x = self.STEP * max(0, n - 1)
        self.Scroll(max(0, (x - self.GetClientSize()[0] + 160) // 16), 0)

    def _x(self, i):
        return 60 + i * self.STEP

    def on_click(self, evt):
        x, _y = self.CalcUnscrolledPosition(evt.GetPosition())
        n = len(self.commits) + (1 if self.pending else 0)
        i = int(round((x - 60) / self.STEP))
        if 0 <= i < n:
            self.sel = i
            self.Refresh()
            self.on_select(i)

    def on_paint(self, _evt):
        dc = wx.AutoBufferedPaintDC(self)
        self.DoPrepareDC(dc)
        dc.SetBackground(wx.Brush(self.GetBackgroundColour()))
        dc.Clear()
        gc = wx.GraphicsContext.Create(dc)
        y = 72
        n = len(self.commits) + (1 if self.pending else 0)
        if not n:
            dc.SetTextForeground(wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT))
            dc.DrawText("No versions yet. Save the first version to start the timeline.", 20, y - 8)
            return
        grey = wx.Colour(150, 150, 150)
        gc.SetPen(wx.Pen(grey, 2))
        gc.StrokeLine(self._x(0), y, self._x(n - 1), y)
        col = {"block": wx.Colour(200, 40, 40), "risk": wx.Colour(215, 130, 0), "ok": wx.Colour(30, 150, 70),
               "": wx.Colour(140, 140, 160)}
        # progress line: blocking findings over time
        vals = [c.num("Review-Blocks") for c in self.commits]
        top = max([v for v in vals if v is not None] or [0])
        if top:
            pts = [(self._x(i), y + 70 - 30 * v / top) for i, v in enumerate(vals) if v is not None]
            gc.SetPen(wx.Pen(col["block"], 1, wx.PENSTYLE_SHORT_DASH))
            for a, b in zip(pts, pts[1:]):
                gc.StrokeLine(a[0], a[1], b[0], b[1])
            gc.SetBrush(wx.Brush(col["block"]))
            for px, py in pts:
                gc.DrawEllipse(px - 2, py - 2, 4, 4)
        font = self.GetFont()
        small = wx.Font(font.GetPointSize() - 1, font.GetFamily(), font.GetStyle(), wx.FONTWEIGHT_NORMAL)
        bfont = wx.Font(font.GetPointSize() - 1, font.GetFamily(), font.GetStyle(), wx.FONTWEIGHT_BOLD)
        for i in range(n):
            x = self._x(i)
            if i == len(self.commits):
                gc.SetPen(wx.Pen(grey, 2, wx.PENSTYLE_SHORT_DASH))
                gc.SetBrush(wx.Brush(self.GetBackgroundColour()))
                gc.DrawEllipse(x - 9, y - 9, 18, 18)
                gc.SetFont(small, grey)
                gc.DrawText(f"{self.pending} unsaved", x - 26, y + 16)
                label = None
            else:
                c = self.commits[i]
                gc.SetBrush(wx.Brush(col[c.state]))
                gc.SetPen(wx.Pen(wx.Colour(60, 60, 60) if i == self.sel else col[c.state], 3 if i == self.sel else 1))
                if c.milestone or c.tags:
                    path = gc.CreatePath()
                    path.MoveToPoint(x, y - 12)
                    path.AddLineToPoint(x + 12, y)
                    path.AddLineToPoint(x, y + 12)
                    path.AddLineToPoint(x - 12, y)
                    path.CloseSubpath()
                    gc.DrawPath(path)
                    label = (c.tags[0] if c.tags else "") or c.milestone
                    full = " / ".join(x for x in (", ".join(c.tags), c.milestone) if x)
                    gc.SetFont(bfont, wx.Colour(40, 40, 40))
                    tw = gc.GetTextExtent(label[:14])[0]
                    gc.DrawText(label[:14], x - tw / 2, y - 34)
                    gc.SetPen(wx.Pen(grey, 1))
                    gc.StrokeLine(x, y - 18, x, y - 13)
                    if c.milestone and c.tags:
                        gc.SetFont(small, grey)
                        tw = gc.GetTextExtent(c.milestone[:14])[0]
                        gc.DrawText(c.milestone[:14], x - tw / 2, y - 50)
                else:
                    gc.DrawEllipse(x - 8, y - 8, 16, 16)
                gc.SetFont(small, wx.Colour(90, 90, 90))
                d = c.date[5:10].replace("-", "/")
                tw = gc.GetTextExtent(d)[0]
                gc.DrawText(d, x - tw / 2, y + 16)
        if top:
            gc.SetFont(small, col["block"])
            gc.DrawText(f"blocking findings (max {top})", self._x(0) - 40, y + 76)



class SaveVersionDialog(wx.Dialog):
    def __init__(self, parent, snapshot_text, need_identity, changes):
        super().__init__(parent, title="Save version", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        s = wx.BoxSizer(wx.VERTICAL)
        g = wx.FlexGridSizer(cols=2, vgap=8, hgap=10)
        g.AddGrowableCol(1)
        self.msg = wx.TextCtrl(self, size=(460, 70), style=wx.TE_MULTILINE)
        self.msg.SetHint("What changed? For example: Moved C3 next to U1, fixed I2C pull-ups")
        self.ms = wx.Choice(self, choices=[m or "(none)" for m in VC.MILESTONES])
        self.ms.SetSelection(0)
        self.tag = wx.TextCtrl(self)
        self.tag.SetHint("optional, for example v1.0 or rev-A")
        for label, w in (("What changed", self.msg), ("Milestone", self.ms), ("Version name", self.tag)):
            g.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_TOP | wx.TOP, 4)
            g.Add(w, 1, wx.EXPAND)
        self.name = self.mail = None
        if need_identity:
            self.name, self.mail = wx.TextCtrl(self), wx.TextCtrl(self)
            for label, w in (("Your name", self.name), ("Your e-mail", self.mail)):
                g.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
                g.Add(w, 1, wx.EXPAND)
        s.Add(g, 0, wx.EXPAND | wx.ALL, 12)
        info = muted(wx.StaticText(self, label=f"{len(changes)} changed file(s). Recorded with this version: "
                                                 f"{snapshot_text}"))
        info.Wrap(520)
        s.Add(info, 0, wx.LEFT | wx.RIGHT, 12)
        s.Add(self.CreateButtonSizer(wx.OK | wx.CANCEL), 0, wx.EXPAND | wx.ALL, 12)
        self.SetSizerAndFit(s)
        self.ms.Bind(wx.EVT_CHOICE, self._ms)

    def _ms(self, _evt):
        if not self.msg.GetValue().strip() and self.ms.GetSelection() > 0:
            self.msg.SetValue(VC.MILESTONES[self.ms.GetSelection()])



class HistoryPanel(wx.Panel):
    """Version history with git: save versions, milestones, push/pull, and a timeline of review progress."""

    def __init__(self, parent, frame):
        super().__init__(parent)
        self.frame, self.repo, self.commits, self.changes_, self.busy = frame, None, [], [], False
        s = wx.BoxSizer(wx.VERTICAL)
        intro = muted(wx.StaticText(self, label=(
            "Every saved version is a git commit of the project folder, with the review state at that moment. "
            "Milestones (for example 'Sent to fab') are marked on the timeline. Push and Pull use your own git "
            "sign-in (credential manager or SSH key); the plugin never asks for a password.")))
        intro.Wrap(1000)
        s.Add(intro, 0, wx.ALL, 10)
        bar = wx.BoxSizer(wx.HORIZONTAL)
        self.btns = {}
        for key, label, fn in (("init", "Start version history", self.on_init), ("save", "Save version...", self.on_save),
                               ("mark", "Mark milestone...", self.on_mark), ("push", "Push", self.on_push),
                               ("pull", "Pull", self.on_pull), ("remote", "Remote...", self.on_remote),
                               ("compare", "Compare...", self.on_compare), ("refresh", "Refresh", lambda e: self.load())):
            b = wx.Button(self, label=label)
            b.Bind(wx.EVT_BUTTON, fn)
            self.btns[key] = b
            bar.Add(b, 0, wx.RIGHT, 6)
        s.Add(bar, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        self.state = bold(wx.StaticText(self, label=""))
        s.Add(self.state, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.tl = Timeline(self, self.on_pick)
        s.Add(self.tl, 0, wx.EXPAND | wx.ALL, 10)
        legend = muted(wx.StaticText(self, label=(
            "Red: blocking findings when saved.  Orange: risks only.  Green: clear.  Grey: checks not run.  "
            "Diamond: milestone or version name.  Dashed: unsaved changes.  Click a node for details.")))
        s.Add(legend, 0, wx.LEFT | wx.RIGHT, 10)
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.detail = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY)
        row.Add(self.detail, 1, wx.EXPAND | wx.RIGHT, 8)
        self.files = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for i, (h, w) in enumerate((("Change", 80), ("Area", 100), ("File", 300))):
            self.files.InsertColumn(i, h, width=w)
        row.Add(self.files, 1, wx.EXPAND)
        s.Add(row, 1, wx.EXPAND | wx.ALL, 10)
        bot = wx.BoxSizer(wx.HORIZONTAL)
        self.export_btn = wx.Button(self, label="Export this version (zip)...")
        self.export_btn.SetToolTip("Writes the project files of the selected version to a zip file. Your current "
                                   "files are not changed.")
        self.export_btn.Bind(wx.EVT_BUTTON, self.on_export)
        self.copy_btn = wx.Button(self, label="Copy version ID")
        self.copy_btn.Bind(wx.EVT_BUTTON, self.on_copy)
        bot.Add(self.export_btn, 0, wx.RIGHT, 6)
        bot.Add(self.copy_btn, 0)
        s.Add(bot, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(s)
        self._loaded = False

    # --- review snapshot from the other tabs
    def snapshot(self):
        tr, ran = {}, []
        tot = {C.BLOCK: 0, C.RISK: 0, C.COSMETIC: 0, "Waived": 0}
        for name, panel in (("Schematic", self.frame.sch_tab), ("ERC/DRC", self.frame.check_tab),
                            ("Power", self.frame.power_tab.findings)):
            if panel.ran:
                ran.append(name)
                for k, v in panel.counts().items():
                    tot[k] = tot.get(k, 0) + v
        if ran:
            tr = {"Review-Blocks": tot[C.BLOCK], "Review-Risks": tot[C.RISK], "Review-Cosmetic": tot[C.COSMETIC],
                  "Review-Waived": tot["Waived"], "Review-Checks": ", ".join(ran)}
            text = (f"{tot[C.BLOCK]} blocking, {tot[C.RISK]} risks, {tot[C.COSMETIC]} cosmetic, {tot['Waived']} "
                    f"waived ({', '.join(ran)}).")
        else:
            text = "no review results (no check was run in this window). Run all checks first to record them."
        try:
            from .. import pcbfile
            bp = self.frame.paths.get("board")
            b = None
            if bp and os.path.isfile(bp):
                with open(bp, encoding="utf-8", errors="replace") as f:
                    b = pcbfile.parse(f.read())
            if b is not None:
                bb = b.bbox()
                size = f", {bb[2] - bb[0]:.0f} x {bb[3] - bb[1]:.0f} mm" if bb else ""
                tr["Board"] = f"{len(b.layers)} layers, {len(b.footprints)} parts{size}"
        except Exception:
            pass
        return tr, text

    def write_findings(self):
        """Store the open and waived findings with the version, so versions can be compared later."""
        tabs = {}
        for name, panel in (("Schematic", self.frame.sch_tab), ("ERC/DRC", self.frame.check_tab),
                            ("Power", self.frame.power_tab.findings)):
            if panel.ran:
                tabs[name] = panel.waivers.split(panel.all)
        path = os.path.join(self.frame.paths["dir"], CMP.SNAPSHOT)
        if tabs:
            CMP.write_snapshot(self.frame.paths["dir"], tabs)
        elif os.path.isfile(path):
            os.remove(path)              # an old snapshot would describe a different design
        old = os.path.join(self.frame.paths["dir"], CMP.OLD_SNAPSHOT)
        if os.path.isfile(old):
            os.remove(old)               # moved to the new folder name

    # --- loading
    def load(self):
        if self.busy:
            return
        self.repo = VC.Repo(self.frame.paths["dir"])
        if not self.repo.exe:
            self._show_state("Git is not installed. Install it from https://git-scm.com/, then open this window again.")
            self._enable(False, False)
            self.tl.set([], 0)
            return
        if not self.repo.ok:
            self._show_state("This project has no version history yet. Press 'Start version history'.")
            self._enable(False, True)
            self.tl.set([], 0)
            return
        try:
            self.commits = self.repo.log()
            self.changes_ = self.repo.changes()
        except VC.GitError as e:
            self._show_state(str(e))
            return
        self.tl.set(self.commits, len(self.changes_))
        remote = self.repo.remote()
        ab = self.repo.ahead_behind() if remote else None
        sync = ("not connected to a remote" if not remote else
                ("remote: " + remote + (f"  |  {ab[0]} to push, {ab[1]} to pull" if ab else "  |  not pushed yet")))
        self._show_state(f"Branch {self.repo.branch()}  |  {len(self.commits)} version(s)  |  {sync}")
        self._enable(True, False)
        self.on_pick(self.tl.sel)
        self._loaded = True

    def _show_state(self, text):
        self.state.SetLabel(text)
        self.Layout()

    def _enable(self, repo_ok, can_init):
        self.btns["init"].Show(can_init)
        for k in ("save", "mark", "push", "pull", "remote", "compare"):
            self.btns[k].Enable(repo_ok and not self.busy)
        self.btns["mark"].Enable(repo_ok and bool(self.commits) and not self.busy)
        self.btns["compare"].Enable(repo_ok and bool(self.commits) and not self.busy)
        self.Layout()

    def on_pick(self, i):
        self.files.DeleteAllItems()
        if i < 0:
            self.detail.SetValue("")
            self.export_btn.Disable()
            self.copy_btn.Disable()
            return
        if i >= len(self.commits):
            self.detail.SetValue(f"UNSAVED CHANGES\n\n{len(self.changes_)} file(s) changed since the last version. "
                                 "Save the schematic and board in KiCad, then press 'Save version'.")
            files = self.changes_
            self.export_btn.Disable()
            self.copy_btn.Disable()
        else:
            c = self.commits[i]
            t = c.trailers
            lines = [c.subject, "", f"Saved {c.date[:16].replace('T', ' ')} by {c.author}   (version {c.short})"]
            if c.tags:
                lines.append("Version name: " + ", ".join(c.tags))
            if c.milestone:
                lines.append("Milestone: " + c.milestone)
            if "Review-Blocks" in t:
                lines.append(f"Review when saved: {t.get('Review-Blocks')} blocking, {t.get('Review-Risks')} risks, "
                             f"{t.get('Review-Cosmetic', '?')} cosmetic, {t.get('Review-Waived', '?')} waived "
                             f"({t.get('Review-Checks', '')})")
                if i > 0 and self.commits[i - 1].num("Review-Blocks") is not None:
                    d = c.num("Review-Blocks") - self.commits[i - 1].num("Review-Blocks")
                    lines.append(f"Change from the previous version: {d:+d} blocking")
            else:
                lines.append("Review when saved: not recorded")
            if t.get("Board"):
                lines.append("Board: " + t["Board"])
            body = c.message.split("\n", 1)[1].strip() if "\n" in c.message else ""
            if body:
                lines += ["", body]
            self.detail.SetValue("\n".join(lines))
            try:
                files = self.repo.files(c)
            except VC.GitError:
                files = []
            self.export_btn.Enable()
            self.copy_btn.Enable()
        for st, path in files:
            r = self.files.InsertItem(self.files.GetItemCount(), st)
            self.files.SetItem(r, 1, VC.category(path))
            self.files.SetItem(r, 2, path)

    # --- actions
    def _bg(self, label, fn, done_text):
        self.busy = True
        self._enable(False, False)
        self._show_state(label)

        def work():
            try:
                fn()
                err = None
            except VC.GitError as e:
                err = str(e)
            call_after(self._bg_done, err, done_text)
        threading.Thread(target=work, daemon=True).start()

    def _bg_done(self, err, done_text):
        self.busy = False
        self.load()
        if err:
            self.frame.info(err, wx.ICON_ERROR)
        else:
            self.frame.info(done_text, wx.ICON_INFORMATION)

    def on_init(self, _evt):
        try:
            VC.Repo(self.frame.paths["dir"]).init()
        except VC.GitError as e:
            self.frame.info(str(e), wx.ICON_ERROR)
            return
        self.load()
        self.frame.info("Version history started. A .gitignore for KiCad was added (backups, caches, local "
                        "settings and generated reports stay out). Press 'Save version' for the first version.")

    def on_save(self, _evt):
        if self.frame.board is not None:
            B.save_board(self.frame.board, self.frame.paths["board"])
        self.changes_ = self.repo.changes()
        name, mail = self.repo.identity()
        tr, text = self.snapshot()
        dlg = SaveVersionDialog(self, text, not (name and mail), self.changes_)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return
        msg, ms, tag = dlg.msg.GetValue(), VC.MILESTONES[dlg.ms.GetSelection()], dlg.tag.GetValue().strip()
        ident = (dlg.name.GetValue().strip(), dlg.mail.GetValue().strip()) if dlg.name else None
        dlg.Destroy()
        if ms:
            tr = {"Milestone": ms, **tr}
        try:
            if ident:
                if not all(ident):
                    raise VC.GitError("Enter your name and e-mail. Git records them with each version.")
                self.repo.set_identity(*ident)
            self.write_findings()
            self.repo.save(msg, tr, tag)
        except VC.GitError as e:
            self.frame.info(str(e), wx.ICON_ERROR)
            return
        self.load()
        self.frame.info(f"Version saved{' as ' + tag if tag else ''}. " +
                        ("Press Push to send it to the remote." if self.repo.remote() else ""))

    def on_mark(self, _evt):
        i = self.tl.sel if 0 <= self.tl.sel < len(self.commits) else len(self.commits) - 1
        c = self.commits[i]
        dlg = wx.TextEntryDialog(self, f"Version name for '{c.subject}' ({c.short}), for example v1.0 or rev-A:",
                                 "Mark milestone")
        if dlg.ShowModal() == wx.ID_OK and dlg.GetValue().strip():
            try:
                self.repo.tag(dlg.GetValue().strip(), c.subject, c.hash)
            except VC.GitError as e:
                self.frame.info(str(e), wx.ICON_ERROR)
            self.load()
        dlg.Destroy()

    def on_compare(self, _evt):
        names = [f"{c.short}  {', '.join(c.tags) + '  ' if c.tags else ''}{c.subject[:50]}" for c in self.commits]
        sel = self.tl.sel if 0 <= self.tl.sel < len(self.commits) else len(self.commits) - 1
        dlg = wx.Dialog(self, title="Compare versions")
        s = wx.BoxSizer(wx.VERTICAL)
        g = wx.FlexGridSizer(cols=2, vgap=8, hgap=10)
        a = wx.Choice(dlg, choices=names)
        b = wx.Choice(dlg, choices=names + ["Current files (not saved)"])
        a.SetSelection(max(0, sel - 1))
        b.SetSelection(sel if sel > 0 else len(names))
        for label, w in (("From (older)", a), ("To (newer)", b)):
            g.Add(wx.StaticText(dlg, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            g.Add(w, 0)
        s.Add(g, 0, wx.ALL, 12)
        s.Add(dlg.CreateButtonSizer(wx.OK | wx.CANCEL), 0, wx.EXPAND | wx.ALL, 12)
        dlg.SetSizerAndFit(s)
        ok = dlg.ShowModal() == wx.ID_OK
        ia, ib = a.GetSelection(), b.GetSelection()
        dlg.Destroy()
        if ok:
            self.compare(ia, ib)

    def compare(self, ia, ib):
        ca = self.commits[ia]
        cb = self.commits[ib] if ib < len(self.commits) else None
        try:
            with wx.BusyCursor():
                res = CMP.compare(CMP.snapshot(self.repo, ca.hash), CMP.snapshot(self.repo, cb.hash if cb else None))
                files = self.repo.diff_names(ca.hash, cb.hash if cb else None)
        except VC.GitError as e:
            self.frame.info(str(e), wx.ICON_ERROR)
            return None
        label = lambda c: (c.tags[0] if c.tags else c.short) if c else "current files"   # noqa: E731
        text = CMP.report_text(res, label(ca), label(cb), files)
        self.last_compare = text

        def save():
            with wx.FileDialog(self, "Save comparison", defaultFile=f"compare-{label(ca)}-{label(cb)}.txt".replace(" ", "_"),
                               wildcard="Text (*.txt)|*.txt", style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as fd:
                if fd.ShowModal() == wx.ID_OK:
                    with open(fd.GetPath(), "w", encoding="utf-8") as f:
                        f.write(text)
        dlg = TextView(self, f"Compare {label(ca)} -> {label(cb)}", text, [("Save as...", save)])
        dlg.ShowModal()
        dlg.Destroy()
        return text

    def on_push(self, _evt):
        self._bg("Pushing...", self.repo.push, "Pushed all versions and version names to the remote.")

    def on_pull(self, _evt):
        if self.changes_ and wx.MessageBox("You have unsaved changes. Save a version first so nothing is lost. "
                                           "Pull anyway?", "Pull", wx.YES_NO | wx.ICON_WARNING) != wx.YES:
            return
        self._bg("Pulling...", self.repo.pull, "Pulled the newest versions. Close and open the schematic and board "
                                               "in KiCad (File > Revert) to see them.")

    def on_remote(self, _evt):
        dlg = wx.TextEntryDialog(self, "Address of the remote repository (GitHub, GitLab, Gitea, a company server...), "
                                       "for example https://github.com/you/board.git or git@github.com:you/board.git.\n"
                                       "Create an empty repository there first. Sign-in is done by git, not by this "
                                       "plugin.", "Remote", self.repo.remote())
        if dlg.ShowModal() == wx.ID_OK and dlg.GetValue().strip():
            url = dlg.GetValue().strip()
            if re.search(r"//[^/@]+:[^/@]+@", url):
                self.frame.info("Do not put a password or token in the address. Use git's credential manager or an "
                                "SSH key.", wx.ICON_ERROR)
            else:
                try:
                    self.repo.set_remote(url)
                except VC.GitError as e:
                    self.frame.info(str(e), wx.ICON_ERROR)
                self.load()
        dlg.Destroy()

    def on_export(self, _evt):
        c = self.commits[self.tl.sel]
        name = f"{os.path.splitext(os.path.basename(self.frame.paths['board'] or 'project'))[0]}-" \
               f"{(c.tags[0] if c.tags else c.short)}.zip"
        with wx.FileDialog(self, "Export version", defaultFile=name, wildcard="Zip (*.zip)|*.zip",
                           style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as fd:
            if fd.ShowModal() != wx.ID_OK:
                return
            try:
                self.repo.export(c, fd.GetPath())
                self.frame.info(f"Exported version {c.short} to {fd.GetPath()}. Unzip it to a new folder to open it "
                                "in KiCad.")
            except VC.GitError as e:
                self.frame.info(str(e), wx.ICON_ERROR)

    def on_copy(self, _evt):
        c = self.commits[self.tl.sel]
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(c.hash))
            wx.TheClipboard.Close()
