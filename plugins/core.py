"""Workflow logic shared by the UI. No widgets here: confirmations come in as callbacks."""
import os
import time
from dataclasses import dataclass, field

try:
    import pcbnew
except ImportError:
    pcbnew = None

from . import rules as R
from . import checks as C
from . import manufacturers as M
from . import dru as D
from . import board as B
from . import stackup_file as SF
from . import pcbfile as PF
from . import powercheck as PC
from . import netdetect as N
from . import schnet as SN
from . import schreview as SR

RULE_KEYS = [("clearance", "Copper to copper"), ("track_width", "Track width"),
             ("min_drill", "Drill"), ("via_drill", "Via drill"), ("via_diameter", "Via pad"),
             ("annular_ring", "Annular ring"), ("hole_to_hole", "Hole to hole"),
             ("copper_edge", "Copper to edge"), ("solder_mask_web", "Solder mask dam"),
             ("silk_line", "Silkscreen line"), ("silk_height", "Silkscreen height")]


def load_req(board, paths):
    req = B.board_defaults(board, R.Requirements())
    if os.path.isfile(paths["cfg"]):
        try:
            with open(paths["cfg"], encoding="utf-8") as f:
                req = R.Requirements.from_json(f.read())
        except Exception:
            pass
    return req


def save_req(req, paths):
    with open(paths["cfg"], "w", encoding="utf-8") as f:
        f.write(req.to_json())


@dataclass
class ApplyResult:
    rules: dict
    notes: list
    stack_lines: list
    constraints_set: list
    constraints_skipped: list
    kept_user_rules: bool
    revert_needed: bool = False
    rows: list = field(default_factory=list)      # (name, value_mm, why)


def apply_rules(board, req, profiles, paths, confirm_stackup):
    """Generate and write rules, constraints and stackup.

    confirm_stackup(text) -> bool is asked before the board file is edited (KiCad 10).
    """
    prof = profiles.get(req.manufacturer)
    if prof and req.level != "Expert":
        req.apply_profile(prof)
    rules, notes = R.derive(req)
    notes = M.check_fit(prof, req) + notes
    kept = D.write(paths["dru"], R.rules_block(req, rules))
    save_req(req, paths)
    revert = False
    if board is None:                # standalone window: no live board; rules file and stackup only
        done, skipped = [], ["Board Setup minimum values (open the board in the PCB editor and apply again)"]
        stack_lines, stack_warn = stackup_standalone(req, paths, confirm_stackup)
    else:
        done, skipped = B.apply_board_settings(board, rules)
        try:
            stack_lines, stack_warn = B.apply_stackup(board, req)
        except B.StackupUnavailable:
            stack_lines, stack_warn, revert = stackup_via_file(board, req, paths, confirm_stackup)
        B.mark_modified(board)
    try:
        pcbnew.Refresh()
    except Exception:
        pass
    rows = [(label, rules[k], rules["why"][k]) for k, label in RULE_KEYS]
    rows += [(n["name"], n["min"], n.get("why", "")) for n in rules["netclass_rules"]]
    return ApplyResult(rules, stack_warn + notes, stack_lines, done, skipped, kept, revert, rows)


def stackup_standalone(req, paths, confirm):
    """Without the PCB editor the stackup is not changed: the PCB editor would overwrite it on its next save."""
    return [], [f"The stackup was not changed (window opened without the PCB editor). To set "
                f"{req.board_thickness_mm:g} mm, open the board in the PCB editor and apply the rules there."]


def stackup_via_file(board, req, paths, confirm):
    path = paths["board"]
    ask = (f"KiCad 10 does not let plugins change the stackup directly.\n\n"
           f"To set {req.board_thickness_mm:g} mm the plugin will:\n"
           "  1. Save the board (with the new design rules).\n"
           "  2. Change the stackup in the board file. A backup is kept.\n"
           "  3. Then you use File > Revert to reload the board.\n\nContinue?")
    if not confirm(ask):
        return [], [f"The stackup was not changed. Set it in Board Setup > Physical Stackup "
                    f"to {req.board_thickness_mm:g} mm, or apply again."], False
    B.save_board(board, path)
    try:
        lines, warn = SF.edit_file(path, req.board_thickness_mm, req.outer_copper_oz, req.inner_copper_oz)
    except (ValueError, OSError) as e:
        return [], [f"The stackup was not changed: {e}"], False
    return lines, warn, True


