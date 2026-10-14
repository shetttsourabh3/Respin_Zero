"""DatasheetsPanel."""
from .common import *  # noqa: F401,F403


class DatasheetsPanel(wx.Panel):
    COLS = [("Category", 150), ("Part", 230), ("Used as", 170), ("Datasheet", 300), ("AI", 50)]

    def __init__(self, parent, frame):
        super().__init__(parent)
        self.frame, self.groups, self.rows, self.loaded, self.busy = frame, [], [], False, False
        self.lib = DS.Library(frame.paths["dir"])
        s = wx.BoxSizer(wx.VERTICAL)
        intro = muted(wx.StaticText(self, label=(
            "Keep the datasheet of each part with the project. Files are copied into "
            f"'{DS.FOLDER}/<category>/' next to the board, so they stay with the design. Datasheets marked AI are "
            "given to the AI tool during a review (as read-only files, or as extracted text for tools that cannot open PDFs), so it can check pins and limits.")))
        intro.Wrap(1000)
        s.Add(intro, 0, wx.ALL, 10)
        top = wx.BoxSizer(wx.HORIZONTAL)
        self.search = wx.SearchCtrl(self, size=(220, -1))
        self.search.ShowCancelButton(True)
        self.search.SetDescriptiveText("Filter parts")
        self.search.Bind(wx.EVT_TEXT, lambda e: self._fill())
        self.show_passive = wx.CheckBox(self, label="Show resistors and capacitors")
        self.show_passive.Bind(wx.EVT_CHECKBOX, lambda e: self._fill())
        self.only_missing = wx.CheckBox(self, label="Only missing")
        self.only_missing.Bind(wx.EVT_CHECKBOX, lambda e: self._fill())
        reload_ = wx.Button(self, label="Reload parts")
        reload_.Bind(wx.EVT_BUTTON, lambda e: self.load(force=True))
        folder = wx.Button(self, label="Open datasheets folder")
        folder.Bind(wx.EVT_BUTTON, self.on_folder)
        for w in (self.search, self.show_passive, self.only_missing):
            top.Add(w, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        top.AddStretchSpacer()
        top.Add(reload_, 0, wx.RIGHT, 6)
        top.Add(folder, 0)
        s.Add(top, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        self.lst = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for i, (c, w) in enumerate(self.COLS):
            self.lst.InsertColumn(i, c, width=w)
        self.lst.Bind(wx.EVT_LIST_ITEM_SELECTED, self._selected_changed)
        self.lst.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda e: self.on_open(None))
        s.Add(self.lst, 1, wx.EXPAND | wx.ALL, 10)
        self.detail = muted(wx.StaticText(self, label=""))
        s.Add(self.detail, 0, wx.LEFT | wx.RIGHT, 10)

        bar = wx.BoxSizer(wx.HORIZONTAL)
        self.btns = {}
        for key, label, fn in [("add", "Add datasheet...", self.on_add),
                               ("download", "Download from symbol link", self.on_download),
                               ("open", "Open", self.on_open), ("ai", "Send to AI: on/off", self.on_toggle_ai),
                               ("remove", "Remove", self.on_remove), ("match", "Find matching files", self.on_match)]:
            b = primary_button(self, label) if key == "add" else wx.Button(self, label=label)
            b.Bind(wx.EVT_BUTTON, fn)
            self.btns[key] = b
            bar.Add(b, 0, wx.RIGHT, 6)
        s.Add(bar, 0, wx.ALL, 10)
        self.count = muted(wx.StaticText(self, label=""))
        s.Add(self.count, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(s)
        self._selected_changed(None)

    # --- loading
    def load(self, force=False):
        if (self.loaded and not force) or self.busy:
            return
        self.busy = True
        self.count.SetLabel("Reading the parts from the saved schematic...")
        paths = self.frame.paths

        def work():
            try:
                out = core.load_design(paths), None
            except Exception as e:
                out = None, str(e)
            call_after(self._loaded, *out)
        threading.Thread(target=work, daemon=True).start()

    def _loaded(self, design, err):
        self.busy = False
        if err:
            self.count.SetLabel(f"Cannot read the schematic: {err}")
            return
        self.design, self.loaded = design, True
        self._regroup()

    def _regroup(self):
        self.lib.load()
        self.groups = DS.groups_from_design(self.design, self.lib)
        self._fill()

    def _fill(self):
        q = self.search.GetValue().strip().lower()
        passives = self.show_passive.GetValue()
        missing = self.only_missing.GetValue()
        self.rows = [g for g in self.groups
                     if (passives or g.kind not in ("R", "C", "L", "FB"))
                     and (not missing or not g.entry)
                     and (not q or q in f"{g.label} {' '.join(g.refs)} {g.category} {g.mpn}".lower())]
        self.lst.Freeze()
        self.lst.DeleteAllItems()
        for i, g in enumerate(self.rows):
            idx = self.lst.InsertItem(i, g.category)
            self.lst.SetItem(idx, 1, g.label)
            self.lst.SetItem(idx, 2, ", ".join(g.refs[:8]) + (" ..." if len(g.refs) > 8 else ""))
            if g.entry:
                self.lst.SetItem(idx, 3, g.entry.file)
                self.lst.SetItem(idx, 4, "yes" if g.entry.send_to_ai else "no")
            else:
                self.lst.SetItem(idx, 3, "missing - link in symbol" if g.url.startswith("http") else "missing")
                self.lst.SetItemTextColour(idx, TIER_COLOUR[C.RISK])
        self.lst.Thaw()
        active = [g for g in self.groups if g.kind not in ("R", "C", "L", "FB")]
        have = sum(1 for g in active if g.entry)
        self.count.SetLabel(f"{len(active)} parts (without resistors and capacitors): {have} with datasheets, "
                            f"{len(active) - have} missing.   Folder: {self.lib.root}")
        self._selected_changed(None)

    def _sel(self):
        i = self.lst.GetFirstSelected()
        return self.rows[i] if 0 <= i < len(self.rows) else None

    def _selected_changed(self, _evt):
        g = self._sel()
        self.btns["add"].Enable(g is not None and not self.busy)
        self.btns["download"].Enable(bool(g and g.url.startswith("http")) and not self.busy)
        for k in ("open", "ai", "remove"):
            self.btns[k].Enable(bool(g and g.entry))
        self.btns["match"].Enable(bool(self.groups))
        if g:
            bits = [f"{g.label}  |  {g.category}  |  {', '.join(g.refs)}"]
            if g.mpn:
                bits.append(f"MPN {g.mpn}")
            if g.url:
                bits.append(f"symbol link: {g.url[:90]}")
            if g.entry:
                bits.append(f"added {g.entry.added} from {g.entry.source}")
            self.detail.SetLabel("   ".join(bits))
        else:
            self.detail.SetLabel("Select a part.")

    # --- actions
    def on_add(self, _evt):
        g = self._sel()
        if not g:
            return
        with wx.FileDialog(self, f"Datasheet for {g.label}", wildcard="PDF files (*.pdf)|*.pdf|All files|*.*",
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as fd:
            if fd.ShowModal() != wx.ID_OK:
                return
            e = self.lib.add(fd.GetPath(), g)
        self._regroup()
        self.frame.info(f"Datasheet for {g.label} saved as {DS.FOLDER}/{e.file}.", wx.ICON_INFORMATION)

    def on_download(self, _evt):
        g = self._sel()
        if not g:
            return
        self.busy = True
        self._selected_changed(None)
        self.count.SetLabel(f"Downloading the datasheet of {g.label}...")

        def work():
            try:
                e = self.lib.download(g.url, g)
                msg, flag = f"Downloaded the datasheet of {g.label} to {DS.FOLDER}/{e.file}.", wx.ICON_INFORMATION
            except Exception as ex:
                msg, flag = f"Could not download the datasheet of {g.label}: {ex}", wx.ICON_WARNING
            call_after(self._downloaded, msg, flag)
        threading.Thread(target=work, daemon=True).start()

    def _downloaded(self, msg, flag):
        self.busy = False
        self._regroup()
        self.frame.info(msg, flag)

    def on_open(self, _evt):
        g = self._sel()
        if g and g.entry:
            open_file(self.lib.path(g.entry))

    def on_toggle_ai(self, _evt):
        g = self._sel()
        if g and g.entry:
            self.lib.set_ai(g, not g.entry.send_to_ai)
            self._regroup()
            for p in (self.frame.sch_tab, self.frame.check_tab):
                p._ai_status()

    def on_remove(self, _evt):
        g = self._sel()
        if not g or not g.entry:
            return
        ans = wx.MessageBox(f"Remove the datasheet link for {g.label}?\n\nYes = also delete the file\n"
                            "No = keep the file in the folder", "Remove datasheet",
                            wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION, self)
        if ans == wx.CANCEL:
            return
        self.lib.unlink(g, delete_file=(ans == wx.YES))
        self._regroup()

    def on_match(self, _evt):
        n = self.lib.auto_match(self.groups)
        self._regroup()
        self.frame.info(f"Linked {n} datasheet(s) found in {DS.FOLDER}/ by file name." if n else
                        "No unlinked PDF in the datasheets folder matches a part name.", wx.ICON_INFORMATION)

    def on_folder(self, _evt):
        os.makedirs(self.lib.root, exist_ok=True)
        wx.LaunchDefaultApplication(self.lib.root)
