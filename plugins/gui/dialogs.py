"""SkillsDialog."""
from .common import *  # noqa: F401,F403


class SkillsDialog(wx.Dialog):
    """Turn review skills on or off, add files, open the folders."""

    def __init__(self, parent, frame):
        super().__init__(parent, title="AI review skills", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.frame = frame
        s = wx.BoxSizer(wx.VERTICAL)
        t = muted(wx.StaticText(self, label=(
            "Skills are Markdown files with your own review rules (for example company layout rules or a "
            "medical checklist). The AI follows the ticked skills. Project skills are in "
            f"'{SK.PROJECT_DIR}' next to the board; personal skills are in {SK.PERSONAL}.")))
        t.Wrap(640)
        s.Add(t, 0, wx.ALL, 10)
        self.lst = wx.CheckListBox(self, size=(640, 220))
        s.Add(self.lst, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        self.info = muted(wx.StaticText(self, label=""))
        s.Add(self.info, 0, wx.ALL, 10)
        row = wx.BoxSizer(wx.HORIZONTAL)
        for label, fn in [("Add skill file...", self.on_add), ("New from template", self.on_new),
                          ("Open project folder", lambda e: self._open(False)),
                          ("Open personal folder", lambda e: self._open(True))]:
            b = wx.Button(self, label=label)
            b.Bind(wx.EVT_BUTTON, fn)
            row.Add(b, 0, wx.RIGHT, 6)
        s.Add(row, 0, wx.LEFT | wx.RIGHT, 10)
        s.Add(self.CreateButtonSizer(wx.OK | wx.CANCEL), 0, wx.EXPAND | wx.ALL, 10)
        self.SetSizerAndFit(s)
        self.lst.Bind(wx.EVT_LISTBOX, self._show)
        self._off = set(frame.req.ai_skills_off)
        self._fill()

    def _fill(self):
        self.skills = SK.discover(self.frame.paths["dir"])
        self.lst.Set([f"{k.name}  -  {k.description}   [{k.applies_to}, {k.origin}]" for k in self.skills])
        for i, k in enumerate(self.skills):
            self.lst.Check(i, k.name not in self._off)
        self.info.SetLabel(f"{len(self.skills)} skill(s) found. Select one to see its file." if self.skills else
                           "No skills yet. Add a file or start from the template.")

    def _show(self, _evt):
        i = self.lst.GetSelection()
        if 0 <= i < len(self.skills):
            k = self.skills[i]
            self.info.SetLabel(f"{k.path}  ({len(k.text)} characters)")

    def disabled(self):
        names = {k.name for k in self.skills}
        off = {k.name for i, k in enumerate(self.skills) if not self.lst.IsChecked(i)}
        return sorted(off | (self._off - names))

    def on_add(self, _evt):
        with wx.FileDialog(self, "Choose a skill file", wildcard="Markdown (*.md)|*.md",
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE) as fd:
            if fd.ShowModal() != wx.ID_OK:
                return
            personal = wx.MessageBox("Use these skills in all your projects?\n\nYes = personal folder (all projects)\n"
                                     "No = this project only", "Add skills", wx.YES_NO | wx.ICON_QUESTION, self) == wx.YES
            for p in fd.GetPaths():
                SK.add_file(p, self.frame.paths["dir"], personal)
        self._off = set(self.disabled())
        self._fill()

    def on_new(self, _evt):
        path = SK.create_template(self.frame.paths["dir"])
        open_file(path)
        self._off = set(self.disabled())
        self._fill()

    def _open(self, personal):
        folder = SK.PERSONAL if personal else os.path.join(self.frame.paths["dir"], SK.PROJECT_DIR)
        os.makedirs(folder, exist_ok=True)
        wx.LaunchDefaultApplication(folder)
