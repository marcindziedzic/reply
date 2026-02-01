"""Reminder service for managing email follow-up reminders."""

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from ..models import Label, Thread

if TYPE_CHECKING:
    from ..gmail import GmailClient


class ReminderStatus(Enum):
    """Status of a reminder."""

    OVERDUE = "overdue"
    UPCOMING = "upcoming"
    FUTURE = "future"


@dataclass
class Reminder:
    """Represents a reminder for a thread."""

    thread: Thread
    date_label: Optional[Label]  # e.g., "Reminders/2025-01-15" or None if Outdated
    hour_label: Optional[Label]  # e.g., "Reminders/11"
    is_outdated: bool  # Has Reminders/Outdated label
    status: ReminderStatus
    scheduled_datetime: Optional[datetime]  # Combined date + hour
    sender_email: str
    sender_name: str


# Constant label names
REMINDER_PARENT_LABEL = "Reminders"
REMINDER_LABEL_PREFIX = "Reminders/"
REMINDER_HOURS = ["09", "11", "13", "15", "17"]
REMINDER_OUTDATED = "Reminders/Outdated"
REMINDER_HOUR_LABELS = [f"Reminders/{h}" for h in REMINDER_HOURS]


class ReminderService:
    """Service for managing reminders."""

    def __init__(self):
        # Lazy import to avoid circular dependency
        from ..gmail import get_gmail_client
        self._gmail = get_gmail_client()
        self._label_cache: dict[str, Label] = {}
        self._state_file = Path.cwd() / ".reminder_state.json"

    def _get_last_cleanup_date(self) -> Optional[date]:
        """Get the date of last cleanup from state file."""
        if not self._state_file.exists():
            return None
        try:
            data = json.loads(self._state_file.read_text(encoding="utf-8"))
            last_cleanup = data.get("last_cleanup_date")
            if last_cleanup:
                return date.fromisoformat(last_cleanup)
        except (json.JSONDecodeError, ValueError, OSError):
            pass
        return None

    def _save_cleanup_date(self, cleanup_date: date) -> None:
        """Save the cleanup date to state file."""
        try:
            self._state_file.write_text(
                json.dumps({"last_cleanup_date": cleanup_date.isoformat()}),
                encoding="utf-8",
            )
        except OSError:
            pass  # Ignore write errors

    def should_run_cleanup(self) -> bool:
        """Check if cleanup should run (once per day)."""
        last_cleanup = self._get_last_cleanup_date()
        return last_cleanup != date.today()

    def ensure_base_labels_exist(self) -> None:
        """Create the base reminder labels if they don't exist.

        Creates a hierarchy:
        - Reminders (parent label)
          - Reminders/09
          - Reminders/11
          - Reminders/13
          - Reminders/15
          - Reminders/17
          - Reminders/Outdated
          - Reminders/YYYY-MM-DD (created dynamically)
        """
        # First, create the parent "Reminders" label
        self._gmail.get_or_create_label(REMINDER_PARENT_LABEL)

        # Then create child labels (hour labels)
        for hour in REMINDER_HOURS:
            label_name = f"{REMINDER_LABEL_PREFIX}{hour}"
            self._gmail.get_or_create_label(label_name)

        # Outdated label
        self._gmail.get_or_create_label(REMINDER_OUTDATED)

    def _get_label_cache(self) -> dict[str, Label]:
        """Get cached labels, refreshing if empty."""
        if not self._label_cache:
            labels = self._gmail.get_user_labels()
            self._label_cache = {label.name: label for label in labels}
        return self._label_cache

    def _invalidate_label_cache(self) -> None:
        """Invalidate the label cache."""
        self._label_cache = {}

    def _get_reminder_labels(self) -> list[Label]:
        """Get all reminder labels (Reminders/*)."""
        cache = self._get_label_cache()
        return [
            label for name, label in cache.items()
            if name.startswith(REMINDER_LABEL_PREFIX)
        ]

    def _get_date_labels(self) -> list[Label]:
        """Get all date labels (Reminders/YYYY-MM-DD)."""
        labels = self._get_reminder_labels()
        date_labels = []
        for label in labels:
            name = label.name
            if name.startswith(REMINDER_LABEL_PREFIX):
                suffix = name[len(REMINDER_LABEL_PREFIX):]
                # Check if it's a date format (YYYY-MM-DD)
                if len(suffix) == 10 and suffix[4] == "-" and suffix[7] == "-":
                    try:
                        date.fromisoformat(suffix)
                        date_labels.append(label)
                    except ValueError:
                        pass
        return date_labels

    def _parse_date_from_label(self, label: Label) -> Optional[date]:
        """Parse date from a label name like 'Reminders/2025-01-15'."""
        name = label.name
        if not name.startswith(REMINDER_LABEL_PREFIX):
            return None

        suffix = name[len(REMINDER_LABEL_PREFIX):]
        try:
            return date.fromisoformat(suffix)
        except ValueError:
            return None

    def _parse_hour_from_label(self, label: Label) -> Optional[int]:
        """Parse hour from a label name like 'Reminders/11'."""
        name = label.name
        if not name.startswith(REMINDER_LABEL_PREFIX):
            return None

        suffix = name[len(REMINDER_LABEL_PREFIX):]
        if suffix in REMINDER_HOURS:
            return int(suffix)
        return None

    def cleanup_old_labels(self) -> int:
        """
        Clean up date labels from previous days.

        Move threads from old date labels to Outdated, then delete the empty labels.
        Returns the number of threads moved to Outdated.
        """
        today = date.today()
        cutoff_date = today  # Move all reminders from before today
        moved_count = 0

        self._invalidate_label_cache()
        date_labels = self._get_date_labels()

        # Get or create Outdated label
        outdated_label = self._gmail.get_or_create_label(REMINDER_OUTDATED)

        for label in date_labels:
            label_date = self._parse_date_from_label(label)
            if label_date and label_date < cutoff_date:
                # Get threads with this label
                threads = self._gmail.get_threads_with_label(label.id)

                for thread in threads:
                    # Remove date label, add Outdated
                    self._gmail.remove_labels_from_thread(thread.id, [label.id])
                    self._gmail.add_labels_to_thread(thread.id, [outdated_label.id])
                    moved_count += 1

                # Delete the empty label
                try:
                    self._gmail.delete_label(label.id)
                except Exception:
                    pass  # Label might already be deleted or have other threads

        self._invalidate_label_cache()
        self._save_cleanup_date(today)
        return moved_count

    def get_reminders(self, include_future: bool = False) -> list[Reminder]:
        """
        Get all reminders (overdue and upcoming for today).

        Args:
            include_future: If True, also include future reminders (not shown by default).

        Returns:
            List of Reminder objects, sorted by status (overdue first) then scheduled time.
        """
        now = datetime.now()
        today = now.date()
        reminders: list[Reminder] = []

        self._invalidate_label_cache()
        cache = self._get_label_cache()

        # Get Outdated label
        outdated_label = cache.get(REMINDER_OUTDATED)

        # Collect threads from Outdated
        if outdated_label:
            threads = self._gmail.get_threads_with_label(outdated_label.id)
            for thread in threads:
                reminder = self._build_reminder(thread, cache, now)
                if reminder:
                    reminders.append(reminder)

        # Collect threads from date labels (last 7 days + today)
        date_labels = self._get_date_labels()
        seen_thread_ids = {r.thread.id for r in reminders}

        for date_label in date_labels:
            label_date = self._parse_date_from_label(date_label)
            if not label_date:
                continue

            # Skip future dates unless requested
            if label_date > today and not include_future:
                continue

            threads = self._gmail.get_threads_with_label(date_label.id)
            for thread in threads:
                if thread.id in seen_thread_ids:
                    continue

                reminder = self._build_reminder(thread, cache, now)
                if reminder:
                    # Filter based on status
                    if reminder.status == ReminderStatus.FUTURE and not include_future:
                        continue
                    reminders.append(reminder)
                    seen_thread_ids.add(thread.id)

        # Sort: overdue first, then by scheduled datetime
        reminders.sort(key=lambda r: (
            0 if r.status == ReminderStatus.OVERDUE else 1,
            r.scheduled_datetime or datetime.min,
        ))

        return reminders

    def _build_reminder(
        self,
        thread: Thread,
        label_cache: dict[str, Label],
        now: datetime,
    ) -> Optional[Reminder]:
        """Build a Reminder object from a thread."""
        thread_label_ids = self._gmail.get_thread_labels(thread.id)

        # Find reminder labels on this thread
        date_label: Optional[Label] = None
        hour_label: Optional[Label] = None
        is_outdated = False

        # Map label IDs to Label objects
        id_to_label = {label.id: label for label in label_cache.values()}

        for label_id in thread_label_ids:
            label = id_to_label.get(label_id)
            if not label:
                continue

            if label.name == REMINDER_OUTDATED:
                is_outdated = True
            elif label.name in REMINDER_HOUR_LABELS:
                hour_label = label
            elif label.name.startswith(REMINDER_LABEL_PREFIX):
                # Check if it's a date label
                if self._parse_date_from_label(label):
                    date_label = label

        # Must have at least one reminder indicator
        if not is_outdated and not date_label:
            return None

        # Determine scheduled datetime
        scheduled_datetime: Optional[datetime] = None
        if date_label:
            label_date = self._parse_date_from_label(date_label)
            if label_date:
                hour = 11  # Default hour
                if hour_label:
                    parsed_hour = self._parse_hour_from_label(hour_label)
                    if parsed_hour:
                        hour = parsed_hour
                scheduled_datetime = datetime(label_date.year, label_date.month, label_date.day, hour, 0)

        # Determine status
        if is_outdated:
            status = ReminderStatus.OVERDUE
        elif scheduled_datetime:
            if scheduled_datetime <= now:
                status = ReminderStatus.OVERDUE
            elif scheduled_datetime.date() == now.date():
                status = ReminderStatus.UPCOMING
            else:
                status = ReminderStatus.FUTURE
        else:
            status = ReminderStatus.OVERDUE

        # Get sender info from pre-fetched metadata
        sender_email = thread.sender_email or ""
        sender_name = thread.sender_name or ""

        return Reminder(
            thread=thread,
            date_label=date_label,
            hour_label=hour_label,
            is_outdated=is_outdated,
            status=status,
            scheduled_datetime=scheduled_datetime,
            sender_email=sender_email,
            sender_name=sender_name,
        )

    def get_overdue_count(self) -> int:
        """Get the count of overdue reminders."""
        reminders = self.get_reminders()
        return sum(1 for r in reminders if r.status == ReminderStatus.OVERDUE)

    def has_reminder(self, thread_id: str) -> bool:
        """Check if a thread has any reminder labels."""
        cache = self._get_label_cache()
        thread_label_ids = self._gmail.get_thread_labels(thread_id)
        id_to_label = {label.id: label for label in cache.values()}

        for label_id in thread_label_ids:
            label = id_to_label.get(label_id)
            if label and label.name.startswith(REMINDER_LABEL_PREFIX):
                return True
        return False

    def set_reminder(
        self,
        thread_id: str,
        reminder_date: date,
        reminder_hour: int = 11,
    ) -> None:
        """
        Set a reminder on a thread.

        Removes any existing reminder labels first, then adds the new ones.
        Also marks thread as read and removes from inbox.
        """
        self._invalidate_label_cache()

        # Mark as read and archive first (this also removes any existing reminder labels)
        self._gmail.mark_as_read([thread_id], archive=True)

        # Create/get the date label (child of Reminders)
        date_label_name = f"{REMINDER_LABEL_PREFIX}{reminder_date.isoformat()}"
        date_label = self._gmail.get_or_create_label(date_label_name)

        # Get the hour label
        hour_str = f"{reminder_hour:02d}"
        if hour_str not in REMINDER_HOURS:
            hour_str = "11"  # Default to 11 if invalid
        hour_label_name = f"{REMINDER_LABEL_PREFIX}{hour_str}"
        hour_label = self._gmail.get_or_create_label(hour_label_name)

        # Add labels to thread
        self._gmail.add_labels_to_thread(thread_id, [date_label.id, hour_label.id])

        self._invalidate_label_cache()

    def remove_reminder(self, thread_id: str) -> None:
        """Remove all reminder labels from a thread."""
        self._invalidate_label_cache()
        cache = self._get_label_cache()

        # Get current thread labels
        thread_label_ids = self._gmail.get_thread_labels(thread_id)

        # Find reminder labels to remove
        reminder_label_ids = []
        id_to_label = {label.id: label for label in cache.values()}

        for label_id in thread_label_ids:
            label = id_to_label.get(label_id)
            if label and label.name.startswith(REMINDER_LABEL_PREFIX):
                reminder_label_ids.append(label_id)

        if reminder_label_ids:
            self._gmail.remove_labels_from_thread(thread_id, reminder_label_ids)

        self._invalidate_label_cache()

    def reschedule_reminder(
        self,
        thread_id: str,
        new_date: date,
        new_hour: int = 11,
    ) -> None:
        """Reschedule an existing reminder."""
        self.set_reminder(thread_id, new_date, new_hour)

    def check_and_remove_replied_reminders(self) -> int:
        """
        Check all reminder threads and remove reminders from threads with unread messages.

        Returns the number of reminders removed.
        """
        reminders = self.get_reminders(include_future=True)
        removed_count = 0

        for reminder in reminders:
            if reminder.thread.has_unread:
                self.remove_reminder(reminder.thread.id)
                removed_count += 1

        return removed_count

    def get_default_reminder_datetime(self) -> tuple[date, int]:
        """
        Get the default reminder date and hour (+2 days, 11:00).

        Returns:
            Tuple of (date, hour).
        """
        target_date = date.today() + timedelta(days=2)
        return target_date, 11


# Global service instance
_reminder_service: Optional[ReminderService] = None


def get_reminder_service() -> ReminderService:
    """Get the global reminder service instance."""
    global _reminder_service
    if _reminder_service is None:
        _reminder_service = ReminderService()
    return _reminder_service
