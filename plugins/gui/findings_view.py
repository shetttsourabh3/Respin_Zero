"""Building blocks for the review pages: filter chips, readable finding titles, severity icons and the detail card."""
import html
import re

import wx.html

from .common import *  # noqa: F401,F403

SHORT = {C.BLOCK: "Blocking", C.RISK: "Risk", C.COSMETIC: "Cosmetic"}
CHIP_LABEL = {C.BLOCK: "Blocking", C.RISK: "Risks", C.COSMETIC: "Cosmetic", "Waived": "Waived"}
SHORT_SOURCE = {"SCH": "Rule", "AI": "AI", "ERC": "ERC", "DRC": "DRC", "PWR": "Power"}
SOURCE = {"SCH": "Rule check", "AI": "AI review", "ERC": "KiCad ERC", "DRC": "KiCad DRC", "PWR": "Power check"}
ACRONYMS = {"usb": "USB", "usbc": "USB-C", "cc": "CC", "i2c": "I2C", "esd": "ESD", "led": "LED", "ldo": "LDO",
            "erc": "ERC", "drc": "DRC", "pth": "PTH", "npth": "NPTH", "smd": "SMD", "vdd": "VDD", "gnd": "GND",
            "rf": "RF", "pcb": "PCB", "swd": "SWD", "jtag": "JTAG", "mcu": "MCU", "ic": "IC", "dnp": "DNP",
            "hv": "HV", "ipc": "IPC", "rc": "RC", "pwr": "Power"}
TITLES = {
    "crystal_wrong_frequency": "Wrong crystal frequency", "led_no_resistor": "LED without a current resistor",
    "strap_pin_wrong": "Strapping pin in the wrong state", "usbc_cc_shared": "USB-C CC1 and CC2 joined",
    "usbc_cc_missing": "USB-C CC resistors missing", "usbc_cc_value": "Wrong USB-C CC resistor value",
    "enable_no_delay": "Enable pin has no RC delay", "i2c_no_pullup": "I2C line without a pull-up",
    "missing_capacitor": "Missing decoupling capacitor", "no_decoupling": "No decoupling capacitor",
    "few_decoupling": "Too little decoupling", "strap_pin_capacitor": "Capacitor on a strapping pin",
    "usb_no_esd": "USB lines without ESD protection", "boot_pin_floating": "Boot pin left floating",
    "boot_pin_high": "Boot pin pulled high", "enable_floating": "Enable pin left floating",
    "crystal_no_load_caps": "Crystal without load capacitors", "led_current_high": "LED current too high",
    "pin_not_grounded": "Pin must be grounded", "pin_floating": "Pin left floating",
    "series_resistor": "Series resistor suggested", "unconnected_items": "Unconnected items",
    "clearance": "Clearance too small", "courtyards_overlap": "Courtyards overlap",
    "silk_over_copper": "Silkscreen over copper", "power_pin_not_driven": "Power input not driven",
    "shorting_items": "Short between nets", "tracks_crossing": "Tracks cross",
}


def humanize(slug):
    words = [w for w in slug.split("_") if w]
    out = [ACRONYMS.get(w.lower(), w) for w in words]
    if out and out[0] == out[0].lower():
        out[0] = out[0].capitalize()
    return " ".join(out)


def title_of(f):
    if f.source == "AI":
        t = f.description.split(": ", 1)[0]
        return t[:90]
    return TITLES.get(f.type) or humanize(f.type)


def detail_of(f):
    """The description without the AI title prefix."""
    if f.source == "AI" and ": " in f.description:
        return f.description.split(": ", 1)[1]
    return f.description


def where_of(f):
    loc = re.sub(r"\s+at \([-\d.]+, [-\d.]+\)$", "", f.location or "")
    loc = (f.sheet.strip("/") + ": " if f.sheet and f.sheet != "/" else "") + loc
    extra = len([i for i in f.items if i.get("description")]) - 1
    return loc + (f"  (+{extra} more)" if extra > 0 else "")


def part_of(f):
    for it in f.items:
        if it.get("ref"):
            return it["ref"]
    m = re.search(r"\b([A-Z]{1,3}\d+)\b", f.location or "")
    return m.group(1) if m else "Board"


