"""Respin Zero - the window (KiCad 10). The code lives in the gui package, one module per tab.
This module keeps the old import path working (plugin.py, standalone.py and the tests use it)."""
from .gui.common import *  # noqa: F401,F403
from .gui.dialogs import SkillsDialog  # noqa: F401
from .gui.tab_rules import RulesPanel  # noqa: F401
from .gui.tab_nets import NetsPanel  # noqa: F401
from .gui.tab_datasheets import DatasheetsPanel  # noqa: F401
from .gui.tab_findings import FindingsPanel  # noqa: F401
from .gui.tab_history import Timeline, SaveVersionDialog, HistoryPanel  # noqa: F401
from .gui.tab_power import PowerPanel  # noqa: F401
from .gui.tab_overview import Card, OverviewPanel  # noqa: F401
from .gui.tab_production import ProductionPanel  # noqa: F401
from .gui.frame import MainFrame, show  # noqa: F401
