"""RulesPanel."""
from .common import *  # noqa: F401,F403


class RulesPanel(wx.Panel):
    FAB_FIELDS = [("fab_min_track_mm", "Track"), ("fab_min_space_mm", "Space"), ("fab_min_drill_mm", "Drill"),
                  ("fab_min_annular_mm", "Annular ring"), ("fab_hole_to_hole_mm", "Hole to hole"),
                  ("fab_edge_mm", "Copper to edge"), ("fab_mask_dam_mm", "Solder mask dam"),
                  ("fab_silk_line_mm", "Silk line width"), ("fab_silk_height_mm", "Silk text height")]

    def __init__(self, parent, frame):
        super().__init__(parent)
        self.frame = frame
        self.f, self.sections = {}, []
        split = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE | wx.SP_3DSASH)
        self.form = form = scrolled.ScrolledPanel(split)
        fs = wx.BoxSizer(wx.VERTICAL)

        # --- Start
        sec = self._section(form, fs, "Start", 0)
        self.f["preset"] = self._row(form, sec, "Preset", wx.Choice(form, choices=["(none)"] + list(frame.presets)),
                                     "A preset fills the answers. You can change any answer after.")
        self.f["preset"].Bind(wx.EVT_CHOICE, self.on_preset)
        self.preset_info = muted(wx.StaticText(form, label=""))
        sec.Add(self.preset_info, 0, wx.LEFT | wx.BOTTOM, 6)

        # --- Product
        sec = self._section(form, fs, "Product", 0)
        self.f["ipc_class"] = self._row(form, sec, "IPC class", wx.Choice(form, choices=[
            "Class 1 - general (toys, hobby)", "Class 2 - dedicated service (most products)",
            "Class 3 - high reliability (life support)"]),
            "IPC-6011. The class sets annular ring, edge margins and inspection criteria.")
        self.f["medical"] = self._row(form, sec, "", wx.CheckBox(form, label="This is a medical device"))

        # --- Board
        sec = self._section(form, fs, "Board", 0)
        self.f["layers"] = self._row(form, sec, "Copper layers", NumField(form, self, 1, True))
        self.f["board_thickness_mm"] = self._row(form, sec, "Thickness (mm)", NumField(form, self, 0.2),
                                                 "The plugin scales the stackup to this value.")
        self.f["max_voltage_v"] = self._row(form, sec, "Highest voltage, not mains (V)", NumField(form, self, 0),
                                            "For example 3.3, 5, 12 or 24. Give mains nets in the Nets tab.")

        # --- Fabricator
        sec = self._section(form, fs, "Fabricator", 0)
        self.f["manufacturer"] = self._row(form, sec, "Fabricator",
                                           wx.Choice(form, choices=[M.CUSTOM] + list(frame.profiles)))
        self.f["manufacturer"].Bind(wx.EVT_CHOICE, self.on_fab)
        self.fab_info = muted(wx.StaticText(form, label=""))
        sec.Add(self.fab_info, 0, wx.LEFT | wx.BOTTOM, 6)

        # --- Copper & power (intermediate)
        sec = self._section(form, fs, "Copper and current", 1)
        self.f["outer_copper_oz"] = self._row(form, sec, "Outer copper (oz)", NumField(form, self, 0.25))
        self.f["inner_copper_oz"] = self._row(form, sec, "Inner copper (oz)", NumField(form, self, 0.25))
        self.f["temp_rise_c"] = self._row(form, sec, "Temperature rise limit (C)", NumField(form, self, 1),
                                          "Used for track width and the Power & Thermal check. 10 C is usual.")
        self.f["solder_mask_coated"] = self._row(form, sec, "", wx.CheckBox(form, label="Outer layers have solder mask (IPC-2221 B4)"))
        self.f["density"] = self._row(form, sec, "IPC-7351 density", wx.Choice(form, choices=[
            "A - most material", "B - nominal", "C - least material (dense)"]))

        # --- Net classes (intermediate)
        sec = self._section(form, fs, "Net classes (optional)", 1)
        self.f["hv_netclass"] = self._row(form, sec, "High-voltage class name", wx.TextCtrl(form, size=(110, -1)),
                                          "Leave blank if you give high-voltage nets in the Nets tab.")
        self.f["hv_voltage_v"] = self._row(form, sec, "Its peak voltage (V)", NumField(form, self, 0))
        self.f["power_nets"] = self._row(form, sec, "Power classes", wx.TextCtrl(form, size=(220, -1)),
                                         "Name:Amps:outer|inner, separated by commas. Example: PWR:2:outer")

        # --- Fabricator limits (intermediate; editable for Expert or Custom)
        sec = self._section(form, fs, "Fabricator limits (mm)", 1)
        grid = wx.FlexGridSizer(0, 4, 6, 10)
        for k, label in self.FAB_FIELDS:
            self.f[k] = NumField(form, self, 0)
            grid.Add(wx.StaticText(form, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(self.f[k], 0)
        sec.Add(grid, 0, wx.ALL, 6)
        self.fab_lock = muted(wx.StaticText(form, label=""))
        sec.Add(self.fab_lock, 0, wx.LEFT | wx.BOTTOM, 6)

        form.SetSizer(fs)
        form.SetupScrolling(scroll_x=False)

        # --- results side
        res = wx.Panel(split)
        rs = wx.BoxSizer(wx.VERTICAL)
        rs.Add(bold(wx.StaticText(res, label="Generated rules")), 0, wx.ALL, 8)
        self.result_hint = muted(wx.StaticText(res, label="Click Apply rules to see the values and the reason for each one."))
        rs.Add(self.result_hint, 0, wx.LEFT | wx.RIGHT, 8)
        self.lst = wx.ListCtrl(res, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for i, (c, w) in enumerate([("Rule", 190), ("Value", 70), ("Why", 420)]):
            self.lst.InsertColumn(i, c, width=w)
        self.lst.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_rule_select)
        self.lst.Bind(wx.EVT_SIZE, self._fit_why)
        rs.Add(self.lst, 3, wx.EXPAND | wx.ALL, 8)
        rs.Add(bold(wx.StaticText(res, label="Notes")), 0, wx.LEFT, 8)
        self.notes = wx.TextCtrl(res, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        rs.Add(self.notes, 2, wx.EXPAND | wx.ALL, 8)
        res.SetSizer(rs)
        split.SplitVertically(form, res, 470)
        split.SetMinimumPaneSize(320)

        # --- bottom bar
        bar = wx.BoxSizer(wx.HORIZONTAL)
        self.apply_btn = primary_button(self, "Apply rules")
        self.apply_btn.Bind(wx.EVT_BUTTON, self.on_apply)
        reset = wx.Button(self, label="Reset to saved")
        reset.Bind(wx.EVT_BUTTON, lambda e: self.set_from(self.frame.req))
        self.last = muted(wx.StaticText(self, label=""))
        bar.Add(self.apply_btn, 0, wx.RIGHT, 8)
        bar.Add(reset, 0, wx.RIGHT, 16)
        bar.Add(self.last, 0, wx.ALIGN_CENTER_VERTICAL)
        s = wx.BoxSizer(wx.VERTICAL)
        s.Add(split, 1, wx.EXPAND | wx.ALL, 6)
        s.Add(bar, 0, wx.ALL, 10)
        self.SetSizer(s)
        self.set_from(frame.req)

    # --- layout helpers
    def _section(self, parent, sizer, title, level):
        box = wx.StaticBoxSizer(wx.VERTICAL, parent, title)
        bold(box.GetStaticBox())
        sizer.Add(box, 0, wx.EXPAND | wx.ALL, 6)
        self.sections.append((box, level))
        return box

    def _row(self, parent, sec, label, ctrl, tip=None):
        row = wx.BoxSizer(wx.HORIZONTAL)
        lab = wx.StaticText(parent, label=label, size=(200, -1))
        row.Add(lab, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        row.Add(ctrl, 1 if isinstance(ctrl, wx.Choice) else 0, wx.EXPAND)
        if tip:
            ctrl.SetToolTip(tip)
            lab.SetToolTip(tip)
        sec.Add(row, 0, wx.EXPAND | wx.ALL, 4)
        return ctrl

    # --- values
    def set_from(self, r):
        f = self.f
        f["preset"].SetSelection(f["preset"].FindString(r.preset) if r.preset in self.frame.presets else 0)
        self.preset_info.SetLabel(self.frame.presets.get(r.preset, {}).get("description", ""))
        f["ipc_class"].SetSelection(r.ipc_class - 1)
        f["medical"].SetValue(r.medical)
        f["solder_mask_coated"].SetValue(r.solder_mask_coated)
        f["density"].SetSelection("ABC".index(r.density) if r.density in "ABC" else 1)
        names = [M.CUSTOM] + list(self.frame.profiles)
        f["manufacturer"].SetSelection(names.index(r.manufacturer) if r.manufacturer in names else 0)
        for k in ("layers", "board_thickness_mm", "max_voltage_v", "outer_copper_oz", "inner_copper_oz",
                  "temp_rise_c", "hv_voltage_v") + tuple(k for k, _ in self.FAB_FIELDS):
            f[k].ChangeValue(f"{getattr(r, k):g}")
        f["hv_netclass"].SetValue(r.hv_netclass if r.hv_voltage_v else "")
        f["power_nets"].SetValue(", ".join(f"{n.name}:{n.current_a:g}:{n.layer}" for n in r.power_nets))
        self.set_level(r.level)

    def result(self):
        f = self.f
        r = R.Requirements.from_json(self.frame.req.to_json())
        r.preset = f["preset"].GetStringSelection() if f["preset"].GetSelection() > 0 else ""
        r.ipc_class = f["ipc_class"].GetSelection() + 1
        r.medical = f["medical"].GetValue()
        r.solder_mask_coated = f["solder_mask_coated"].GetValue()
        r.density = "ABC"[f["density"].GetSelection()]
        r.manufacturer = "" if self._profile() is None else f["manufacturer"].GetStringSelection()
        for k in ("layers", "board_thickness_mm", "max_voltage_v", "outer_copper_oz", "inner_copper_oz",
                  "temp_rise_c", "hv_voltage_v") + tuple(k for k, _ in self.FAB_FIELDS):
            setattr(r, k, f[k].value())
        hv = f["hv_netclass"].GetValue().strip()
        r.hv_netclass, r.hv_voltage_v = (hv, r.hv_voltage_v) if hv else ("HV", 0.0)
        r.power_nets = []
        for part in f["power_nets"].GetValue().split(","):
            bits = [b.strip() for b in part.split(":") if b.strip()]
            if len(bits) >= 2:
                r.power_nets.append(R.PowerNet(bits[0], float(bits[1]), bits[2] if len(bits) > 2 else "outer"))
        return r

    def _profile(self):
        return self.frame.profiles.get(self.f["manufacturer"].GetStringSelection())

    def _level(self):
        return R.LEVELS.index(self.frame.req.level) if self.frame.req.level in R.LEVELS else 0

    # --- behaviour
    def set_level(self, level):
        lvl = R.LEVELS.index(level) if level in R.LEVELS else 0
        for box, need in self.sections:
            box.ShowItems(lvl >= need)
            box.GetStaticBox().Show(lvl >= need)
        self._show_fab_info()
        self.form.Layout()
        self.form.SetupScrolling(scroll_x=False, scrollToTop=False)
        self.Layout()

    def _show_fab_info(self):
        prof = self._profile()
        if prof:
            lo, hi = prof.get("thickness_mm", ["?", "?"])
            self.fab_info.SetLabel(f"{prof.get('country', '')}. Up to {prof.get('max_layers', '?')} layers, "
                                   f"{lo}-{hi} mm, outer copper {prof.get('outer_oz')} oz. "
                                   f"Data checked {prof.get('verified', '?')}.")
        else:
            self.fab_info.SetLabel("No fabricator selected: the plugin uses safe general values."
                                   if self._level() == 0 else "Type the values from your fabricator's capability sheet.")
        self.fab_info.Wrap(400)
        expert = self._level() == 2
        editable = prof is None or expert
        for k, _ in self.FAB_FIELDS:
            self.f[k].Enable(editable)
        self.fab_lock.SetLabel("" if editable else "Values come from the fabricator profile. Expert level can change them.")
        self.on_validity()

    def on_fab(self, _evt):
        prof = self._profile()
        if prof:
            tmp = R.Requirements(layers=int(self.f["layers"].value()) if self.f["layers"].valid() else 2)
            tmp.apply_profile(prof)
            for k, _ in self.FAB_FIELDS:
                self.f[k].ChangeValue(f"{getattr(tmp, k):g}")
        self._show_fab_info()
        self.form.Layout()

    def on_preset(self, _evt):
        pre = self.frame.presets.get(self.f["preset"].GetStringSelection())
        if not pre:
            self.preset_info.SetLabel("")
            return
        try:
            r = self.result()
        except ValueError:
            r = R.Requirements.from_json(self.frame.req.to_json())
        level, fab = self.frame.req.level, r.manufacturer
        r.apply_preset(pre)
        r.level, r.manufacturer = level, fab
        self.set_from(r)
        self.on_fab(None)
        self.preset_info.SetLabel(pre.get("description", ""))
        self.preset_info.Wrap(400)
        self.form.Layout()

    def on_validity(self):
        bad = [k for k, c in self.f.items() if isinstance(c, NumField) and c.IsShown() and not c.valid()]
        self.apply_btn.Enable(not bad)
        self.apply_btn.SetToolTip("Correct the fields in red first." if bad else "Write the rules, constraints and stackup.")

    def _fit_why(self, evt):
        w = self.lst.GetClientSize()[0] - self.lst.GetColumnWidth(0) - self.lst.GetColumnWidth(1) - 4
        if w > 120:
            self.lst.SetColumnWidth(2, w)
        evt.Skip()

    def on_rule_select(self, _evt):
        i = self.lst.GetFirstSelected()
        if i >= 0:
            self.frame.status(f"{self.lst.GetItemText(i, 0)}: {self.lst.GetItemText(i, 2)}")

    def on_apply(self, _evt):
        try:
            req = self.result()
        except ValueError:
            self.frame.info("A field has a value that is not a number. Correct the fields in red.", wx.ICON_ERROR)
            return
        req.level = self.frame.req.level
        with wx.BusyCursor():
            res = core.apply_rules(self.frame.board, req, self.frame.profiles, self.frame.paths,
                                   lambda text: wx.MessageBox(text, "Respin Zero - Stackup",
                                                              wx.YES_NO | wx.ICON_QUESTION, self) == wx.YES)
        self.frame.req = req
        self.show_result(res)
        self.frame.overview.refresh()
        if res.revert_needed:
            self.frame.info("The board file has the new stackup. Use File > Revert in the PCB Editor now "
                            "(do not save first).", wx.ICON_WARNING)
        else:
            self.frame.info(f"Rules applied: {len(res.rows)} rules. Save the board to keep the constraints.",
                            wx.ICON_INFORMATION)

    def show_result(self, res):
        self.lst.DeleteAllItems()
        for i, (name, val, why) in enumerate(res.rows):
            idx = self.lst.InsertItem(i, name)
            self.lst.SetItem(idx, 1, f"{val:g} mm")
            self.lst.SetItem(idx, 2, why)
        self.lst.SetToolTip("Select a rule to read the full reason in the status bar.")
        self.result_hint.SetLabel(f"{len(res.rows)} rules written to {os.path.basename(self.frame.paths['dru'])}. "
                                  + ("Your own rules were kept." if res.kept_user_rules
                                     else "Add your own rules below the marker line; the plugin keeps them."))
        lines = []
        if res.stack_lines:
            lines += ["Stackup:"] + [f"  {s}" for s in res.stack_lines] + [""]
        lines += [f"- {n}" for n in res.notes] or ["- No notes."]
        if res.constraints_skipped:
            lines.append("- Not set in Board Setup (KiCad API): " + ", ".join(res.constraints_skipped))
        self.notes.SetValue("\n".join(lines))
        self.last.SetLabel(f"Last applied {time.strftime('%H:%M')}")
