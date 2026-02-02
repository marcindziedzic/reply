"""Reminders screen - shows list of follow-up reminders."""

from datetime import date, datetime, time
from typing import TYPE_CHECKING, Optional

from textual.binding import Binding
from textual.widgets import ListView, Static

from ..gmail import get_gmail_client
from ..services.reminder_service import (
    Reminder,
    ReminderStatus,
    get_reminder_service,
)
from .widgets import CENTERED_LIST_CSS, BaseListItem, BaseListScreen

if TYPE_CHECKING:
    from ..app import EmailAssistantApp


class ReminderListItem(BaseListItem):
    """A list item representing a reminder."""

    def __init__(self, reminder: Reminder, index: int) -> None:
        super().__init__(index=index)
        self.reminder = reminder

    def get_line_1(self) -> str:
        if self.reminder.status == ReminderStatus.OVERDUE:
            status_icon = "[bold red]![/]"
        else:
            status_icon = "[bold cyan]●[/]"
        sender_display = self.reminder.sender_name or self.reminder.sender_email or "Unknown"
        return f"[{self.index + 1}] {status_icon} {sender_display}"

    def get_line_2(self) -> str:
        subject = self.reminder.thread.subject
        return f"    {subject[:60]}{'...' if len(subject) > 60 else ''}"

    def get_line_3(self) -> str:
        return f"    {self._format_time_info()}"

    def _format_time_info(self) -> str:
        """Format the time information for display."""
        now = datetime.now()

        if self.reminder.is_outdated and not self.reminder.scheduled_datetime:
            return "Overdue (archive)"

        if not self.reminder.scheduled_datetime:
            return "No due date"

        scheduled = self.reminder.scheduled_datetime
        scheduled_date = scheduled.date()
        today = now.date()

        # Format scheduled time
        if scheduled_date == today:
            day_str = "Today"
        elif (scheduled_date - today).days == 1:
            day_str = "Tomorrow"
        elif (today - scheduled_date).days == 1:
            day_str = "Yesterday"
        else:
            # English day names
            days_en = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            months_en = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
            day_name = days_en[scheduled_date.weekday()]
            month_name = months_en[scheduled_date.month - 1]
            day_str = f"{day_name}, {month_name} {scheduled_date.day}"

        time_str = f"{scheduled.hour:02d}:00"

        # Status suffix
        if self.reminder.status == ReminderStatus.OVERDUE:
            diff = now - scheduled
            if diff.days > 0:
                status_suffix = f"Overdue {diff.days} days"
            else:
                hours = diff.seconds // 3600
                if hours > 0:
                    status_suffix = f"Overdue {hours}h"
                else:
                    minutes = diff.seconds // 60
                    status_suffix = f"Overdue {minutes}min"
        elif self.reminder.status == ReminderStatus.UPCOMING:
            diff = scheduled - now
            hours = diff.seconds // 3600
            if hours > 0:
                status_suffix = f"In {hours}h"
            else:
                minutes = diff.seconds // 60
                status_suffix = f"In {minutes}min"
        else:
            status_suffix = ""

        if status_suffix:
            return f"Scheduled: {day_str} {time_str} - {status_suffix}"
        else:
            return f"Scheduled: {day_str} {time_str}"


