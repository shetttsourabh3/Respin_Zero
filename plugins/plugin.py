"""Respin Zero - KiCad 10 action plugin: one toolbar button, one window with tabs."""
import os

import pcbnew
import wx

from . import board as B


class IpcSteAssistant(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = "Respin Zero"
        self.category = "Design rules"
        self.description = ("IPC design rules, net currents, ERC/DRC and power/thermal checks, "
                            "explained in Simplified Technical English.")
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), "icon.png")

    def Run(self):
        board = pcbnew.GetBoard()
        if not board or not board.GetFileName():
            wx.MessageBox("Save the board once before you use the Respin Zero.", "Respin Zero")
            return
        from . import ui
        ui.show(board, B.project_paths(board))
