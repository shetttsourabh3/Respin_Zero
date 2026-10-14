"""Open the window without KiCad and visit every tab (needs wxPython and a display, e.g. xvfb-run)."""
import os

import pytest

wx = pytest.importorskip("wx")
from conftest import mod  # noqa: E402

pytestmark = pytest.mark.skipif(not os.environ.get("DISPLAY") and os.name != "nt", reason="no display")


def test_every_tab_opens(tmp_path, board_copy):
    board = board_copy()
    app = wx.App(False)  # noqa: F841
    S, ui, core = mod("standalone"), mod("ui"), mod("core")
    paths = S.project_paths(os.path.splitext(board)[0] + ".kicad_pro")
    core._STANDALONE_BOARD["path"] = paths["board"]
    fr = ui.show(None, paths)
    for i in range(fr.nb.GetPageCount()):
        fr.nb.SetSelection(i)
        fr._lazy(i)
        for _ in range(20):
            wx.Yield()
    assert fr.nb.GetPageCount() >= 8
    fr.Destroy()


def test_problem_report_has_no_project_path(tmp_path):
    D = mod("diag")
    D.setup_logging()
    D.log.error("Cannot read %s/secret_board.kicad_pcb token=abc123", str(tmp_path))
    text = D.report(str(tmp_path), "History")
    assert str(tmp_path) not in text and "<project>/secret_board" in text and "abc123" not in text
    assert "kicad-cli:" in text and "AI tools:" in text
