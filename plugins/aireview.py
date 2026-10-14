"""AI schematic review: build a compact design summary, ask for JSON findings, validate every reference.

The AI only sees text the plugin builds. Every finding must name parts, pins or nets that exist in
the netlist; findings that name anything else are dropped. Pure Python.
"""
import json
import re

from . import checks as C

MAX_CHARS = 120_000          # keep requests inside common context limits
TIER = {"block": C.BLOCK, "risk": C.RISK, "cosmetic": C.COSMETIC}

INSTRUCTIONS = """You are a senior hardware engineer reviewing a schematic for an embedded product before PCB release.
The design is given as a netlist summary. Find real design errors and important omissions:
- power: regulator input/output ranges, rail voltages vs. part limits, decoupling and bulk capacitance, enable pins
- MCUs and ICs: boot/strapping pins, reset, clocks and crystals, required external parts from the datasheet
- interfaces: I2C pull-ups, USB (CC, series resistors, ESD), UART/SPI direction, level mismatches between voltage domains
- protection: ESD, reverse polarity, inrush, battery charging limits
- analog: divider ratios vs. ADC range, op-amp supply and input range
- anything a part's datasheet requires that is missing

Rules:
- Report only problems you can justify from the netlist and well-known datasheet facts. Do not report style issues.
- If you are not sure about a datasheet value, say so and set "confidence" to "low".
- Use ONLY reference designators, pin numbers and net names that appear in the summary.
- The "Rule-based findings" are already known; do not repeat them.
- Severity: "block" = the board will not work or will be damaged; "risk" = may fail, unreliable or out of spec; "cosmetic" = improvement.

Reply with ONLY a JSON object, no other text:
{"findings": [{"severity": "block|risk|cosmetic", "title": "short title",
  "detail": "what is wrong and why, with values", "action": "what to change",
  "refs": ["U1", "R5"], "pins": ["U1.15"], "nets": ["/EN"], "confidence": "high|medium|low"}],
 "summary": "one or two sentences about the design"}
"""


def summarize(d, rule_findings=()):
    """Compact text description of the design."""
    lines = ["# Parts"]
    passives = {}
    for c in sorted(d.comps.values(), key=lambda c: (c.kind, c.ref)):
        if c.kind == "ignore":
            continue
        if c.kind in ("R", "C", "L", "FB") and c.two_nets():
            a, b = c.two_nets()
            passives.setdefault(c.kind, []).append(f"{c.ref} {c.value}: {a} -- {b}")
            continue
        pins = sorted(c.pins.values(), key=lambda p: (len(p.num), p.num))
        desc = f"{c.ref} [{c.kind}] value={c.value} part={c.lib}:{c.part}"
        mpn = next((c.fields[k] for k in ("mpn", "manufacturer_part_number", "mfr part", "mfr_pn",
                    "manufacturer part number", "part number", "partnumber") if c.fields.get(k, "~") not in ("~", "")), "")
        mfr = next((c.fields[k] for k in ("manufacturer", "mfr", "manufacturer_name") if c.fields.get(k, "~") not in ("~", "")), "")
        if mpn:
            desc += f" MPN={mpn}" + (f" ({mfr})" if mfr else "")
        if c.description:
            desc += f" ({c.description[:80]})"
        lines.append(desc)
        for p in pins:
            if c.kind == "IC" or len(pins) <= 40:
                net = p.net if p.net and not d.is_floating(p.net) else "(not connected)"
                lines.append(f"  {c.ref}.{p.num} {p.name or '-'} [{p.type or '?'}] -> {net}")
    for kind, title in (("R", "Resistors"), ("C", "Capacitors"), ("L", "Inductors"), ("FB", "Ferrite beads")):
        if passives.get(kind):
            lines.append(f"# {title} (ref value: net -- net)")
            lines += [f"  {x}" for x in passives[kind]]
    lines.append("# Rails (power and ground nets, with parts on them)")
    for net in sorted(d.nets):
        if d.is_power(net) or d.is_ground(net):
            refs = sorted({p.ref for p in d.pins_on(net)})
            v = d.voltage(net)
            lines.append(f"  {net}{f' (~{v:g} V from name)' if v else ''}: {', '.join(refs[:60])}"
                         f"{' ...' if len(refs) > 60 else ''}")
    if rule_findings:
        lines.append("# Rule-based findings (already reported)")
        lines += [f"  - [{f.tier}] {f.description}" for f in rule_findings]
    text = "\n".join(lines)
    truncated = len(text) > MAX_CHARS
    if truncated:
        text = text[:MAX_CHARS] + "\n# (summary cut here: the design is too large for one request)"
    return text, truncated


def build_request(d, rule_findings=()):
    summary, truncated = summarize(d, rule_findings)
    return INSTRUCTIONS, "DESIGN NETLIST SUMMARY\n\n" + summary, truncated


def _extract_json(text):
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if m:
        text = m.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("The AI reply has no JSON object.")
    return json.loads(text[start:end + 1])


def _slug(title):
    return "ai_" + re.sub(r"[^a-z0-9]+", "_", (title or "finding").lower()).strip("_")[:40]


def parse_reply(text, d):
    """Schematic: findings must reference real parts/pins/nets. Returns (findings, dropped, summary)."""
    def pin_label(ref, num):
        pin = d.comps[ref].pins.get(num)
        return pin.label() if pin else f"{ref} pin {num}"
    return parse_generic(text, lambda r: r in d.comps,
                         lambda r, n: r in d.comps and (not n or n in d.comps[r].pins),
                         lambda n: n in d.nets, pin_label)


def parse_generic(text, has_ref, has_pin, has_net, pin_label):
    data = _extract_json(text)
    out, dropped = [], []
    for raw in data.get("findings", []) or []:
        if not isinstance(raw, dict):
            continue
        refs = [r for r in raw.get("refs", []) or [] if isinstance(r, str)]
        pins = [p for p in raw.get("pins", []) or [] if isinstance(p, str)]
        nets = [n for n in raw.get("nets", []) or [] if isinstance(n, str)]
        bad = [r for r in refs if not has_ref(r)]
        bad += [p for p in pins if not has_pin(*(p.partition(".")[::2]))]
        bad += [n for n in nets if not has_net(n)]
        title = str(raw.get("title", "")).strip() or "AI finding"
        if bad or not (refs or pins or nets):
            dropped.append(f"{title} (unknown: {', '.join(bad) or 'no parts named'})")
            continue
        tier = TIER.get(str(raw.get("severity", "risk")).lower(), C.RISK)
        conf = str(raw.get("confidence", "medium")).lower()
        if conf == "low" and tier == C.BLOCK:
            tier = C.RISK                      # never block on a low-confidence guess
        items = []
        for p in pins:
            ref, _, num = p.partition(".")
            items.append({"description": pin_label(ref, num), "ref": ref})
        items += [{"description": r, "ref": r} for r in refs if r not in {i["ref"] for i in items}]
        items += [{"description": f"net {n}", "ref": ""} for n in nets]
        detail = str(raw.get("detail", "")).strip()
        out.append(C.Finding("AI", _slug(title), tier, f"{title}: {detail}" if detail else title,
                             str(raw.get("action", "")).strip() or "Examine this with the datasheet.",
                             f"AI review, confidence {conf}. Check this against the datasheet before you change the design.",
                             "", "", "error", items))
    return out, dropped, str(data.get("summary", "")).strip()
