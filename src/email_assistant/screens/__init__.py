"""Email Assistant screens."""

from .clients import ClientsScreen
from .dialogs import (
    EssenceDialog,
    MarkAsReadDialog,
    RegenerateDialog,
    ReminderConfirmDialog,
    RescheduleDialog,
)
from .draft import DraftScreen
from .reminders import RemindersScreen
from .thread_detail import ThreadDetailScreen

__all__ = [
    "ClientsScreen",
    "DraftScreen",
    "EssenceDialog",
    "MarkAsReadDialog",
    "RegenerateDialog",
    "ReminderConfirmDialog",
    "RemindersScreen",
    "RescheduleDialog",
    "ThreadDetailScreen",
]
