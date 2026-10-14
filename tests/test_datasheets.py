import os

from conftest import DATA, mod

DS = mod("datasheets")
E = mod("dsextract")
PDF = os.path.join(DATA, "ap2112.pdf")


def test_library_add_and_share(tmp_path, design):
    d = design("buggy_esp")
    lib = DS.Library(str(tmp_path))
    groups = DS.groups_from_design(d, lib)
    g = next(g for g in groups if "AP2112" in g.label)
    lib.add(PDF, g)
    assert os.path.isfile(os.path.join(str(tmp_path), "datasheets", "Power", "AP2112K-3.3.pdf"))
    groups = DS.groups_from_design(d, DS.Library(str(tmp_path)))
    files = DS.Library(str(tmp_path)).ai_files(groups, d)
    assert len(files) == 1 and files[0][4]["mpn"]
    lib.set_ai(g, False)
    assert DS.Library(str(tmp_path)).ai_files(DS.groups_from_design(d, DS.Library(str(tmp_path))), d) == []


def test_bundled_pdf_reader():
    assert E.available()
    assert len(E.pages(PDF)) == 10


def test_pages_for_exact_part():
    pg = E.pages(PDF)
    _t, chosen, _r, found = E.select(pg, "AP2112K-3.3TRG1", ["VIN", "EN", "VOUT"], budget=12000)
    assert found == "exact"
    assert {3, 4, 5}.issubset(chosen)                    # ordering, pins, absolute maximum
    assert not {2, 7, 9, 10} & set(chosen)               # revision history, graphs, package, legal


def test_wrong_variant_and_wrong_file():
    pg = E.pages(PDF)
    assert E.select(pg, "AP2112K-5.0TRG1", budget=12000)[3] == "family"
    assert E.select(pg, "LM1117-3.3", budget=12000)[3] == "no"
