# -*- coding: utf-8 -*-
"""
InitGui.py - entry point of the add-on as a FreeCAD WORKBENCH.

FreeCAD runs this file at startup (in GUI mode) for every add-on present in the
Mod folder. From here we register the "FreeCAD Agent" workbench: when the user
selects it from the workbench bar, the add-on panel appears.

ROBUSTNESS: this file is written to be FAIL-SAFE. Module-level globals that the
class bodies reference (e.g. _ICON) are defined FIRST and the discovery logic is
wrapped in try/except, so the workbench still registers even if something odd
happens at load time. Class bodies read the icon via globals().get(...) so a
missing global can never raise a NameError. NOTE: FreeCAD 1.1 does NOT define
__file__ here, so the add-on folder is found robustly (see _find_addon_dir).
"""

import os
import sys

import FreeCAD
import FreeCADGui

# --- Fail-safe defaults: defined BEFORE anything else references them ---------
_ICON = ""    # path to the workbench icon ("" = no icon, harmless)
_HERE = None  # the add-on root folder (the one with addon/ and shared/)


def _find_addon_dir():
    """Return this add-on's root folder (the one with addon/ and shared/)."""
    # 1) if __file__ happens to exist, it's the most direct way.
    try:
        return os.path.dirname(os.path.abspath(__file__))  # noqa: F821
    except NameError:
        pass
    # 2) FreeCAD adds the add-on folder to sys.path BEFORE running InitGui.py:
    #    look for the one containing our structure (marker).
    for _entry in list(sys.path):
        try:
            if (_entry and os.path.isfile(os.path.join(_entry, "InitGui.py"))
                    and os.path.isdir(os.path.join(_entry, "addon"))
                    and os.path.isdir(os.path.join(_entry, "shared"))):
                return _entry
        except Exception:
            continue
    # 3) fallback: known FreeCAD Mod folders (user and installation).
    for _base in (FreeCAD.getUserAppDataDir(), FreeCAD.getResourceDir()):
        try:
            _moddir = os.path.join(_base, "Mod")
            if not os.path.isdir(_moddir):
                continue
            for _name in os.listdir(_moddir):
                _cand = os.path.join(_moddir, _name)
                if (os.path.isfile(os.path.join(_cand, "InitGui.py"))
                        and os.path.isdir(os.path.join(_cand, "addon"))
                        and os.path.isdir(os.path.join(_cand, "shared"))):
                    return _cand
        except Exception:
            continue
    return None


# --- Resolve the add-on folder and put addon/ + shared/ on sys.path ----------
# Wrapped so any failure degrades gracefully instead of breaking the workbench.
try:
    _HERE = _find_addon_dir()
    if _HERE is None:
        FreeCAD.Console.PrintError(
            "[FreeCAD Agent] could not find the add-on folder: panel may not open.\n")
    else:
        _ADDON_DIR = os.path.join(_HERE, "addon")     # .../addon
        _SHARED_DIR = os.path.join(_HERE, "shared")   # .../shared
        _icon_candidate = os.path.join(_ADDON_DIR, "ai_copilot", "ui", "icon.svg")
        if os.path.isfile(_icon_candidate):
            _ICON = _icon_candidate
        for _p in (_ADDON_DIR, _SHARED_DIR):
            if os.path.isdir(_p) and _p not in sys.path:
                sys.path.insert(0, _p)
except Exception as _exc:  # never let setup break workbench registration
    FreeCAD.Console.PrintError(f"[FreeCAD Agent] setup warning: {_exc}\n")


class FreeCADAgentWorkbench(FreeCADGui.Workbench):
    """The add-on workbench. Shows the panel when activated."""

    MenuText = "FreeCAD Agent"
    ToolTip = "AI copilot for FreeCAD (natural language + structured commands)"
    # Read defensively: a missing global can never raise here.
    Icon = globals().get("_ICON", "")

    def Initialize(self):
        # Register the command via an IMPORTED module (not a name defined in this
        # InitGui namespace): FreeCAD runs InitGui.py in a throwaway namespace, so
        # top-level names here are NOT reliably visible from this deferred call,
        # whereas imports resolve via sys.modules. We only add the command to the
        # toolbar/menu AFTER a successful registration, so a failure cannot leave
        # behind "Unknown command" entries.
        try:
            from ai_copilot.gui_commands import register
            cmd = register()
            self.appendToolbar("FreeCAD Agent", [cmd])
            self.appendMenu("FreeCAD Agent", [cmd])
        except Exception as exc:
            FreeCAD.Console.PrintError(
                f"[FreeCAD Agent] command setup failed: {exc}\n")
        FreeCAD.Console.PrintMessage("[FreeCAD Agent] workbench initialized.\n")

    def Activated(self):
        # When the workbench is activated, open the panel right away.
        try:
            from ai_copilot.ui import show_panel
            show_panel()
        except Exception as exc:
            FreeCAD.Console.PrintError(f"[FreeCAD Agent] failed to open the panel: {exc}\n")

    def Deactivated(self):
        pass

    def GetClassName(self):
        # Workbench defined in Python: string required by FreeCAD.
        return "Gui::PythonWorkbench"


FreeCADGui.addWorkbench(FreeCADAgentWorkbench())
