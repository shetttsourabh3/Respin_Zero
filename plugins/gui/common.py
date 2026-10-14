"""Respin Zero - shared helpers for the window with tabs (KiCad 10).

Overview | Design Rules | Nets | ERC / DRC | Power & Thermal
"""
import os
import re
import shutil
import tempfile
import threading
import time

import wx
import wx.grid as gridlib
import wx.lib.scrolledpanel as scrolled

from .. import core
from .. import rules as R
from .. import checks as C
from .. import manufacturers as M
from .. import waivers as W
from .. import board as B
from .. import powercheck as PC
from .. import aiproviders as AP
from .. import skills as SK
from .. import datasheets as DS
from .. import vcs as VC

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACCENT = wx.Colour(30, 110, 200)
TIER_COLOUR = {C.BLOCK: wx.Colour(205, 45, 45), C.RISK: wx.Colour(200, 115, 0), C.COSMETIC: wx.Colour(125, 125, 125)}
GOOD = wx.Colour(40, 150, 80)
GROUP_TINT = {"Power": wx.Colour(255, 240, 220), "Ground": wx.Colour(228, 238, 250),
              "High voltage": wx.Colour(255, 225, 225), "Signal": None}
_FRAME = None


def call_after(fn, *args):
    """wx.CallAfter that is safe when the window (or the app) closed while a worker thread was busy."""
    if wx.GetApp() is None:
        return

    def run():
        try:
            fn(*args)
        except RuntimeError as e:          # "wrapped C/C++ object ... has been deleted"
            if "deleted" not in str(e):
                raise
    wx.CallAfter(run)


def is_dark():
    try:
        return wx.SystemSettings.GetAppearance().IsDark()
    except Exception:
        return wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW).GetLuminance() < 0.5


def tint(c):
    """Group row tint, softened in dark mode."""
    if c is None:
        return None
    if is_dark():
        return wx.Colour(int(c.Red() * 0.25), int(c.Green() * 0.25), int(c.Blue() * 0.25))
    return c


def icon(name, size=16):
    p = os.path.join(HERE, name)
    if not os.path.isfile(p):
        return wx.NullBitmap
    img = wx.Image(p)
    return wx.Bitmap(img.Scale(size, size, wx.IMAGE_QUALITY_HIGH))


def bold(win, delta=0):
    f = win.GetFont()
    f.SetWeight(wx.FONTWEIGHT_BOLD)
    if delta:
        f.SetPointSize(f.GetPointSize() + delta)
    win.SetFont(f)
    if isinstance(win, wx.StaticText):
        win.SetLabel(win.GetLabel())        # re-measure with the new font, so long titles are not cut
        win.InvalidateBestSize()
        win.SetInitialSize()
    return win


def muted(win):
    win.SetForegroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT))
    return win


def primary_button(parent, label):
    b = wx.Button(parent, label=label)
    b.SetDefault()
    return b


def open_file(path):
    if os.path.isfile(path):
        wx.LaunchDefaultApplication(path)


class TextView(wx.Dialog):
    def __init__(self, parent, title, text, extra=()):
        super().__init__(parent, title=title, style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        s = wx.BoxSizer(wx.VERTICAL)
        t = wx.TextCtrl(self, value=text, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL)
        t.SetFont(wx.Font(9, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        s.Add(t, 1, wx.EXPAND | wx.ALL, 8)
        row = wx.BoxSizer(wx.HORIZONTAL)
        for label, fn in extra:
            b = wx.Button(self, label=label)
            b.Bind(wx.EVT_BUTTON, lambda e, f=fn: f())
            row.Add(b, 0, wx.RIGHT, 6)
        row.AddStretchSpacer()
        row.Add(self.CreateButtonSizer(wx.OK), 0)
        s.Add(row, 0, wx.EXPAND | wx.ALL, 8)
        self.SetSizer(s)
        self.SetSize((900, 640))


class NumField(wx.TextCtrl):
    """Text field that turns red while the value is not a valid number."""

    def __init__(self, parent, owner, minimum=0.0, integer=False):
        super().__init__(parent, size=(110, -1))
        self.owner, self.minimum, self.integer = owner, minimum, integer
        self._normal = self.GetBackgroundColour()
        self.Bind(wx.EVT_TEXT, self._check)

    def value(self):
        v = float(self.GetValue().strip())
        if self.integer:
            v = int(v)
        if v < self.minimum:
            raise ValueError
        return v

    def valid(self):
        if not self.IsEnabled():
            return True
        try:
            self.value()
            return True
        except ValueError:
            return False

    def _check(self, evt):
        ok = self.valid()
        self.SetBackgroundColour(self._normal if ok else wx.Colour(255, 205, 205))
        self.SetToolTip(None if ok else f"Type a number of {self.minimum:g} or more.")
        self.Refresh()
        self.owner.on_validity()
        evt.Skip()

