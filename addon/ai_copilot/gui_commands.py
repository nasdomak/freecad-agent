# -*- coding: utf-8 -*-
"""
ai_copilot.gui_commands - GUI command(s) for the FreeCAD Agent workbench.

WHY THIS MODULE EXISTS (root-cause fix, Session 8):
FreeCAD runs InitGui.py inside a throwaway namespace. Names defined at the top
level of InitGui.py (e.g. a command class) are NOT reliably visible from
DEFERRED workbench method calls such as Workbench.Initialize(), which runs later
when the user activates the workbench. The symptom was:

    [FreeCAD Agent] addCommand failed: name '_ShowPanelCommand' is not defined
    Unknown command 'FreeCADAgent_ShowPanel'   (twice -> toolbar + menu)

and a missing toolbar icon. By contrast, anything reached through an `import`
resolves via sys.modules, which IS stable across deferred calls (that is why
Workbench.Activated() always worked - it imports show_panel). So we keep the
command here, in an importable module, and InitGui.py imports it inside
Initialize(). Registration is idempotent, so re-activating the workbench is safe.
"""

import os

import FreeCAD
import FreeCADGui

# Stable command id used by the toolbar, the menu and addCommand.
COMMAND_NAME = "FreeCADAgent_ShowPanel"

# Resolve the workbench icon relative to THIS file (stable, no __file__ tricks in
# InitGui). Empty string is a harmless "no icon" for FreeCAD.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ICON = os.path.join(_HERE, "ui", "icon.svg")
if not os.path.isfile(_ICON):
    _ICON = ""


class ShowPanelCommand:
    """GUI command: open/show the add-on panel."""

    def GetResources(self):
        return {
            "Pixmap": _ICON,
            "MenuText": "FreeCAD Agent panel",
            "ToolTip": "Open the panel to connect the engine and run commands",
        }

    def Activated(self):
        # Import here (stable via sys.modules) so the panel opens on demand.
        from ai_copilot.ui import show_panel
        show_panel()

    def IsActive(self):
        return True


def register():
    """
    Register the panel command once and return its id.

    Idempotent: if the command is already registered (e.g. the workbench is
    activated again), we do not register it twice. Returns COMMAND_NAME so the
    caller can append it to the toolbar/menu only after a successful registration.
    """
    try:
        existing = FreeCADGui.listCommands()
    except Exception:
        existing = []
    if COMMAND_NAME not in existing:
        FreeCADGui.addCommand(COMMAND_NAME, ShowPanelCommand())
    return COMMAND_NAME
