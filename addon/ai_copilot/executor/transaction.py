"""
executor/transaction.py - FreeCAD undoable transactions (principle 6).

Every agent action runs inside a FreeCAD transaction: if something goes wrong,
automatic rollback; if it goes well, it lands on the Undo stack so the user can
undo it with Ctrl+Z. This is the safety net that lets us "let it try" any model
without risk.

FreeCAD does not return an id from openTransaction(), so we generate our own
(UUID) for the protocol (commandResult.transaction_id) and also use it in the
transaction label, so it is recognizable on the Undo stack.

IMPORTANT: this code touches FreeCAD APIs and MUST run on the GUI main thread
(qt_invoker handles that). FreeCAD is imported lazily because this module must
not be importable only inside FreeCAD.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Iterator, Tuple


@contextmanager
def undoable(doc, action_label: str) -> Iterator[Tuple[str, str]]:
    """
    Context manager for an undoable transaction.

    Use:
        with undoable(doc, "create_box") as (tx_id, tx_label):
            ... create/modify objects ...
        # on clean exit -> commit; on exception -> abort + re-raise

    yields: (tx_id, tx_label)
    """
    tx_id = str(uuid.uuid4())
    tx_label = f"FreeCAD Agent: {action_label} [{tx_id[:8]}]"
    doc.openTransaction(tx_label)
    try:
        yield tx_id, tx_label
    except Exception:
        # Rollback: undo everything done in this transaction.
        doc.abortTransaction()
        raise
    else:
        doc.commitTransaction()


def rollback_last(doc) -> bool:
    """
    Undo the last committed transaction (used by the protocol's
    transaction.rollback). Returns True if there was something to undo.
    """
    if doc.getUndoNames():
        doc.undo()
        return True
    return False
