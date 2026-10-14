"""NetsPanel."""
from .common import *  # noqa: F401,F403


class NetsPanel(wx.Panel):
    COLS = ["Net", "Group", "Current (A)", "Peak voltage (V)", "Source"]

    def __init__(self, parent, frame):
        super().__init__(parent)
        self.frame, self.nets, self.view, self.loaded = frame, [], [], False
        s = wx.BoxSizer(wx.VERTICAL)
        intro = muted(wx.StaticText(self, label=(
            "The plugin guesses the group of each net from its name. Give the maximum current for power and "
            "ground nets, and the peak voltage for high-voltage nets (230 V mains = 340 V peak).")))
        intro.Wrap(900)
        s.Add(intro, 0, wx.ALL, 10)
        top = wx.BoxSizer(wx.HORIZONTAL)
        self.search = wx.SearchCtrl(self, size=(220, -1))
        self.search.ShowCancelButton(True)
        self.search.SetDescriptiveText("Filter nets")
        self.search.Bind(wx.EVT_TEXT, lambda e: self._fill())
        self.show_all = wx.CheckBox(self, label="Show signal nets")
        self.show_all.Bind(wx.EVT_CHECKBOX, lambda e: self._fill())
        redetect = wx.Button(self, label="Guess again from names")
        redetect.SetToolTip("Replace unsaved guesses. Rows you edited or saved are kept.")
        redetect.Bind(wx.EVT_BUTTON, lambda e: self.load(force=True))
        top.Add(self.search, 0, wx.RIGHT, 10)
        top.Add(self.show_all, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        top.AddStretchSpacer()
        top.Add(redetect, 0)
        s.Add(top, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        self.grid = gr = gridlib.Grid(self)
        gr.CreateGrid(0, len(self.COLS))
        for i, c in enumerate(self.COLS):
            gr.SetColLabelValue(i, c)
        for col, attr in ((0, "ro"), (1, "choice"), (2, "float"), (3, "float"), (4, "ro")):
            a = gridlib.GridCellAttr()
            if attr == "ro":
                a.SetReadOnly(True)
            elif attr == "choice":
                a.SetEditor(gridlib.GridCellChoiceEditor(R.GROUPS))
            else:
                a.SetEditor(gridlib.GridCellFloatEditor(-1, 2))
                a.SetAlignment(wx.ALIGN_RIGHT, wx.ALIGN_CENTER)
            gr.SetColAttr(col, a)
        gr.SetRowLabelSize(0)
        gr.SetDefaultRowSize(26)
        gr.EnableDragRowSize(False)
        gr.Bind(gridlib.EVT_GRID_CELL_CHANGED, self.on_change)
        s.Add(gr, 1, wx.EXPAND | wx.ALL, 10)

        bar = wx.BoxSizer(wx.HORIZONTAL)
        save = wx.Button(self, label="Save nets")
        save.Bind(wx.EVT_BUTTON, lambda e: self.save(False))
        apply = primary_button(self, "Save and apply rules")
        apply.Bind(wx.EVT_BUTTON, lambda e: self.save(True))
        self.count = muted(wx.StaticText(self, label=""))
        bar.Add(apply, 0, wx.RIGHT, 8)
        bar.Add(save, 0, wx.RIGHT, 16)
        bar.Add(self.count, 0, wx.ALIGN_CENTER_VERTICAL)
        s.Add(bar, 0, wx.ALL, 10)
        self.SetSizer(s)

    def load(self, force=False):
        if self.loaded and not force:
            return
        keep = {n["net"]: n for n in self.nets if not n.get("guessed")} if force else {}
        nets = core.detect_nets(self.frame.board, self.frame.req)
        self.nets = [keep.get(n["net"], n) for n in nets]
        self.loaded = True
        self._fill()
        if not self.nets:
            self.frame.info("The board has no nets. Update the PCB from the schematic first.", wx.ICON_WARNING)

    def _fill(self):
        gr = self.grid
        gr.BeginBatch()
        if gr.GetNumberRows():
            gr.DeleteRows(0, gr.GetNumberRows())
        q = self.search.GetValue().strip().upper()
        show_all = self.show_all.GetValue()
        self.view = [i for i, n in enumerate(self.nets)
                     if (show_all or n["group"] != "Signal") and (not q or q in n["net"].upper())]
        gr.AppendRows(len(self.view))
        for r, i in enumerate(self.view):
            self._paint(r, self.nets[i])
        gr.SetColSize(0, 260)
        for c, w in ((1, 140), (2, 110), (3, 130), (4, 90)):
            gr.SetColSize(c, w)
        gr.EndBatch()
        self._count()

    def _count(self):
        n_sig = sum(1 for n in self.nets if n["group"] == "Signal")
        need = sum(1 for n in self.nets if n["group"] in ("Power", "Ground") and n["current_a"] <= 0)
        txt = f"{len(self.nets)} nets: {len(self.nets) - n_sig} power, ground or high voltage; {n_sig} signal."
        if need:
            txt += f"  {need} still need a current."
        self.count.SetLabel(txt)

    def _paint(self, r, n):
        gr = self.grid
        gr.SetCellValue(r, 0, n["net"])
        gr.SetCellValue(r, 1, n["group"])
        gr.SetCellValue(r, 2, f"{n['current_a']:g}")
        gr.SetCellValue(r, 3, f"{n['voltage_v']:g}")
        gr.SetCellValue(r, 4, "guess" if n.get("guessed") else "edited" if n.get("edited") else "saved")
        bg = tint(GROUP_TINT.get(n["group"])) or wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)
        row = gridlib.GridCellAttr()
        row.SetBackgroundColour(bg)
        gr.SetRowAttr(r, row)
        missing = n["group"] in ("Power", "Ground") and n["current_a"] <= 0
        gr.SetCellTextColour(r, 2, TIER_COLOUR[C.BLOCK] if missing else gr.GetDefaultCellTextColour())

    def on_change(self, evt):
        r, c = evt.GetRow(), evt.GetCol()
        n = self.nets[self.view[r]]
        val = self.grid.GetCellValue(r, c)
        try:
            if c == 1:
                n["group"] = val
            elif c == 2:
                n["current_a"] = max(0.0, float(val or 0))
            elif c == 3:
                n["voltage_v"] = max(0.0, float(val or 0))
            n["guessed"], n["edited"] = False, True
        except ValueError:
            pass
        self._paint(r, n)
        self.grid.ForceRefresh()
        self._count()

    def groups(self):
        self.grid.SaveEditControlValue()
        return [R.NetGroup(n["net"], n["group"], n["current_a"], n["voltage_v"])
                for n in self.nets if n["group"] != "Signal"]

    def save(self, apply):
        self.frame.req.net_groups = self.groups()
        core.save_req(self.frame.req, self.frame.paths)
        for n in self.nets:
            n["guessed"] = n["edited"] = False
        self._fill()
        self.frame.overview.refresh()
        if apply:
            self.frame.rules.on_apply(None)
        else:
            self.frame.info(f"{len(self.frame.req.net_groups)} nets saved.", wx.ICON_INFORMATION)
