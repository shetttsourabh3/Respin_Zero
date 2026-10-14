"""Build KiCad-style XML netlists (export version E) for tests."""
from xml.sax.saxutils import quoteattr as q
def netlist(comps, nets):
    lib = {}
    out = ['<?xml version="1.0" encoding="utf-8"?>', '<export version="E">', '<design><source>test.kicad_sch</source></design>', '<components>']
    for ref, (value, libname, part, pins) in comps.items():
        out.append(f'<comp ref={q(ref)}><value>{value}</value><footprint>fp</footprint><libsource lib={q(libname)} part={q(part)} description=""/></comp>')
        lib[(libname, part)] = pins
    out.append('</components><libparts>')
    for (l, p), pins in lib.items():
        out.append(f'<libpart lib={q(l)} part={q(p)}><pins>' + "".join(f'<pin num={q(n)} name={q(nm)} type={q(t)}/>' for n, nm, t in pins) + '</pins></libpart>')
    out.append('</libparts><nets>')
    for i, (name, nodes) in enumerate(nets.items(), 1):
        out.append(f'<net code="{i}" name={q(name)} class="Default">' + "".join(f'<node ref={q(r)} pin={q(n)}/>' for r, n in nodes) + '</net>')
    out.append('</nets></export>')
    return "\n".join(out)

R2 = [("1", "~", "passive"), ("2", "~", "passive")]
def R(v): return (v, "Device", "R", R2)
def Cap(v): return (v, "Device", "C", R2)
def LED(v="LED"): return (v, "Device", "LED", [("1", "K", "passive"), ("2", "A", "passive")])
def XTAL(v): return (v, "Device", "Crystal", [("1", "1", "passive"), ("2", "2", "passive")])
USBC = ("USB_C_Receptacle_USB2.0", "Connector", "USB_C_Receptacle_USB2.0_16P",
        [("A4", "VBUS", "passive"), ("A1", "GND", "passive"), ("A5", "CC1", "bidirectional"), ("B5", "CC2", "bidirectional"),
         ("A6", "D+", "bidirectional"), ("A7", "D-", "bidirectional")])
def HDR(n): return (f"Conn_01x{n:02d}", "Connector", f"Conn_01x{n:02d}", [(str(i), f"Pin_{i}", "passive") for i in range(1, n + 1)])
LDO = ("AP2112K-3.3", "Regulator_Linear", "AP2112K-3.3", [("1", "VIN", "power_in"), ("2", "GND", "power_in"), ("3", "EN", "input"), ("5", "VOUT", "power_out")])
SENSOR = ("BME280", "Sensor", "BME280", [("8", "VDD", "power_in"), ("6", "VDDIO", "power_in"), ("1", "GND", "power_in"), ("3", "SDI", "bidirectional"), ("4", "SCK", "input")])
ESP_CHIP = ("ESP32-C3", "MCU_Espressif", "ESP32-C3", [
    ("31", "VDD3P3_CPU", "power_in"), ("1", "VDDA", "power_in"), ("2", "VDDA", "power_in"), ("3", "VDD3P3", "power_in"), ("4", "VDD3P3", "power_in"),
    ("17", "VDD3P3_RTC", "power_in"), ("18", "VDD_SPI", "power_out"), ("33", "GND", "power_in"),
    ("7", "CHIP_EN", "input"), ("15", "GPIO9", "bidirectional"), ("14", "GPIO8", "bidirectional"), ("6", "GPIO2", "bidirectional"),
    ("29", "XTAL_P", "passive"), ("30", "XTAL_N", "passive"), ("25", "GPIO18", "bidirectional"), ("26", "GPIO19", "bidirectional"),
    ("27", "U0RXD", "bidirectional"), ("28", "U0TXD", "bidirectional"), ("12", "GPIO4", "bidirectional"), ("13", "GPIO5", "bidirectional")])
ESP_MOD = ("ESP32-C3-MINI-1", "RF_Module", "ESP32-C3-MINI-1", [
    ("3", "3V3", "power_in"), ("1", "GND", "power_in"), ("8", "EN", "input"), ("23", "IO9", "bidirectional"), ("22", "IO8", "bidirectional"),
    ("5", "IO2", "bidirectional"), ("26", "IO18", "bidirectional"), ("27", "IO19", "bidirectional"), ("30", "RXD0", "bidirectional"), ("31", "TXD0", "bidirectional"),
    ("12", "IO4", "bidirectional"), ("13", "IO5", "bidirectional"), ("16", "IO10", "bidirectional")])