class RemindersScreen(BaseListScreen[Reminder]):
    """Screen showing list of reminders."""

    TITLE = "REMINDERS"
    LOADING_TEXT = "Loading reminders..."
    EMPTY_TEXT = "No reminders to display"
    LIST_ID = "reminders-list"
    EMPTY_ICON = "   ___\n  /   \\\n |     |\n  \\___/"
    EMPTY_MESSAGE = "No reminders"
    EMPTY_HINT = "Use 'f' on a thread to set a reminder"

    CSS = f"""
    RemindersScreen {{
        background: $surface;
        align: center middle;
    }}
    {CENTERED_LIST_CSS}
    """

    BINDINGS = [
        *BaseListScreen.BASE_BINDINGS,
        Binding("I", "go_inbox", "Inbox"),
        Binding("escape", "go_inbox", "Inbox", show=False),
        Binding("h", "reschedule", "Reschedule"),
        Binding("l", "assign_label", "Label"),
        Binding("d", "delete_reminder", "Delete"),
        Binding("r", "refresh", "Refresh"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.user_email = ""
        self._overdue_count = 0

    async def fetch_items(self) -> list[Reminder]:
        """Fetch reminders."""
        gmail = get_gmail_client()
        self.user_email = gmail.get_user_email()

        service = get_reminder_service()
        reminders = service.get_reminders()

        # Count overdue
        self._overdue_count = sum(
            1 for r in reminders
            if r.status == ReminderStatus.OVERDUE
        )

        return reminders

    def create_list_item(self, item: Reminder, index: int) -> BaseListItem:
        """Create a reminder list item."""
        return ReminderListItem(item, index)

    def on_item_selected(self, item: Reminder) -> None:
        """Open thread detail screen for this reminder."""
        app: "EmailAssistantApp" = self.app  # type: ignore
        app.open_thread_screen(item.thread, self.user_email, reminder=item)

    def get_title_with_count(self) -> str:
        if self._overdue_count > 0:
            return f"{self.TITLE} ({self._overdue_count} overdue)"
        return f"{self.TITLE} ({len(self.items)})"

    def get_empty_title(self) -> str:
        return f"{self.TITLE} (none)"

    def action_go_inbox(self) -> None:
        """Go back to inbox (ClientsScreen)."""
        self.app.pop_screen()

    def action_delete_reminder(self) -> None:
        """Delete the selected reminder and move thread back to inbox."""
        index = self._get_selected_index()
        if index is None:
            self.notify("No reminder selected", severity="warning")
            return

        reminder = self._remove_item_optimistically(index)

        def do_delete():
            service = get_reminder_service()
            service.remove_reminder(reminder.thread.id)

            gmail = get_gmail_client()
            gmail.add_labels_to_thread(reminder.thread.id, ["INBOX", "UNREAD"])

        self._run_background_task(
            do_delete, "Reminder deleted - thread moved to Inbox", "Delete failed"
        )

    def action_reschedule(self) -> None:
        """Reschedule the selected reminder."""
        # Capture index before dialog opens
        index = self._get_selected_index()
        if index is None:
            self.notify("No reminder selected", severity="warning")
            return

        from .dialogs import RescheduleDialog

        def handle_result(result: Optional[tuple]) -> None:
            if result:
                new_date, new_hour = result
                # Index was captured before dialog - get reminder if still valid
                if index < len(self.items):
                    today = date.today()

                    if new_date == today:
                        # Rescheduled for today - update in place
                        reminder = self.items[index]

                        # Optimistically update reminder in memory
                        new_datetime = datetime.combine(new_date, time(hour=new_hour))
                        reminder.scheduled_datetime = new_datetime
                        reminder.is_outdated = False

                        # Update status based on new time
                        now = datetime.now()
                        if new_datetime < now:
                            reminder.status = ReminderStatus.OVERDUE
                        elif (new_datetime - now).total_seconds() < 3600:
                            reminder.status = ReminderStatus.UPCOMING
                        else:
                            reminder.status = ReminderStatus.FUTURE

                        # Update the list item display
                        self._refresh_list_item_display(index)
                    else:
                        # Rescheduled for another day - remove from list
                        reminder = self._remove_item_optimistically(index)

                    def do_reschedule():
                        service = get_reminder_service()
                        service.reschedule_reminder(reminder.thread.id, new_date, new_hour)

                    self._run_background_task(
                        do_reschedule,
                        f"Rescheduled to: {new_date.isoformat()} {new_hour}:00",
                        "Reschedule failed",
                    )

        self.app.push_screen(RescheduleDialog(), handle_result)

    def _refresh_list_item_display(self, index: int) -> None:
        """Refresh the display of a list item after in-memory update."""
        items_list = self.query_one(f"#{self.LIST_ID}", ListView)
        list_items = list(items_list.children)
        if 0 <= index < len(list_items):
            list_item = list_items[index]
            if isinstance(list_item, ReminderListItem):
                # Update line 1 (status icon may have changed)
                line_1 = list_item.query_one(".item-line-1", Static)
                line_1.update(list_item.get_line_1())
                # Update line 3 (time info)
                line_3 = list_item.query_one(".item-line-3", Static)
                line_3.update(list_item.get_line_3())

    def action_assign_label(self) -> None:
        """Assign a label to the selected reminder's thread."""
        # Capture index before dialog opens
        index = self._get_selected_index()
        if index is None:
            self.notify("No reminder selected", severity="warning")
            return

        from .dialogs import MarkAsReadDialog

        def handle_result(result: Optional[tuple[bool, Optional[str]]]) -> None:
            if result and result[0] and result[1]:
                # Index was captured before dialog - get reminder if still valid
                if index < len(self.items):
                    reminder = self.items[index]
                    label_id = result[1]

                    def do_assign_label():
                        gmail = get_gmail_client()
                        gmail.add_labels_to_thread(reminder.thread.id, [label_id])

                    self._run_background_task(
                        do_assign_label, "Label assigned", "Assign label failed"
                    )

        self.app.push_screen(MarkAsReadDialog(), handle_result)
