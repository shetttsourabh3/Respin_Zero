"""Accepted (waived) findings, stored per project in ipc_ste_waivers.json."""
import datetime
import getpass
import json
import os

FILE = "ipc_ste_waivers.json"


class Waivers:
    def __init__(self, project_dir):
        self.path = os.path.join(project_dir, FILE) if project_dir else None
        self.data = {}
        if self.path and os.path.isfile(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    self.data = json.load(f).get("waivers", {})
            except (OSError, ValueError):
                self.data = {}

    def add(self, finding, reason, by=None):
        try:
            user = by or getpass.getuser()
        except Exception:
            user = "unknown"
        self.data[finding.key] = {"type": finding.type, "source": finding.source,
                                  "location": finding.location, "reason": reason.strip(),
                                  "by": user, "date": datetime.date.today().isoformat()}

    def remove(self, finding):
        self.data.pop(finding.key, None)

    def get(self, finding):
        return self.data.get(finding.key)

    def split(self, findings):
        """Return (open, waived[(finding, waiver)])."""
        open_, waived = [], []
        for f in findings:
            w = self.get(f)
            (waived.append((f, w)) if w else open_.append(f))
        return open_, waived

    def save(self):
        if not self.path:
            return
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "waivers": self.data}, f, indent=2)