def confidence_of(f):
    m = re.search(r"confidence (\w+)", f.why or "")
    return m.group(1) if m else ""


# ------------------------------------------------------------------------------------------- severity icons
def dot_bitmap(colour, size=14, ring=False):
    bmp = wx.Bitmap(size, size, 32)
    mdc = wx.MemoryDC(bmp)
    mdc.SetBackground(wx.Brush(wx.Colour(0, 0, 0, 0)))
    mdc.Clear()
    gc = wx.GraphicsContext.Create(mdc)
    if ring:
        gc.SetPen(wx.Pen(colour, 2))
        gc.SetBrush(wx.TRANSPARENT_BRUSH)
    else:
        gc.SetPen(wx.TRANSPARENT_PEN)
        gc.SetBrush(wx.Brush(colour))
    gc.DrawEllipse(2, 2, size - 4, size - 4)
    del gc
    mdc.SelectObject(wx.NullBitmap)
    try:
        bmp.UseAlpha()
    except Exception:
        pass
    return bmp


# ------------------------------------------------------------------------------------------- filter chips
class Chip(wx.Panel):
    """A rounded toggle chip with a count, like a modern filter: 'Blocking 4'. Same API as a ToggleButton."""

    def __init__(self, parent, key, colour, on_toggle):
        super().__init__(parent)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.key, self.colour, self.on_toggle = key, colour, on_toggle
        self.value, self.count, self.hover = True, 0, False
        self._label = CHIP_LABEL.get(key, key)
        f = self.GetFont()
        f.SetWeight(wx.FONTWEIGHT_BOLD)
        self.SetFont(f)
        self._size()
        self.SetCursor(wx.Cursor(wx.CURSOR_HAND))
        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_LEFT_DOWN, self.on_click)
        self.Bind(wx.EVT_ENTER_WINDOW, lambda e: self._hover(True))
        self.Bind(wx.EVT_LEAVE_WINDOW, lambda e: self._hover(False))
        self.SetToolTip(f"Show or hide the {self._label.lower()} findings")

    def _hover(self, h):
        self.hover = h
        self.Refresh()

    def _size(self):
        w, h = self.GetTextExtent(f"{self._label}  {self.count}")
        self.SetMinSize((w + 40, h + 14))

    # ToggleButton-compatible API (other code calls these)
    def GetValue(self):
        return self.value

    def SetValue(self, v):
        self.value = bool(v)
        self.Refresh()

    def SetLabel(self, text):
        m = re.search(r"(\d+)\s*$", text)
        self.count = int(m.group(1)) if m else 0
        self._size()
        self.GetParent().Layout()
        self.Refresh()

    def on_click(self, _evt):
        self.value = not self.value
        self.Refresh()
        self.on_toggle()

    def on_paint(self, _evt):
        dc = wx.AutoBufferedPaintDC(self)
        bg = self.GetParent().GetBackgroundColour()
        dc.SetBackground(wx.Brush(bg))
        dc.Clear()
        gc = wx.GraphicsContext.Create(dc)
        w, h = self.GetClientSize()
        c = self.colour
        txt = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT)
        if self.value:
            fill = wx.Colour(c.Red(), c.Green(), c.Blue(), 40 if not is_dark() else 70)
            gc.SetBrush(wx.Brush(fill))
            gc.SetPen(wx.Pen(c, 2))
        else:
            gc.SetBrush(wx.Brush(wx.Colour(0, 0, 0, 12 if self.hover else 0)))
            gc.SetPen(wx.Pen(wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT), 1))
        gc.DrawRoundedRectangle(0.75, 0.75, w - 1.5, h - 1.5, (h - 1.5) / 2)
        gc.SetBrush(wx.Brush(c if self.value else wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT)))
        gc.SetPen(wx.TRANSPARENT_PEN)
        gc.DrawEllipse(12, h / 2 - 4, 8, 8)
        gc.SetFont(self.GetFont(), txt if self.value else wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT))
        label = f"{self._label}  {self.count}"
        tw, th = gc.GetTextExtent(label)
        gc.DrawText(label, 26, (h - th) / 2)