_STANDALONE_BOARD = {}


def paths_board(board):
    return _STANDALONE_BOARD.get("path") if board is None else None


def detect_nets(board, req):
    return N.detect(B.net_names(board, paths_board(board)), {g.net: g for g in req.net_groups})


def run_erc_drc(paths, progress=lambda msg: None):
    """Run in a worker thread. Returns (findings, notes, ran)."""
    notes, findings, ran = [], [], []
    cli = C.find_kicad_cli()
    if not cli:
        return [], ["The plugin cannot find kicad-cli. Make sure that KiCad 10 is installed correctly."], ()
    if os.path.isfile(paths["sch"]):
        progress("Running ERC...")
        try:
            findings += C.findings_from_erc(C.run_erc(cli, paths["sch"]))
            ran.append("ERC")
        except Exception as e:
            notes.append(f"ERC did not run: {e}")
    else:
        notes.append("No schematic found. The ERC is skipped.")
    progress("Running DRC (zones are refilled first)...")
    try:
        findings += C.findings_from_drc(C.run_drc(cli, paths["board"]))
        ran.append("DRC")
    except Exception as e:
        notes.append(f"DRC did not run: {e}")
    if not os.path.isfile(paths["dru"]):
        notes.append("No custom rules found. Apply the rules in the Design Rules tab first.")
    return findings, notes, tuple(ran)


def run_power(paths, req, progress=lambda msg: None):
    """Run in a worker thread. Returns (findings, summaries, notes)."""
    progress("Reading the board file...")
    with open(paths["board"], encoding="utf-8") as f:
        pcb = PF.parse(f.read(), req.outer_copper_oz * B.OZ_MM, req.inner_copper_oz * B.OZ_MM)
    progress("Checking tracks, vias and thermal pads...")
    findings, summaries, notes = PC.analyze(pcb, req)
    notes.append(f"Limit: {req.temp_rise_c:g} C conductor temperature rise. Values are IPC-2221 estimates.")
    return findings, summaries, notes


def file_time(path):
    try:
        return time.strftime("%d %b %H:%M", time.localtime(os.path.getmtime(path)))
    except OSError:
        return None


def rules_applied(paths):
    try:
        with open(paths["dru"], encoding="utf-8") as f:
            return D.BEGIN in f.read()
    except OSError:
        return False


def run_schematic(paths, progress=lambda msg: None):
    """Run in a worker thread. Returns (findings, notes, matched)."""
    cli = C.find_kicad_cli()
    if not cli:
        return [], ["The plugin cannot find kicad-cli. Make sure that KiCad 10 is installed correctly."], []
    if not os.path.isfile(paths["sch"]):
        return [], ["No schematic found next to the board."], []
    progress("Exporting the netlist from the saved schematic...")
    design = SN.parse_xml(SN.export_netlist(cli, paths["sch"]))
    progress(f"Reviewing {len(design.comps)} parts and {len(design.nets)} nets...")
    profiles = SR.load_profiles(paths["dir"])
    findings, matched, notes = SR.review(design, profiles)
    notes = [f"Chip profile used: {ref} = {name}" for ref, name in matched] + notes
    notes.append("The review uses the saved schematic. Save it in the Schematic Editor before you run the review.")
    return findings, notes, matched


def load_design(paths):
    cli = C.find_kicad_cli()
    if not cli:
        raise RuntimeError("The plugin cannot find kicad-cli. Make sure that KiCad 10 is installed correctly.")
    if not os.path.isfile(paths["sch"]):
        raise RuntimeError("No schematic found next to the board.")
    return SN.parse_xml(SN.export_netlist(cli, paths["sch"]))


