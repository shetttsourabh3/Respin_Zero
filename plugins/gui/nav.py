"""Sidebar navigation: pages grouped by stage (Set up, Review, Release), each with a live status badge.

Drawn by hand so it looks the same on Windows, macOS and Linux, follows light and dark mode, and can collapse
to icons only.
"""
from .common import *  # noqa: F401,F403

# badge kinds: ("count", "7", colour)  ("check", "", colour)  ("dot", "", colour)  ("text", "Off", colour)


def _mix(a, b, t):
    return wx.Colour(int(a.Red() + (b.Red() - a.Red()) * t), int(a.Green() + (b.Green() - a.Green()) * t),
                     int(a.Blue() + (b.Blue() - a.Blue()) * t))


class Sidebar(wx.Panel):
    WIDE, NARROW, ROW, HEAD = 214, 56, 34, 30

    def __init__(self, parent, items, on_select, collapsed=False):
        """items: [(section, label, icon_file, shortcut_text)]; on_select(index)."""
        super().__init__(parent, style=wx.WANTS_CHARS)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.items, self.on_select = items, on_select
        self.sel, self.hover, self.collapsed = 0, -1, collapsed
        self.badges = {}
        self.bmps = [icon(f, 18) if f else wx.NullBitmap for _s, _l, f, _k in items]
        self.SetMinSize((self.NARROW if collapsed else self.WIDE, -1))
        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_MOTION, self.on_motion)
        self.Bind(wx.EVT_LEAVE_WINDOW, lambda e: self._set_hover(-1))
        self.Bind(wx.EVT_LEFT_DOWN, self.on_click)
        self.Bind(wx.EVT_KEY_DOWN, self.on_key)
        self.Bind(wx.EVT_SIZE, lambda e: (self.Refresh(), e.Skip()))
        self._layout()

    # --- geometry
    def _layout(self):
        """Row rectangles, top to bottom, with section headers between groups."""
        self.rows, self.heads = [], []
        y, last = 10, None
        for i, (sec, _l, _f, _k) in enumerate(self.items):
            if sec != last:
                if last is not None:
                    y += 8
                if not self.collapsed:
                    self.heads.append((sec, y))
                    y += self.HEAD - 8
                else:
                    self.heads.append((sec, y))      # drawn as a thin line
                    y += 6
                last = sec
            self.rows.append(wx.Rect(6, y, 0, self.ROW))
            y += self.ROW + 2
        self.toggle_rect = wx.Rect(6, 0, 0, 28)

    def _width(self):
        return self.GetClientSize()[0]

    def row_at(self, pt):
        w = self._width()
        for i, r in enumerate(self.rows):
            if r.y <= pt.y < r.y + r.height and 0 <= pt.x < w:
                return i
        return -1

    def _on_toggle(self, pt):
        h = self.GetClientSize()[1]
        return pt.y >= h - 36

    # --- state
    def set_selection(self, i):
        if i != self.sel:
            self.sel = i
            self.Refresh()

    def set_badges(self, badges):
        if badges != self.badges:
            self.badges = dict(badges)
            self.Refresh()
            self._tooltips()

    def toggle(self):
        self.collapsed = not self.collapsed
        self.SetMinSize((self.NARROW if self.collapsed else self.WIDE, -1))
        self._layout()
        self.GetParent().Layout()
        self.Refresh()
        cfg = wx.Config("IPC_STE_Assistant")
        cfg.WriteBool("nav_collapsed", self.collapsed)
        cfg.Flush()

    def _set_hover(self, i):
        if i != self.hover:
            self.hover = i
            self.Refresh()
            self._tooltips()

    def _tooltips(self):
        if 0 <= self.hover < len(self.items):
            _s, label, _f, key = self.items[self.hover]
            b = self.badges.get(self.hover)
            extra = {"count": f": {b[1]}", "check": ": done", "dot": ": to do", "text": f": {b[1]}"}.get(b[0], "") \
                if b else ""
            self.SetToolTip(f"{label}{extra}    {key}")
        else:
            self.SetToolTip("Show or hide the labels   Ctrl+B" if self.hover == -2 else "")

    # --- events
    def on_motion(self, evt):
        pt = evt.GetPosition()
        self._set_hover(-2 if self._on_toggle(pt) else self.row_at(pt))
        self.SetCursor(wx.Cursor(wx.CURSOR_HAND if self.hover != -1 else wx.CURSOR_ARROW))

    def on_click(self, evt):
        self.SetFocus()
        pt = evt.GetPosition()
        if self._on_toggle(pt):
            self.toggle()
            return
        i = self.row_at(pt)
        if i >= 0:
            self.set_selection(i)
            self.on_select(i)

    def on_key(self, evt):
        k = evt.GetKeyCode()
        if k in (wx.WXK_DOWN, wx.WXK_UP):
            i = max(0, min(len(self.items) - 1, self.sel + (1 if k == wx.WXK_DOWN else -1)))
            self.set_selection(i)
            self.on_select(i)
        else:
            evt.Skip()

    # --- drawing
    def on_paint(self, _evt):
        dc = wx.AutoBufferedPaintDC(self)
        win = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)
        txt = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT)
        dark = is_dark()
        bg = _mix(win, txt, 0.06 if not dark else 0.10)
        grey = _mix(bg, txt, 0.50)
        dc.SetBackground(wx.Brush(bg))
        dc.Clear()
        gc = wx.GraphicsContext.Create(dc)
        w, h = self.GetClientSize()
        base = self.GetFont()
        f_item = wx.Font(base.GetPointSize() + 1, base.GetFamily(), base.GetStyle(), wx.FONTWEIGHT_NORMAL)
        f_sel = wx.Font(base.GetPointSize() + 1, base.GetFamily(), base.GetStyle(), wx.FONTWEIGHT_BOLD)
        f_head = wx.Font(base.GetPointSize() - 1, base.GetFamily(), base.GetStyle(), wx.FONTWEIGHT_BOLD)
        f_badge = wx.Font(base.GetPointSize() - 1, base.GetFamily(), base.GetStyle(), wx.FONTWEIGHT_BOLD)
        # border on the right
        gc.SetPen(wx.Pen(_mix(bg, txt, 0.12), 1))
        gc.StrokeLine(w - 1, 0, w - 1, h)
        for sec, y in self.heads:
            if self.collapsed:
                if y > 12:
                    gc.SetPen(wx.Pen(_mix(bg, txt, 0.15), 1))
                    gc.StrokeLine(14, y + 1, w - 14, y + 1)
            else:
                gc.SetFont(f_head, grey)
                gc.DrawText(sec.upper(), 16, y + 4)
        for i, (sec, label, _f, _k) in enumerate(self.items):
            r = self.rows[i]
            x0, x1 = r.x, w - 7
            if i == self.sel:
                gc.SetBrush(wx.Brush(_mix(bg, ACCENT, 0.16 if not dark else 0.30)))
                gc.SetPen(wx.TRANSPARENT_PEN)
                gc.DrawRoundedRectangle(x0, r.y, x1 - x0, r.height, 7)
                gc.SetBrush(wx.Brush(ACCENT))
                gc.DrawRoundedRectangle(x0, r.y + 7, 3, r.height - 14, 1.5)
            elif i == self.hover:
                gc.SetBrush(wx.Brush(_mix(bg, txt, 0.07)))
                gc.SetPen(wx.TRANSPARENT_PEN)
                gc.DrawRoundedRectangle(x0, r.y, x1 - x0, r.height, 7)
            bmp = self.bmps[i]
            ix = (w - 18) // 2 if self.collapsed else x0 + 12
            if bmp.IsOk():
                gc.DrawBitmap(bmp, ix, r.y + (r.height - 18) / 2, 18, 18)
            else:                                   # Overview: a small house of squares
                gc.SetBrush(wx.Brush(ACCENT if i == self.sel else grey))
                gc.SetPen(wx.TRANSPARENT_PEN)
                for dx, dy in ((0, 0), (10, 0), (0, 10), (10, 10)):
                    gc.DrawRoundedRectangle(ix + dx, r.y + 8 + dy, 8, 8, 2)
            b = self.badges.get(i)
            if not self.collapsed:
                gc.SetFont(f_sel if i == self.sel else f_item, txt)
                gc.DrawText(label, x0 + 40, r.y + (r.height - gc.GetTextExtent(label)[1]) / 2)
                if b:
                    self._badge(gc, b, x1 - 8, r.y + r.height / 2, f_badge, right=True)
            elif b:
                self._badge(gc, b, ix + 22, r.y + 9, f_badge, right=True, small=True)
        # collapse toggle at the bottom
        gc.SetPen(wx.Pen(_mix(bg, txt, 0.12), 1))
        gc.StrokeLine(0, h - 37, w, h - 37)
        if self.hover == -2:
            gc.SetBrush(wx.Brush(_mix(bg, txt, 0.07)))
            gc.SetPen(wx.TRANSPARENT_PEN)
            gc.DrawRectangle(0, h - 36, w - 1, 36)
        gc.SetPen(wx.Pen(grey, 2))
        cx, cy = (w // 2 if self.collapsed else 24), h - 18
        d = 1 if self.collapsed else -1                 # chevron points to where the bar will go
        for off in (0, 6):
            gc.StrokeLine(cx - 3 * d + off * d, cy - 5, cx + 2 * d + off * d, cy)
            gc.StrokeLine(cx + 2 * d + off * d, cy, cx - 3 * d + off * d, cy + 5)
        if not self.collapsed:
            gc.SetFont(f_head, grey)
            gc.DrawText("Hide labels", 44, cy - gc.GetTextExtent("Hide")[1] / 2)

    def _badge(self, gc, b, x_right, cy, font, right=True, small=False):
        kind, text, colour = b
        if kind == "dot":
            rr = 4 if not small else 3.5
            gc.SetBrush(wx.Brush(colour))
            gc.SetPen(wx.TRANSPARENT_PEN)
            gc.DrawEllipse(x_right - 2 * rr, cy - rr, 2 * rr, 2 * rr)
            return
        if kind == "check":
            s = 16 if not small else 13
            gc.SetBrush(wx.Brush(_mix(colour, wx.WHITE, 0.82) if not is_dark() else _mix(colour, wx.BLACK, 0.55)))
            gc.SetPen(wx.TRANSPARENT_PEN)
            gc.DrawEllipse(x_right - s, cy - s / 2, s, s)
            gc.SetPen(wx.Pen(colour, 2))
            x, y = x_right - s, cy - s / 2
            gc.StrokeLine(x + s * 0.28, y + s * 0.52, x + s * 0.44, y + s * 0.68)
            gc.StrokeLine(x + s * 0.44, y + s * 0.68, x + s * 0.74, y + s * 0.34)
            return
        gc.SetFont(font, wx.WHITE if kind == "count" else colour)
        tw, th = gc.GetTextExtent(text)
        pw, ph = max(tw + 12, 20 if not small else 16), th + (4 if not small else 2)
        if kind == "count":
            gc.SetBrush(wx.Brush(colour))
            gc.SetPen(wx.TRANSPARENT_PEN)
        else:
            gc.SetBrush(wx.TRANSPARENT_BRUSH)
            gc.SetPen(wx.Pen(colour, 1))
        gc.DrawRoundedRectangle(x_right - pw, cy - ph / 2, pw, ph, ph / 2)
        gc.DrawText(text, x_right - pw + (pw - tw) / 2, cy - th / 2)
