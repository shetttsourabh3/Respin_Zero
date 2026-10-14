"""Load fabricator capability profiles (bundled list + optional project overrides)."""
import json
import os

BUNDLED = os.path.join(os.path.dirname(__file__), "manufacturers.json")
PROJECT_FILE = "ipc_ste_manufacturers.json"
CUSTOM = "Custom (enter values)"


def load(project_dir=None):
    """Return {name: profile}. A project file with the same id replaces the bundled entry."""
    profiles = {}
    paths = [BUNDLED]
    if project_dir:
        paths.append(os.path.join(project_dir, PROJECT_FILE))
    for p in paths:
        if not os.path.isfile(p):
            continue
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        verified = data.get("verified", "")
        for m in data.get("manufacturers", []):
            m.setdefault("verified", verified)
            for k in [k for k, v in profiles.items() if v.get("id") == m.get("id")]:
                del profiles[k]
            profiles[f'{m["name"]} - {m.get("country", "")}'] = m
    return dict(sorted(profiles.items(), key=lambda kv: (kv[1].get("country", ""), kv[0])))


def check_fit(profile, req):
    """Return STE warnings where the design needs more than the fabricator offers."""
    w = []
    if not profile:
        return w
    if req.layers > profile.get("max_layers", 99):
        w.append(f"{profile['name']} makes a maximum of {profile['max_layers']} layers. "
                 f"The design has {req.layers}. Select a different fabricator.")
    lo, hi = profile.get("thickness_mm", [0, 99])
    if not lo <= req.board_thickness_mm <= hi:
        w.append(f"{profile['name']} makes boards from {lo} to {hi} mm thick. Change the board thickness.")
    if profile.get("outer_oz") and req.outer_copper_oz not in profile["outer_oz"]:
        w.append(f"{profile['name']} does not list {req.outer_copper_oz} oz outer copper. "
                 f"Available: {profile['outer_oz']} oz.")
    if req.layers > 2 and profile.get("inner_oz") and req.inner_copper_oz not in profile["inner_oz"]:
        w.append(f"{profile['name']} does not list {req.inner_copper_oz} oz inner copper. "
                 f"Available: {profile['inner_oz']} oz.")
    if profile.get("notes"):
        w.append(f"Fabricator note: {profile['notes']}")
    w.append(f"Capability data from {profile.get('source', 'unknown')} (verified {profile.get('verified', '?')}). "
             "Make sure that the values are current before you order.")
    return w
