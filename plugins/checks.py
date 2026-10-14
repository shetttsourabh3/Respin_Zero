"""Run ERC and DRC with kicad-cli and turn each violation into tiered STE feedback."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field

BLOCK, RISK, COSMETIC = "Blocks fabrication", "Reliability risk", "Cosmetic"
TIER_ORDER = {BLOCK: 0, RISK: 1, COSMETIC: 2}

# type -> (tier, document section, STE action, why it matters for beginners)
DRC_INFO = {
    "clearance": (BLOCK, "3.2", "Increase the distance between the conductors. Use the IPC-2221 Table 6-1 value for this voltage.",
                  "Conductors that are too close can short during etching or arc in use."),
    "shorting_items": (BLOCK, "4.5", "Separate the items. They connect two different nets.",
                       "Two nets are joined. The circuit will not work."),
    "tracks_crossing": (BLOCK, "4.5", "Reroute one track. Tracks on the same layer must not cross.",
                        "Crossing tracks on one layer are a short circuit."),
    "hole_clearance": (BLOCK, "3.3", "Move the hole or the conductor. Keep the clearance rule value.",
                       "The drill can cut into the copper and cause a short or an open."),
    "track_width": (BLOCK, "3.1", "Make the conductor wider. Calculate the width for the current with IPC-2152.",
                    "A narrow track can overheat, or the fabricator cannot etch it."),
    "connection_width": (BLOCK, "3.1", "Make the copper connection wider.",
                         "A thin neck of copper can break or overheat."),
    "annular_width": (BLOCK, "3.3", "Make the pad or via larger, or make the drill smaller. Keep the IPC-6012 annular ring.",
                      "Drill wander can break out of a small ring and open the connection."),
    "drill_out_of_range": (BLOCK, "3.3", "Change the drill size. Keep the aspect ratio at 8:1 or less.",
                           "The fabricator cannot drill or plate this hole reliably."),
    "via_diameter": (BLOCK, "3.3", "Make the via larger to agree with the rule.",
                     "The via pad is too small for the drill and the ring."),
    "hole_to_hole": (BLOCK, "3.3", "Move the holes apart. Thin web between holes can crack during drilling.",
                     "The laminate between two close holes can crack."),
    "copper_edge_clearance": (BLOCK, "4.1", "Move the copper away from the board edge.",
                              "Routing or V-scoring can expose or cut the copper."),
    "unconnected_items": (BLOCK, "4.5", "Route the connection, or correct the netlist.",
                          "A connection in the schematic does not exist on the board."),
    "invalid_outline": (BLOCK, "4.4", "Close the board outline on the Edge.Cuts layer.",
                        "The fabricator cannot cut a board with an open outline."),
    "solder_mask_bridge": (BLOCK, "4.2", "Increase the solder mask web between the lands to the fabricator minimum.",
                           "Without a mask dam, solder can bridge the pads."),
    "net_conflict": (BLOCK, "4.5", "Update the PCB from the schematic.",
                     "The board and the schematic do not agree."),
    "missing_footprint": (BLOCK, "4.5", "Put the footprint on the board. Update the PCB from the schematic.",
                          "A part in the schematic is not on the board."),
    "extra_footprint": (RISK, "4.5", "Add the component to the schematic, or remove the footprint.",
                        "A part on the board is not in the schematic."),
    "copper_sliver": (BLOCK, "4.2", "Remove the thin copper sliver. Adjust the zone or the track.",
                      "Thin slivers can peel off during etching and cause shorts."),
    "starved_thermal": (RISK, "3.4", "Add thermal relief spokes. Use a minimum of two spokes.",
                        "The pad can have a weak electrical and thermal connection."),
    "courtyards_overlap": (RISK, "3.4", "Move the components. Courtyards must not overlap.",
                           "The assembly machine or the rework tool can hit the other part."),
    "missing_courtyard": (RISK, "3.4", "Add a courtyard to the footprint. Use IPC-7351.",
                          "Without a courtyard, the DRC cannot check part spacing."),
    "malformed_courtyard": (RISK, "3.4", "Correct the courtyard. It must be a closed shape.",
                            "The DRC cannot check part spacing."),
    "isolated_copper": (RISK, "4.2", "Remove the isolated copper, or connect it to ground.",
                        "Floating copper can act as an antenna."),
    "via_dangling": (RISK, "4.5", "Remove the via, or connect it to a net.",
                     "An unused via is an antenna stub and wastes space."),
    "track_dangling": (RISK, "4.5", "Remove the conductor end, or connect it.",
                       "An unconnected track end is an antenna stub."),
    "lib_footprint_mismatch": (RISK, "3.4", "Update the footprint from the library, or record the change.",
                               "The board footprint differs from the library version."),
    "lib_footprint_issues": (RISK, "3.4", "Correct the footprint library link.",
                             "The footprint cannot be found in a library."),
    "footprint_type_mismatch": (RISK, "3.4", "Set the footprint type (SMD or through-hole) correctly.",
                                "Pick-and-place files will be wrong."),
    "silk_over_copper": (COSMETIC, "4.2", "Move the silkscreen off the exposed copper.",
                         "The fabricator clips the legend. Text can become illegible."),
    "silk_overlap": (COSMETIC, "4.2", "Move the silkscreen text. Make sure that it is legible.",
                     "Overlapping text is hard to read."),
    "silk_edge_clearance": (COSMETIC, "4.2", "Move the silkscreen away from the board edge.",
                            "The legend can be cut off."),
    "text_height": (COSMETIC, "4.2", "Make the silkscreen text taller.",
                    "Small text can be illegible after printing."),
    "text_thickness": (COSMETIC, "4.2", "Make the silkscreen line thicker.",
                       "Thin lines can break up after printing."),
}

ERC_INFO = {
    "pin_to_pin": (BLOCK, "Examine the pin types. Two outputs must not drive the same net."),
    "power_pin_not_driven": (BLOCK, "Connect a power source to this net. Add a PWR_FLAG if the source is a connector."),
    "duplicate_reference": (BLOCK, "Give each symbol a different reference designator."),
    "unannotated": (BLOCK, "Annotate the schematic."),
    "multiple_net_names": (BLOCK, "Give the net one name only. Remove one of the labels."),
    "pin_not_connected": (BLOCK, "Connect the pin, or put a no-connect flag on it."),
    "pin_not_driven": (RISK, "Connect an output to this input, or correct the pin type."),
    "no_connect_connected": (RISK, "Remove the no-connect flag, or disconnect the pin."),
    "different_unit_footprint": (RISK, "Use the same footprint for all units of the symbol."),
    "footprint_link_issues": (RISK, "Correct the footprint assignment of the symbol."),
    "missing_power_pin": (RISK, "Add the hidden power units or pins to the schematic."),
    "label_dangling": (RISK, "Connect the label to a wire, or remove it."),
    "global_label_dangling": (RISK, "Connect the global label, or remove it."),
    "wire_dangling": (RISK, "Connect the wire end, or remove the wire."),
    "similar_labels": (RISK, "Make the labels the same, or make them clearly different."),
    "lib_symbol_issues": (COSMETIC, "Correct the symbol library link."),
    "endpoint_off_grid": (COSMETIC, "Put the wire end on the connection grid."),
}


@dataclass
class Finding:
    source: str             # "ERC" or "DRC"
    type: str
    tier: str
    description: str
    action: str
    why: str = ""
    section: str = ""
    sheet: str = ""
    kicad_severity: str = "error"
    items: list = field(default_factory=list)   # [{"description","pos","uuid"}]

    @property
    def key(self):
        ids = sorted(i.get("uuid", "") for i in self.items if i.get("uuid"))
        if not ids:
            ids = sorted(f"{i.get('description', '')}@{(i.get('pos') or {}).get('x', '')},"
                         f"{(i.get('pos') or {}).get('y', '')}" for i in self.items)
        return f"{self.source}|{self.type}|{self.sheet}|" + "|".join(ids)

    @property
    def location(self):
        if not self.items:
            return ""
        it = self.items[0]
        pos = it.get("pos") or {}
        loc = f" at ({pos.get('x', 0):.2f}, {pos.get('y', 0):.2f})" if pos else ""
        return f"{it.get('description', '')}{loc}"


def find_kicad_cli():
    names = ["kicad-cli.exe", "kicad-cli"] if os.name == "nt" else ["kicad-cli"]
    candidates = [os.path.join(os.path.dirname(sys.executable), n) for n in names]
    candidates += ["/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"]
    for c in candidates:
        if os.path.isfile(c):
            return c
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def _run(cmd):
    kw = {"capture_output": True, "text": True}
    if os.name == "nt":
        kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    return subprocess.run(cmd, **kw)


def _run_json(cmd, out):
    res = _run(cmd)
    if not os.path.isfile(out):
        raise RuntimeError((res.stderr or res.stdout or "kicad-cli gave no output").strip()[:400])
    with open(out, encoding="utf-8") as f:
        return json.load(f)


def run_drc(cli, board_path):
    out = os.path.join(tempfile.mkdtemp(), "drc.json")
    return _run_json([cli, "pcb", "drc", "--format", "json", "--severity-all", "--units", "mm",
                      "--schematic-parity", "--refill-zones", "-o", out, board_path], out)


def run_erc(cli, sch_path):
    out = os.path.join(tempfile.mkdtemp(), "erc.json")
    return _run_json([cli, "sch", "erc", "--format", "json", "--severity-all", "--units", "mm",
                      "-o", out, sch_path], out)


def _tier(info_tier, kicad_sev):
    # A KiCad "warning" never ranks above Reliability risk.
    if kicad_sev == "warning" and info_tier == BLOCK:
        return RISK
    return info_tier


def findings_from_drc(data):
    out = []
    all_v = (data.get("violations", []) + data.get("unconnected_items", [])
             + data.get("schematic_parity", []))
    for v in all_v:
        sev = v.get("severity", "error")
        if sev in ("exclusion", "ignore"):
            continue
        t = v.get("type", "unknown")
        tier, sec, act, why = DRC_INFO.get(t, (RISK, "4.5", "Examine the violation in the KiCad DRC window.", ""))
        out.append(Finding("DRC", t, _tier(tier, sev), v.get("description", ""), act, why, sec, "",
                           sev, v.get("items") or []))
    return out


def findings_from_erc(data):
    out = []
    for sheet in data.get("sheets", []):
        for v in sheet.get("violations", []):
            sev = v.get("severity", "error")
            if sev in ("exclusion", "ignore"):
                continue
            t = v.get("type", "unknown")
            tier, act = ERC_INFO.get(t, (RISK, "Examine the violation in the KiCad ERC window."))
            out.append(Finding("ERC", t, _tier(tier, sev), v.get("description", ""), act, "", "",
                               sheet.get("path", "/"), sev, v.get("items") or []))
    return out


def sort_findings(findings):
    return sorted(findings, key=lambda f: (TIER_ORDER.get(f.tier, 9), f.source, f.type))


SOURCE_TITLE = {"ERC": "ELECTRICAL RULE CHECK", "DRC": "DESIGN RULE CHECK", "PWR": "POWER & THERMAL CHECK",
                "SCH": "SCHEMATIC REVIEW", "AI": "AI REVIEW (check every finding against the datasheet)"}


def build_report(board_path, findings, waived, notes=None, level="Beginner", ran=("ERC", "DRC"), appendix=None):
    """Plain-text report. `waived` = list of (Finding, waiver dict)."""
    out = ["IPC / ASD-STE100 DESIGN CHECK REPORT", f"Board: {board_path}", f"Level: {level}", ""]
    for n in notes or []:
        out.append(f"NOTE: {n}")
    for src in ran:
        fs = [f for f in findings if f.source == src]
        out += ["", f"{SOURCE_TITLE.get(src, src)} ({src}): {len(fs)} open finding(s)"]
        if not fs:
            out.append("    No open findings." + (" Next: the final checks in the Fabrication tab." if src == "DRC" else ""))
        for tier in (BLOCK, RISK, COSMETIC):
            tf = [f for f in fs if f.tier == tier]
            if not tf:
                continue
            out.append(f"  == {tier.upper()} ({len(tf)}) ==")
            groups = {}
            for f in tf:
                groups.setdefault(f.type, []).append(f)
            for t, gs in groups.items():
                f0 = gs[0]
                out.append(f"  {t} ({len(gs)}): {f0.description}")
                out.append(f"      Action: {f0.action}" + (f" (Document section {f0.section})" if f0.section else ""))
                if level == "Beginner" and f0.why:
                    out.append(f"      Why: {f0.why}")
                limit = 3 if level != "Expert" else len(gs)
                for f in (gs[:limit] if not (f0.source in ("PWR", "SCH", "AI") and len(gs) == 1) else []):
                    where = f.description if f.source in ("PWR", "SCH", "AI") else f.location
                    out.append(f"      - {(f.sheet + ': ') if f.sheet else ''}{where}")
                if len(gs) > limit:
                    out.append(f"      - ...and {len(gs) - limit} more")
    if waived:
        out += ["", f"WAIVED FINDINGS ({len(waived)}) - audit record"]
        for f, w in waived:
            out.append(f"  [{f.source}] {f.type}: {f.location}")
            out.append(f"      Reason: {w.get('reason', '')} - {w.get('by', '?')}, {w.get('date', '?')}")
    if appendix:
        out += ["", appendix]
    blocking = sum(1 for f in findings if f.tier == BLOCK)
    out += ["", "RESULT: " + ("NOT READY - fix the 'Blocks fabrication' findings first." if blocking
                              else "No blocking findings. Examine the risks, then do the section 4.5 checklist.")]
    return "\n".join(out)
