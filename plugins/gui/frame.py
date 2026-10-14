"""MainFrame, show."""
from .common import *  # noqa: F401,F403
import logging
import sys
from .. import diag as DG
from .tab_rules import RulesPanel
from .tab_nets import NetsPanel
from .tab_datasheets import DatasheetsPanel
from .tab_findings import FindingsPanel
from .tab_history import HistoryPanel
from .tab_fab import FabPanel
from .tab_production import ProductionPanel
from .tab_power import PowerPanel
from .tab_overview import OverviewPanel
from .nav import Sidebar
from .. import datasheets as DSL


_FRAME = None


def _install_excepthook():
    """Errors in the window go to the log (and still to KiCad's console)."""
    if getattr(sys.excepthook, "_respin_zero", False):
        return
    prev = sys.excepthook

    def hook(t, v, tb):
        import traceback
        DG.log.error("Unhandled error: %s", "".join(traceback.format_exception(t, v, tb))[-3000:])
        prev(t, v, tb)
    hook._respin_zero = True
    sys.excepthook = hook


class StatusChip(wx.Panel):
    """Rounded status chip in the header: '3 blocking' in red, 'Ready for review' in green."""

    def __init__(self, parent):
        super().__init__(parent)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.text, self.colour = "", ACCENT
        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_LEFT_DOWN, lambda e: self.GetTopLevelParent().go(0))
        self.SetCursor(wx.Cursor(wx.CURSOR_HAND))
        self.SetToolTip("Click for the overview")

    def set(self, text, colour):
        self.text, self.colour = text, colour
        f = self.GetFont()
        f.SetWeight(wx.FONTWEIGHT_BOLD)
        self.SetFont(f)
        w, h = self.GetTextExtent(text)
        self.SetMinSize((w + 34, h + 12))
        self.Refresh()

    def on_paint(self, _evt):
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(self.GetParent().GetBackgroundColour()))
        dc.Clear()
        gc = wx.GraphicsContext.Create(dc)
        w, h = self.GetClientSize()
        c = self.colour
        gc.SetBrush(wx.Brush(wx.Colour(255, 255, 255, 40) if c.Alpha() < 255 else c))
        gc.SetPen(wx.Pen(wx.Colour(255, 255, 255, 120), 1))
        gc.DrawRoundedRectangle(0.5, 0.5, w - 1, h - 1, (h - 1) / 2)
        gc.SetBrush(wx.Brush(wx.WHITE))
        gc.SetPen(wx.TRANSPARENT_PEN)
        gc.DrawEllipse(11, h / 2 - 3, 6, 6)
        gc.SetFont(self.GetFont(), wx.WHITE)
        tw, th = gc.GetTextExtent(self.text)
        gc.DrawText(self.text, 23, (h - th) / 2)


