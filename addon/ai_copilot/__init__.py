"""
ai_copilot - the FreeCAD Agent add-on package (add-on side of the bridge).

It lives INSIDE FreeCAD, bound to the internal Python 3.11 (principle 2/3).
For Phase 1 it contains:
- bridge_client : the bridge client that attaches to the engine.
- qt_invoker    : marshalling calls onto FreeCAD's Qt main thread.
- executor/     : runs the vocabulary commands inside undoable transactions.
- ui/           : the Qt dock panel.

NOTE: historically the internal package is named 'ai_copilot' (from the plan).
The product was renamed "FreeCAD Agent"; renaming the package is a cosmetic detail
deferred so as not to break paths during Phase 1.
"""

__version__ = "0.3.0-phase2"
