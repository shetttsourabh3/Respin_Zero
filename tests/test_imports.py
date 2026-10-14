"""Every relative import must point at a real module (catches mistakes after moving code)."""
import ast
import glob
import os

from conftest import ROOT


def test_relative_imports_resolve():
    bad = []
    for path in glob.glob(os.path.join(ROOT, "plugins", "**", "*.py"), recursive=True):
        if os.sep + "vendor" + os.sep in path:
            continue
        pkg_dir = os.path.dirname(path)
        for node in ast.walk(ast.parse(open(path, encoding="utf-8").read())):
            if isinstance(node, ast.ImportFrom) and node.level:
                base = pkg_dir
                for _ in range(node.level - 1):
                    base = os.path.dirname(base)
                if node.module:
                    target = os.path.join(base, *node.module.split("."))
                    if not (os.path.isfile(target + ".py") or os.path.isdir(target)):
                        bad.append(f"{os.path.relpath(path, ROOT)}:{node.lineno} from {'.' * node.level}{node.module}")
                else:
                    for a in node.names:
                        target = os.path.join(base, a.name)
                        if not (os.path.isfile(target + ".py") or os.path.isdir(target)):
                            bad.append(f"{os.path.relpath(path, ROOT)}:{node.lineno} from {'.' * node.level} import {a.name}")
    assert not bad, "\n".join(bad)


def test_shortcut_button_works(tmp_path):
    from conftest import mod
    S = mod("standalone")
    p = S.create_shortcut(str(tmp_path / "demo.kicad_pro"), str(tmp_path))
    assert os.path.isfile(p) and "launch.py" in open(p).read()
