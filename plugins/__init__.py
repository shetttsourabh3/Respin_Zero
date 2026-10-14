import logging

MIN_MAJOR = 10


def _kicad_major():
    try:
        import pcbnew
        return int(pcbnew.Version().lstrip("(").split(".")[0])
    except Exception:
        return 0


import os as _os

if _os.environ.get("IPCSTE_STANDALONE"):
    pass                     # opened by launch.py, outside the PCB editor: nothing to register
else:
  try:
    if _kicad_major() < MIN_MAJOR:
        logging.getLogger(__name__).warning("Respin Zero is built for KiCad 10.")
    from .plugin import IpcSteAssistant
    IpcSteAssistant().register()
  except Exception as e:  # keep KiCad running if the plugin fails to load
    logging.getLogger(__name__).exception("Respin Zero failed to load: %s", e)