def ai_request(paths, mode="schematic", req=None, prior=()):
    """(validator_context, instructions, data, truncated, skills_used) for preview and review.

    mode "schematic": the netlist summary; mode "pcb": measured layout facts.
    """
    from . import aireview as AR
    from . import ailayout as AL
    from . import skills as SK
    if mode == "pcb":
        with open(paths["board"], encoding="utf-8") as f:
            board = PF.parse(f.read(), (req.outer_copper_oz if req else 1) * B.OZ_MM,
                             (req.inner_copper_oz if req else 0.5) * B.OZ_MM)
        ins, data, trunc = AL.build_request(board, req, prior)
        ctx = ("pcb", board)
    else:
        d = load_design(paths)
        rule, _m, _n = SR.review(d, SR.load_profiles(paths["dir"]))
        ins, data, trunc = AR.build_request(d, rule)
        ctx = ("schematic", d, rule)
    block, used = SK.instructions_block(SK.active(paths["dir"], mode, req.ai_skills_off if req else ()))
    return ctx, ins + block, data, trunc, used


def ai_datasheets(paths, design=None):
    """Datasheets marked 'send to AI' for parts in the design: [(label, refs, path, MB)]."""
    from . import datasheets as DS
    lib = DS.Library(paths["dir"])
    if not lib.entries:
        return []
    try:
        d = design or load_design(paths)
    except Exception:
        return []
    return lib.ai_files(DS.groups_from_design(d, lib), d)


def run_ai(paths, provider, model="", progress=lambda m: None, mode="schematic", req=None, prior=()):
    """Run in a worker thread. Returns (rule_findings, ai_findings, notes)."""
    from . import aireview as AR
    from . import ailayout as AL
    progress("Reading the design..." if mode == "schematic" else "Measuring the layout...")
    ctx, ins, data, trunc, used = ai_request(paths, mode, req, prior)
    files = []
    if provider.reads_pdfs:
        progress("Collecting datasheets...")
        files = ai_datasheets(paths, ctx[1] if ctx[0] == "schematic" else None)
    progress(f"Waiting for {provider.short}"
             + (f" ({len(files)} datasheet(s))" if files else "") + "... large designs can take a few minutes")
    provider.ds_notes = []
    res = provider.review(ins, data, model=model, files=files)
    progress("Checking every part, pad and net the AI named...")
    if ctx[0] == "pcb":
        found, dropped, summary = AL.parse_reply(res.text, ctx[1])
        rule = []
    else:
        found, dropped, summary = AR.parse_reply(res.text, ctx[1])
        rule = ctx[2]
    notes = []
    if summary:
        notes.append(f"AI summary: {summary}")
    notes.append(f"AI review by {provider.name}, model {res.model} ({res.billing}) in {res.seconds:.0f} s"
                 + (f", about ${res.cost:.2f}" if res.cost else "") + ".")
    how = "as read-only files" if provider.files_mode == "read" else "as extracted text"
    notes.append(f"AI datasheets shared {how}: {', '.join(f[0] for f in files)} ({res.files_shared} read)." if files else
                 ("AI datasheets shared: none." if provider.reads_pdfs else
                  f"AI datasheets: not shared ({provider.short} takes no files and no PDF text extractor was found)."))
    for n in getattr(provider, "ds_notes", [])[:12]:
        notes.append(f"AI datasheet {n}.")
    notes.append(f"AI skills used: {', '.join(used)}." if used else "AI skills used: none.")
    if dropped:
        notes.append(f"AI review: {len(dropped)} finding(s) dropped because they named parts, pads or nets that are "
                     f"not in the design: " + "; ".join(dropped[:8]))
    if trunc:
        notes.append("AI review: the design was too large for one request; the AI saw only the first part of it.")
    notes.append("AI review: findings can be wrong. Check each one against the datasheet before you change the design.")
    return rule, found, notes, res