class MainFrame(wx.Frame):
    # (stage, sidebar label, page title, one-line description, icon, shortcut)
    PAGES = [
        ("Set up", "Overview", "Overview", "Where the design stands and what to do next.", None, "Ctrl+1"),
        ("Set up", "Design rules", "Design rules", "Answer a few questions; the IPC rules and fabricator limits follow.", "icon.png", "Ctrl+2"),
        ("Set up", "Nets & currents", "Nets and currents", "Give currents and voltages to power, ground and high-voltage nets.", "icon_nets.png", "Ctrl+3"),
        ("Set up", "Datasheets", "Datasheets", "Keep each part's datasheet with the project, for you and for the AI review.", "icon_ds.png", "Ctrl+4"),
        ("Review", "Schematic review", "Schematic review", "Rule checks and chip profiles on the saved schematic; optional AI review.", "icon_sch.png", "Ctrl+5"),
        ("Review", "ERC / DRC", "ERC and DRC", "KiCad's electrical and design rule checks, explained and sorted by risk.", "icon_check.png", "Ctrl+6"),
        ("Review", "Power & thermal", "Power and thermal", "Track heating, vias and voltage drop on every power net.", "icon_power.png", "Ctrl+7"),
        ("Release", "Production files", "Production files", "Gerber zip, position file and BOM in one click.", "icon_prod.png", "Ctrl+8"),
        ("Release", "Fabrication", "Fabrication", "Final checks, then the files for your fabricator, saved as a version.", "icon_fab.png", "Ctrl+9"),
        ("Release", "History", "History", "Versions, milestones and what changed between them.", "icon_hist.png", "Ctrl+0"),
    ]
    TABS = [p[2] for p in PAGES]

    def __init__(self, board, paths):
        cfg = wx.Config("IPC_STE_Assistant")
        w, h = cfg.ReadInt("width", 1280), cfg.ReadInt("height", 820)
        super().__init__(None, title="Respin Zero", size=(w, h))
        self.SetMinSize((980, 640))
        self.board, self.paths = board, paths
        self.req = core.load_req(board, paths)
        self.profiles = M.load(paths["dir"])
        self.presets = R.load_presets()
        try:
            self.SetIcon(wx.Icon(os.path.join(HERE, "icon.png"), wx.BITMAP_TYPE_PNG))
        except Exception:
            pass

        root = wx.Panel(self)
        s = wx.BoxSizer(wx.VERTICAL)
        s.Add(self._header(root), 0, wx.EXPAND)
        self.infobar = wx.InfoBar(root)
        s.Add(self.infobar, 0, wx.EXPAND)

        body = wx.BoxSizer(wx.HORIZONTAL)
        self.nav = Sidebar(root, [(p[0], p[1], p[4], p[5]) for p in self.PAGES], self._nav_select,
                           cfg.ReadBool("nav_collapsed", False))
        body.Add(self.nav, 0, wx.EXPAND)
        content = wx.BoxSizer(wx.VERTICAL)
        head = wx.BoxSizer(wx.HORIZONTAL)
        titles = wx.BoxSizer(wx.VERTICAL)
        self.page_stage = muted(wx.StaticText(root, label=""))
        self.page_title = bold(wx.StaticText(root, label=""), 6)
        self.page_desc = muted(wx.StaticText(root, label=""))
        titles.Add(self.page_stage, 0)
        titles.Add(self.page_title, 0, wx.TOP, 1)
        titles.Add(self.page_desc, 0, wx.TOP, 2)
        head.Add(titles, 1)
        self.next_btn = wx.Button(root, label="Next step")
        self.next_btn.SetToolTip("Go to the next page in the workflow.   Ctrl+Page Down")
        self.next_btn.Bind(wx.EVT_BUTTON, lambda e: self.go(min(self.nb.GetSelection() + 1, len(self.PAGES) - 1)))
        head.Add(self.next_btn, 0, wx.ALIGN_BOTTOM)
        content.Add(head, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 16)
        line = wx.StaticLine(root)
        content.Add(line, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 12)

        self.nb = wx.Simplebook(root)
        self.overview = OverviewPanel(self.nb, self)
        self.rules = RulesPanel(self.nb, self)
        self.nets = NetsPanel(self.nb, self)
        self.ds_tab = DatasheetsPanel(self.nb, self)
        self.sch_tab = FindingsPanel(self.nb, self, "sch")
        self.check_tab = FindingsPanel(self.nb, self, "check")
        self.power_tab = PowerPanel(self.nb, self)
        self.prod_tab = ProductionPanel(self.nb, self)
        self.fab_tab = FabPanel(self.nb, self)
        self.hist_tab = HistoryPanel(self.nb, self)
        for page, title in zip((self.overview, self.rules, self.nets, self.ds_tab, self.sch_tab, self.check_tab,
                                self.power_tab, self.prod_tab, self.fab_tab, self.hist_tab), self.TABS):
            self.nb.AddPage(page, title)
        self.nb.Bind(wx.EVT_BOOKCTRL_PAGE_CHANGED, self.on_tab)
        content.Add(self.nb, 1, wx.EXPAND | wx.ALL, 6)
        body.Add(content, 1, wx.EXPAND)
        s.Add(body, 1, wx.EXPAND)
        root.SetSizer(s)

        self.sb = self.CreateStatusBar()
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self._shortcuts()
        self.overview.refresh()
        tab = cfg.ReadInt("tab", 0)
        self.go(tab if 0 <= tab < self.nb.GetPageCount() else 0)
        self.status(f"{os.path.basename(paths['board'])}  |  answers in {os.path.basename(paths['cfg'])}  |  "
                    "Ctrl+1...0 pages, Ctrl+R run all checks, Ctrl+B labels")

    # --- navigation
    def go(self, i):
        """Show page i (also from code and tests: nb.SetSelection works the same way)."""
        if self.nb.GetSelection() != i:
            self.nb.SetSelection(i)            # sends the page-changed event -> on_tab
        else:
            self._page_shown(i)

    def _nav_select(self, i):
        self.go(i)

    def _page_shown(self, i):
        stage, _l, title, desc, _ic, _k = self.PAGES[i]
        stages = ["Set up", "Review", "Release"]
        self.page_stage.SetLabel(f"{stage.upper()}  ·  STEP {stages.index(stage) + 1} OF 3" if stage in stages
                                 else stage.upper())
        self.page_title.SetLabel(title)
        self.page_desc.SetLabel(desc)
        self.next_btn.Show(i < len(self.PAGES) - 1)
        if i < len(self.PAGES) - 1:
            self.next_btn.SetLabel(f"Next: {self.PAGES[i + 1][1]}  →".replace("&", "&&"))
        self.nav.set_selection(i)
        self.page_title.GetParent().Layout()
        self.refresh_nav()

    def _shortcuts(self):
        entries, self._acc_ids = [], {}
        keys = [ord(str(d)) for d in (1, 2, 3, 4, 5, 6, 7, 8, 9, 0)]
        for i, k in enumerate(keys[:len(self.PAGES)]):
            wid = wx.NewIdRef()
            self.Bind(wx.EVT_MENU, lambda e, n=i: self.go(n), id=wid)
            entries.append(wx.AcceleratorEntry(wx.ACCEL_CTRL, k, wid))
        for flags, key, fn in ((wx.ACCEL_CTRL, ord("R"), lambda e: self.run_all()),
                               (wx.ACCEL_CTRL, ord("B"), lambda e: self.nav.toggle()),
                               (wx.ACCEL_CTRL, wx.WXK_PAGEDOWN, lambda e: self.go(min(self.nb.GetSelection() + 1, len(self.PAGES) - 1))),
                               (wx.ACCEL_CTRL, wx.WXK_PAGEUP, lambda e: self.go(max(self.nb.GetSelection() - 1, 0))),
                               (wx.ACCEL_NORMAL, wx.WXK_F1, lambda e: open_file(os.path.join(HERE, "README.md")))):
            wid = wx.NewIdRef()
            self.Bind(wx.EVT_MENU, fn, id=wid)
            entries.append(wx.AcceleratorEntry(flags, key, wid))
        self.SetAcceleratorTable(wx.AcceleratorTable(entries))

    def run_all(self):
        if self.overview.run_all.IsEnabled():
            self.overview.on_run_all(None)

    def refresh_nav(self):
        """Status badges in the sidebar: red/orange counts, green tick when done, dot when to do."""
        if not hasattr(self, "nav") or not hasattr(self, "hist_tab"):
            return
        grey = wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT)
        red, orange = TIER_COLOUR[C.BLOCK], TIER_COLOUR[C.RISK]
        b = {}
        b[1] = ("check", "", GOOD) if core.rules_applied(self.paths) else ("dot", "", orange)
        b[2] = ("check", "", GOOD) if any(getattr(g, "current_a", 0) for g in self.req.net_groups) else ("dot", "", orange)
        try:
            n = len(DSL.Library(self.paths["dir"]).entries)
            if n:
                b[3] = ("text", str(n), grey)
        except Exception:
            pass
        for i, p in ((4, self.sch_tab), (5, self.check_tab), (6, self.power_tab.findings)):
            if not p.ran:
                continue
            c = p.counts()
            b[i] = ("count", str(c[C.BLOCK]), red) if c[C.BLOCK] else \
                ("count", str(c[C.RISK]), orange) if c[C.RISK] else ("check", "", GOOD)
        prod = os.path.join(self.paths["dir"], self.prod_tab.folder.GetValue().strip() or "production") \
            if not os.path.isabs(self.prod_tab.folder.GetValue().strip() or "production") else self.prod_tab.folder.GetValue()
        if os.path.isdir(prod) and any(f.endswith(".zip") for f in os.listdir(prod)):
            b[7] = ("check", "", GOOD)
        fb = [c for c in getattr(self.fab_tab, "checks", []) if c.level == "fail"]
        if getattr(self.fab_tab, "checks", None):
            b[8] = ("count", str(len(fb)), red) if fb else ("check", "", GOOD)
        hb = getattr(self, "_hist_badge", None)
        now = time.time()
        if hb is None or now - hb[0] > 5:
            try:
                repo = VC.Repo(self.paths["dir"])
                val = None if not repo.ok else len(repo.changes())
            except Exception:
                val = None
            self._hist_badge = hb = (now, val)
        if hb[1] is None:
            b[9] = ("text", "Off", grey)
        elif hb[1]:
            b[9] = ("count", str(hb[1]), orange)
        else:
            b[9] = ("check", "", GOOD)
        self.nav.set_badges(b)

    def _header(self, parent):
        hp = wx.Panel(parent)
        hp.SetBackgroundColour(ACCENT)
        hs = wx.BoxSizer(wx.HORIZONTAL)
        logo = wx.StaticBitmap(hp, bitmap=icon("logo.png", 30))
        hs.Add(logo, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 14)
        titles = wx.BoxSizer(wx.VERTICAL)
        t = bold(wx.StaticText(hp, label="Respin Zero"), 3)
        t.SetForegroundColour(wx.WHITE)
        try:
            import pcbnew
            ver = pcbnew.Version()
        except Exception:
            ver = "?"
        where = "opened without the PCB editor" if self.board is None else f"KiCad {ver}"
        sub = wx.StaticText(hp, label=f"{os.path.basename(self.paths['board'])}   \u00b7   {where}")
        sub.SetForegroundColour(wx.Colour(220, 232, 248))
        titles.Add(t, 0)
        titles.Add(sub, 0, wx.TOP, 1)
        hs.Add(titles, 1, wx.ALL, 10)
        self.pill = StatusChip(hp)
        hs.Add(self.pill, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)
        self.run_all_btn = wx.Button(hp, label="Run all checks")
        self.run_all_btn.SetToolTip("Schematic review, ERC/DRC and the power check, one after the other.   Ctrl+R")
        self.run_all_btn.Bind(wx.EVT_BUTTON, lambda e: self.run_all())
        hs.Add(self.run_all_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 16)
        lab = wx.StaticText(hp, label="Level")
        lab.SetForegroundColour(wx.WHITE)
        self.level = wx.Choice(hp, choices=R.LEVELS)
        self.level.SetSelection(R.LEVELS.index(self.req.level) if self.req.level in R.LEVELS else 0)
        self.level.SetToolTip("Beginner: few plain questions and explanations.\nIntermediate: all IPC options "
                              "and the reason for each value.\nExpert: override fabricator values; less guidance.")
        self.level.Bind(wx.EVT_CHOICE, self.on_level)
        hs.Add(lab, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        hs.Add(self.level, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)
        hp.SetSizer(hs)
        return hp

    # --- shared helpers
    def info(self, text, flags=wx.ICON_INFORMATION):
        lvl = {wx.ICON_ERROR: logging.ERROR, wx.ICON_WARNING: logging.WARNING}.get(flags, logging.INFO)
        DG.log.log(lvl, "%s: %s", self.nb.GetPageText(self.nb.GetSelection()) if hasattr(self, "nb") else "-",
                   text.replace("\n", " | ")[:600])
        self.infobar.ShowMessage(text, flags)
        self.status(text)
        self._info_id = getattr(self, "_info_id", 0) + 1
        if flags == wx.ICON_INFORMATION:          # warnings and errors stay until closed
            my = self._info_id
            wx.CallLater(8000, lambda: self._info_id == my and self.infobar.IsShown() and self.infobar.Dismiss())

    def status(self, text):
        self.sb.SetStatusText(text)

    def set_status_pill(self):
        if not hasattr(self, "pill"):
            return
        panels = [self.sch_tab, self.check_tab, self.power_tab.findings] if hasattr(self, "power_tab") else []
        blocking = sum(p.counts()[C.BLOCK] for p in panels)
        ran = bool(panels) and all(p.ran for p in panels)
        self.pill.set(f"{blocking} blocking" if blocking else "Ready for review" if ran else "Checks not run",
                      TIER_COLOUR[C.BLOCK] if blocking else GOOD if ran else wx.Colour(255, 255, 255, 60))
        self.pill.GetParent().Layout()
        self.refresh_nav()

    def on_level(self, _evt):
        self.req.level = self.level.GetStringSelection()
        core.save_req(self.req, self.paths)
        self.rules.set_level(self.req.level)
        for p in (self.sch_tab, self.check_tab, self.power_tab.findings):
            p.toggles[C.COSMETIC].SetValue(self.req.level != "Beginner")
            p.refresh()
        self.overview.refresh()
        self.status(f"Level: {self.req.level}")

    def _lazy(self, tab):
        if tab == 2:
            self.nets.load()
        if tab == 3:
            self.ds_tab.load()
        if tab == 7:
            self.prod_tab.load()
        if tab == 8:
            self.fab_tab.load()
        if tab == 9:
            self.hist_tab.load()
        if tab == 0:
            self.overview.refresh()
        for t, panel in ((4, self.sch_tab), (5, self.check_tab), (6, self.power_tab.findings)):
            if tab == t:
                panel.update_stale()
        for t, panel in ((4, self.sch_tab), (5, self.check_tab)):
            if tab == t and getattr(panel, "_ai_ok", False):
                panel._ai_account_done(panel._provider(), True, panel._ai_text)

    def on_tab(self, evt):
        i = evt.GetSelection()
        self._lazy(i)
        self._page_shown(i)
        evt.Skip()

    def on_close(self, evt):
        global _FRAME
        cfg = wx.Config("IPC_STE_Assistant")
        w, h = self.GetSize()
        cfg.WriteInt("width", w)
        cfg.WriteInt("height", h)
        cfg.WriteInt("tab", self.nb.GetSelection())
        cfg.Flush()
        _FRAME = None
        evt.Skip()



def show(board, paths):
    """Open the window, or bring the open one to the front."""
    global _FRAME
    DG.setup_logging()
    _install_excepthook()
    if _FRAME:
        try:
            if _FRAME.paths["board"] == paths["board"]:
                _FRAME.Raise()
                _FRAME.overview.refresh()
                return _FRAME
            _FRAME.Close()
        except RuntimeError:       # window was destroyed
            pass
    _FRAME = MainFrame(board, paths)
    _FRAME.Show()
    return _FRAME
