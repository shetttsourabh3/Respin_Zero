"""ProductionPanel: one click for the Gerber zip, position file and BOM, without the release steps."""
from .common import *  # noqa: F401,F403
from .. import fab as FB


class ProductionPanel(wx.Panel):
    def __init__(self, parent, frame):
        super().__init__(parent)
        self.frame, self.busy, self.files = frame, False, []
        self.presets = FB.load_presets()
        cfg = wx.Config("IPC_STE_Assistant")
        s = wx.BoxSizer(wx.VERTICAL)
        intro = muted(wx.StaticText(self, label=(
            "Make the production files in one step, at any time: Gerbers and drill files in one zip, the "
            "position (pick-and-place) file and the BOM. Nothing is checked or saved in History. To release "
            "a board to the fabricator with the final checks and a version, use the Fabrication tab.")))
        intro.Wrap(1000)
        s.Add(intro, 0, wx.ALL, 10)

        g = wx.FlexGridSizer(cols=3, vgap=8, hgap=10)
        g.AddGrowableCol(1)
        self.preset = wx.Choice(self, choices=[p["name"] for p in self.presets])
        self.folder = wx.TextCtrl(self, value=cfg.Read("production_folder", "production"))
        self.folder.SetToolTip("Folder for the files. A relative name is inside the project folder.")
        browse = wx.Button(self, label="Browse...")
        browse.Bind(wx.EVT_BUTTON, self.on_browse)
        g.Add(wx.StaticText(self, label="Format"), 0, wx.ALIGN_CENTER_VERTICAL)
        g.Add(self.preset, 0, wx.EXPAND)
        g.AddSpacer(0)
        g.Add(wx.StaticText(self, label="Output folder"), 0, wx.ALIGN_CENTER_VERTICAL)
        g.Add(self.folder, 1, wx.EXPAND)
        g.Add(browse, 0)
        s.Add(g, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        row = wx.BoxSizer(wx.HORIZONTAL)
        self.opt = {}
        for key, label, tip in (
                ("gerber", "Gerbers + drill (zip)", "All copper, mask, silkscreen, paste and outline layers, with the "
                                                    "drill files, in one zip."),
                ("cpl", "Position file", "Pick-and-place file, both sides, without DNP parts."),
                ("bom", "BOM", "Bill of materials from the schematic, grouped by value, footprint and part number."),
                ("step", "3D model (STEP)", "For enclosure design. Can take a minute.")):
            cb = wx.CheckBox(self, label=label)
            cb.SetValue(cfg.ReadBool("production_" + key, key != "step"))
            cb.SetToolTip(tip)
            if key == "gerber":
                cb.SetValue(True)
                cb.Disable()                      # always made
            self.opt[key] = cb
            row.Add(cb, 0, wx.RIGHT, 16)
        s.Add(row, 0, wx.ALL, 10)

        bar = wx.BoxSizer(wx.HORIZONTAL)
        self.go = primary_button(self, "Generate production files")
        self.go.Bind(wx.EVT_BUTTON, self.on_generate)
        self.open_btn = wx.Button(self, label="Open folder")
        self.open_btn.Bind(wx.EVT_BUTTON, lambda e: open_file(self.out_dir()) if os.path.isdir(self.out_dir()) else None)
        self.gauge = wx.Gauge(self, range=100, size=(140, 12))
        self.gauge.Hide()
        self.progress = muted(wx.StaticText(self, label=""))
        bar.Add(self.go, 0, wx.RIGHT, 8)
        bar.Add(self.open_btn, 0, wx.RIGHT, 12)
        bar.Add(self.gauge, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        bar.Add(self.progress, 1, wx.ALIGN_CENTER_VERTICAL)
        s.Add(bar, 0, wx.EXPAND | wx.ALL, 10)

        self.warn = wx.StaticText(self, label="")
        self.warn.SetForegroundColour(TIER_COLOUR[C.RISK])
        s.Add(self.warn, 0, wx.LEFT | wx.RIGHT, 10)
        self.lst = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for i, (h, w) in enumerate((("File", 420), ("Size", 90), ("Made", 160))):
            self.lst.InsertColumn(i, h, width=w)
        self.lst.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_open_file)
        s.Add(self.lst, 1, wx.EXPAND | wx.ALL, 10)
        tip = muted(wx.StaticText(self, label="Double-click a file to open it."))
        s.Add(tip, 0, wx.LEFT | wx.BOTTOM, 10)
        self.SetSizer(s)
        self._timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, lambda e: self.gauge.Pulse(), self._timer)

    # --- helpers
    def out_dir(self):
        f = self.folder.GetValue().strip() or "production"
        return f if os.path.isabs(f) else os.path.join(self.frame.paths["dir"], f)

    def on_browse(self, _evt):
        with wx.DirDialog(self, "Output folder", self.out_dir() if os.path.isdir(self.out_dir())
                          else self.frame.paths["dir"]) as dd:
            if dd.ShowModal() == wx.ID_OK:
                p = dd.GetPath()
                try:
                    rel = os.path.relpath(p, self.frame.paths["dir"])
                    p = rel if not rel.startswith("..") else p
                except ValueError:                  # other drive on Windows
                    pass
                self.folder.SetValue(p)

    def load(self):
        prof = self.frame.profiles.get(self.frame.req.manufacturer)
        if self.preset.GetSelection() < 0:
            want = FB.preset_for(prof.get("id", "") if prof else "", self.presets)
            self.preset.SetSelection(self.presets.index(want))
        self._show_existing()
        self._warn()

    def _warn(self):
        """A reminder, not a gate: say if the checks are missing, old or blocking."""
        f = self.frame
        p = f.check_tab
        newest = max(FB._mtime(f.paths.get("board", "")), FB._mtime(f.paths.get("sch", "")))
        if not p.ran:
            text = "ERC and DRC have not run in this session. The files are made anyway."
        elif getattr(p, "ran_at", 0) + 1 < newest:
            text = "The board or schematic changed after the last ERC/DRC run."
        elif p.counts().get(C.BLOCK):
            text = f"ERC/DRC has {p.counts()[C.BLOCK]} blocking finding(s)."
        else:
            text = ""
        self.warn.SetLabel(text)
        self.Layout()

    def _show_existing(self):
        self.lst.DeleteAllItems()
        d = self.out_dir()
        if not os.path.isdir(d):
            return
        for fn in sorted(os.listdir(d)):
            p = os.path.join(d, fn)
            if os.path.isfile(p):
                i = self.lst.InsertItem(self.lst.GetItemCount(), fn)
                self.lst.SetItem(i, 1, f"{os.path.getsize(p) / 1024:.1f} KB")
                self.lst.SetItem(i, 2, time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(p))))

    def on_open_file(self, evt):
        open_file(os.path.join(self.out_dir(), self.lst.GetItemText(evt.GetIndex())))

    # --- generate
    def on_generate(self, _evt):
        if self.busy:
            return
        if self.frame.board is not None:
            B.save_board(self.frame.board, self.frame.paths["board"])
        cfg = wx.Config("IPC_STE_Assistant")
        cfg.Write("production_folder", self.folder.GetValue().strip() or "production")
        for k, cb in self.opt.items():
            cfg.WriteBool("production_" + k, cb.GetValue())
        cfg.Flush()
        opts = {k: cb.GetValue() for k, cb in self.opt.items()}
        opts["paste"] = True
        opts["raw_pos"] = True
        preset = self.presets[self.preset.GetSelection()]
        out, paths, req = self.out_dir(), self.frame.paths, self.frame.req
        self.busy = True
        self.go.Disable()
        self.gauge.Show()
        self._timer.Start(80)
        self.progress.SetLabel("Starting...")
        self.Layout()

        def work():
            err, files, notes = None, [], []
            try:
                design = None
                if opts["bom"]:
                    call_after(self.progress.SetLabel, "Reading the schematic...")
                    try:
                        design = core.load_design(paths)
                    except Exception as e:
                        notes.append(f"BOM not made: cannot read the schematic ({e}).")
                files, more = FB.export(paths, req, preset, out, opts, design,
                                        lambda m: call_after(self.progress.SetLabel, m), clean=False, note=False)
                notes = more + notes
            except (FB.FabError, OSError) as e:
                err = str(e)
            call_after(self._done, err, files, notes)
        threading.Thread(target=work, daemon=True).start()

    def _done(self, err, files, notes):
        self.busy = False
        self._timer.Stop()
        self.gauge.Hide()
        self.go.Enable()
        self._show_existing()
        self._warn()
        if err:
            self.progress.SetLabel("Failed.")
            self.frame.info(err, wx.ICON_ERROR)
            return
        self.files = files
        self.progress.SetLabel(f"{len(files)} file(s) made in {os.path.relpath(self.out_dir(), self.frame.paths['dir'])}.")
        self.frame.info("Production files made: " + "  ".join(notes), wx.ICON_INFORMATION)
        self.Layout()
