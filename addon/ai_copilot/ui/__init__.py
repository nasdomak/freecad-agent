"""
ai_copilot.ui - graphical interface of the add-on (Qt dock panel).

In Phase 1 it contains only `panel.AgentPanel`: a dockable panel that shows the
engine connection status, lets you compose and send a structured command (from
the vocabulary), and keeps an on-screen log. It also lays out the placeholders
for the privacy indicator (local/remote) and the "Free Python" banner
(principle 5), which we will use in Phase 2.
"""

from .panel import AgentPanel, show_panel

__all__ = ["AgentPanel", "show_panel"]
