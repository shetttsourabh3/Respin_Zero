"""PowerPanel."""
from .common import *  # noqa: F401,F403
from .tab_findings import FindingsPanel


class PowerPanel(wx.Panel):
    """Findings plus a proper net summary table."""

    def __init__(self, parent, frame):
        super().__init__(parent)
        nb = wx.Notebook(self)
        self.findings = FindingsPanel(nb, frame, "power")
        summ = wx.Panel(nb)
        ss = wx.BoxSizer(wx.VERTICAL)
        self.sum_hint = muted(wx.StaticText(summ, label="Run the check to fill this table."))
        ss.Add(self.sum_hint, 0, wx.ALL, 10)
        self.table = wx.ListCtrl(summ, style=wx.LC_REPORT)
        for i, (c, w, a) in enumerate([("Net", 150, wx.LIST_FORMAT_LEFT), ("Group", 90, wx.LIST_FORMAT_LEFT),
                                       ("Current (A)", 90, wx.LIST_FORMAT_RIGHT), ("Voltage (V)", 90, wx.LIST_FORMAT_RIGHT),
                                       ("Track (mm)", 90, wx.LIST_FORMAT_RIGHT), ("Narrowest", 170, wx.LIST_FORMAT_LEFT),
                                       ("Rise (C)", 80, wx.LIST_FORMAT_RIGHT), ("Vias", 60, wx.LIST_FORMAT_RIGHT),
                                       ("Vias / change", 100, wx.LIST_FORMAT_RIGHT), ("V drop (mV)", 100, wx.LIST_FORMAT_RIGHT),
                                       ("Pour", 60, wx.LIST_FORMAT_LEFT)]):
            self.table.InsertColumn(i, c, a, w)
        ss.Add(self.table, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        summ.SetSizer(ss)
        nb.AddPage(self.findings, "Findings")
        nb.AddPage(summ, "Net summary")
        s = wx.BoxSizer(wx.VERTICAL)
        s.Add(nb, 1, wx.EXPAND)
        self.SetSizer(s)
        self.frame = frame

    def show_summary(self, summaries):
        lim = self.frame.req.temp_rise_c
        self.table.DeleteAllItems()
        for i, sm in enumerate(summaries):
            vals = [sm.net, sm.group, f"{sm.current_a:g}", f"{sm.voltage_v:g}", f"{sm.length_mm:.1f}", sm.narrowest,
                    ">200" if sm.est_rise_c > 200 else f"{sm.est_rise_c:.1f}", str(sm.vias), str(sm.vias_needed),
                    "-" if sm.has_pour else f"{sm.vdrop_v * 1000:.0f}", "yes" if sm.has_pour else "no"]
            idx = self.table.InsertItem(i, vals[0])
            for c, v in enumerate(vals[1:], 1):
                self.table.SetItem(idx, c, v)
            if sm.est_rise_c > lim:
                self.table.SetItemTextColour(idx, TIER_COLOUR[C.BLOCK] if sm.est_rise_c > max(3 * lim, 60)
                                             else TIER_COLOUR[C.RISK])
        self.sum_hint.SetLabel(f"Rise = estimated temperature rise of the narrowest track (limit {lim:g} C). "
                               "Vias / change = vias needed where the current changes layer. "
                               "V drop is a worst case and is not calculated for nets with a pour.")
        self.sum_hint.Wrap(900)
        self.sum_hint.GetParent().Layout()