# ------------------------------------------------------------------------------------------- detail card
def _hex(c):
    return f"#{c.Red():02x}{c.Green():02x}{c.Blue():02x}"


class DetailCard(wx.html.HtmlWindow):
    """Readable detail of one finding: title, severity, where, what is wrong, how to fix, why it matters."""

    def __init__(self, parent):
        super().__init__(parent, style=wx.html.HW_SCROLLBAR_AUTO | wx.BORDER_THEME)
        self.SetBorders(14)
        try:
            self.SetStandardFonts(self.GetFont().GetPointSize() + 1)
        except Exception:
            pass
        self.Bind(wx.html.EVT_HTML_LINK_CLICKED, self._link)
        self.on_link = None

    def _link(self, evt):
        if self.on_link:
            self.on_link(evt.GetLinkInfo().GetHref())

    def _page(self, body):
        bg = _hex(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW))
        fg = _hex(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT))
        self.SetPage(f'<html><body bgcolor="{bg}" text="{fg}">{body}</body></html>')

    def message(self, title, text, colour=None, action=None):
        grey = _hex(wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT))
        col = _hex(colour) if colour else grey
        btn = f'<p><a href="{action[0]}"><b>{html.escape(action[1])}</b></a></p>' if action else ""
        self._page(f'<br><br><center><font size="+2" color="{col}"><b>{html.escape(title)}</b></font><br><br>'
                   f'<font color="{grey}">{html.escape(text)}</font>{btn}</center>')

    def show(self, f, waiver=None, level="Beginner"):
        grey = _hex(wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT))
        col = _hex(TIER_COLOUR.get(f.tier, wx.Colour(120, 120, 120)))
        e = html.escape
        conf = confidence_of(f)
        meta = [f'<font color="{col}"><b>&#9679; {e(f.tier.upper())}</b></font>', e(SOURCE.get(f.source, f.source))]
        if conf:
            meta.append(f"confidence {e(conf)}")
        if f.section:
            meta.append(f"design document {e(f.section)}")
        rows = [f'<font size="-1" color="{grey}">{" &nbsp;&middot;&nbsp; ".join(meta)}</font>',
                f'<p><font size="+2"><b>{e(title_of(f))}</b></font></p>']
        where = [it.get("description", "") for it in f.items if it.get("description")]
        if where:
            rows.append(f'<p><font color="{grey}"><b>WHERE</b></font><br>' +
                        " &nbsp; ".join(f'<a href="ref:{e(it.get("ref") or "")}"><code>{e(it["description"])}</code></a>'
                                        if it.get("ref") else f"<code>{e(it['description'])}</code>"
                                        for it in f.items[:12] if it.get("description")) +
                        (f' <font color="{grey}">+{len(where) - 12} more</font>' if len(where) > 12 else "") + "</p>")
        rows.append(f'<p><font color="{grey}"><b>WHAT IS WRONG</b></font><br>{e(detail_of(f))}</p>')
        rows.append(f'<table width="100%" cellpadding="8" bgcolor="{_hex(_soft(TIER_COLOUR.get(f.tier, GOOD)))}">'
                    f'<tr><td><b>HOW TO FIX</b><br>{e(f.action)}</td></tr></table>')
        if f.why and (level != "Expert" or f.source == "AI"):
            label = "ABOUT THIS FINDING" if f.source == "AI" else "WHY IT MATTERS"
            rows.append(f'<p><font color="{grey}"><b>{label}</b></font><br>{e(f.why)}</p>')
        if waiver:
            rows.append(f'<p><font color="{grey}"><b>WAIVED</b></font><br>by {e(waiver["by"])} on {e(waiver["date"])}: '
                        f'{e(waiver["reason"])}</p>')
        self._page("".join(rows))


def _soft(c):
    if is_dark():
        return wx.Colour(int(c.Red() * 0.25 + 30), int(c.Green() * 0.25 + 30), int(c.Blue() * 0.25 + 30))
    return wx.Colour(int(255 - (255 - c.Red()) * 0.12), int(255 - (255 - c.Green()) * 0.12),
                     int(255 - (255 - c.Blue()) * 0.12))
