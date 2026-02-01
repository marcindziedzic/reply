"""Threads screen - main screen showing unread email threads."""

from datetime import date, datetime
from typing import TYPE_CHECKING, Optional

from textual.binding import Binding

from ..gmail import get_gmail_client
from ..models import Thread
from ..services.reminder_service import get_reminder_service
from .widgets import CENTERED_LIST_CSS, BaseListItem, BaseListScreen

if TYPE_CHECKING:
    from ..app import EmailAssistantApp


class ThreadListItem(BaseListItem):
    """A list item representing an email thread."""

    def __init__(self, thread: Thread, index: int) -> None:
        super().__init__(index=index)
        self.thread = thread

    def get_line_1(self) -> str:
        sender_name = self.thread.sender_name or self.thread.sender_email or "Unknown"
        return f"[{self.index + 1}] [bold cyan]●[/] {sender_name}"

    def get_line_2(self) -> str:
        subject = self.thread.subject
        return f"    {subject[:60]}{'...' if len(subject) > 60 else ''}"

    def get_line_3(self) -> str:
        if self.thread.last_message_date:
            now = datetime.now()
            date = self.thread.last_message_date
            if date.date() == now.date():
                date_str = f"today {date.strftime('%H:%M')}"
            elif (now.date() - date.date()).days == 1:
                date_str = "yesterday"
            else:
                date_str = date.strftime("%Y-%m-%d")
        else:
            date_str = "unknown"
        return f"    {date_str} · {self.thread.message_count} messages"


class ClientsScreen(BaseListScreen[Thread]):
    """Main screen showing list of unread threads."""

    TITLE = "THREADS"
    LOADING_TEXT = "Loading threads from Gmail..."
    EMPTY_TEXT = "No messages to handle"
    LIST_ID = "threads-list"
    EMPTY_ICON = "~~~~~~~~~~\n    \\O/\n     |\n    / \\"
    EMPTY_MESSAGE = "Inbox zero!"
    EMPTY_HINT = "No messages to handle"

    CSS = f"""
    ClientsScreen {{
        background: $surface;
        align: center middle;
    }}
    {CENTERED_LIST_CSS}
    """

    BINDINGS = [
        *BaseListScreen.BASE_BINDINGS,
        Binding("c", "compose_new", "New email"),
        Binding("R", "reminders", "Reminders"),
        Binding("S", "search", "Search"),
        Binding("L", "browse_labels", "Labels"),
        Binding("l", "mark_read", "Mark read"),
        Binding("h", "set_reminder", "Reminder"),
        Binding("d", "delete", "Delete"),
        Binding("r", "refresh", "Refresh"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.user_email = ""
        self._threads_preloaded = False

    async def fetch_items(self) -> list[Thread]:
        """Fetch unread threads from Gmail."""
        gmail = get_gmail_client()
        self.user_email = gmail.get_user_email()

        # Update header with user email
        app = self.app
        if hasattr(app, "title"):
            app.title = f"Email Assistant v0.1 - {self.user_email}"

        # Get and sort threads
        threads = gmail.get_unread_threads()
        threads.sort(
            key=lambda t: t.last_message_date or datetime.min,
            reverse=True,
        )
        return threads

    def create_list_item(self, item: Thread, index: int) -> BaseListItem:
        """Create a thread list item."""
        return ThreadListItem(item, index)

    def on_item_selected(self, item: Thread) -> None:
        """Open thread detail screen."""
        app: "EmailAssistantApp" = self.app  # type: ignore
        app.open_thread_screen(item, self.user_email)

    def get_title_with_count(self) -> str:
        return f"{self.TITLE} ({len(self.items)} unread)"

    def get_empty_title(self) -> str:
        return f"{self.TITLE} (no unread)"

    def on_mount(self) -> None:
        """Handle screen mount."""
        if self._threads_preloaded:
            # Threads already loaded - just display them
            self._display_preloaded()
        else:
            self.load_items()

    def _display_preloaded(self) -> None:
        """Display pre-loaded threads."""
        # Trigger load which will use already set self.items
        self.load_items()

    def action_compose_new(self) -> None:
        """Open new message dialog, then draft screen."""
        from .dialogs import NewMessageDialog

        def handle_result(result: Optional[tuple[str, str]]) -> None:
            if result:
                recipient, subject = result
                app: "EmailAssistantApp" = self.app  # type: ignore
                app.open_new_message_screen(self.user_email, recipient, subject)

        self.app.push_screen(NewMessageDialog(), handle_result)

    def action_reminders(self) -> None:
        """Open reminders screen."""
        app: "EmailAssistantApp" = self.app  # type: ignore
        app.open_reminders_screen()

    def action_delete(self) -> None:
        """Delete the selected thread (move to trash)."""
        index = self._get_selected_index()
        if index is None:
            self.notify("No thread selected", severity="warning")
            return

        thread = self._remove_item_optimistically(index)

        def do_delete():
            gmail = get_gmail_client()
            gmail.trash_thread(thread.id)

        self._run_background_task(do_delete, "Moved to trash", "Delete failed")

    def action_mark_read(self) -> None:
        """Open mark as read dialog for selected thread."""
        # Capture index before dialog opens
        index = self._get_selected_index()
        if index is None:
            self.notify("No thread selected", severity="warning")
            return

        from .dialogs import MarkAsReadDialog

        def handle_result(result: Optional[tuple[bool, Optional[str]]]) -> None:
            if result and result[0]:
                # Index was captured before dialog - safe to use
                if index < len(self.items):
                    thread = self._remove_item_optimistically(index)
                    label_id = result[1]

                    def do_mark_read():
                        gmail = get_gmail_client()
                        gmail.mark_as_read([thread.id], label_id)

                    self._run_background_task(
                        do_mark_read, "Thread marked as read", "Mark read failed"
                    )

        self.app.push_screen(MarkAsReadDialog(), handle_result)

    def action_set_reminder(self) -> None:
        """Open dialog to set a reminder for the selected thread."""
        # Capture index before dialog opens
        index = self._get_selected_index()
        if index is None:
            self.notify("No thread selected", severity="warning")
            return

        from .dialogs import RescheduleDialog

        def handle_result(result: Optional[tuple]) -> None:
            if result:
                reminder_date, reminder_hour = result
                # Index was captured before dialog - safe to use
                if index < len(self.items):
                    thread = self._remove_item_optimistically(index)

                    def do_set_reminder():
                        service = get_reminder_service()
                        service.set_reminder(thread.id, reminder_date, reminder_hour)

                    self._run_background_task(
                        do_set_reminder,
                        f"Reminder set for: {reminder_date.isoformat()} {reminder_hour}:00",
                        "Set reminder failed",
                    )

        self.app.push_screen(RescheduleDialog(), handle_result)

    def action_search(self) -> None:
        """Open search dialog."""
        from .dialogs import SearchDialog

        def handle_result(email: Optional[str]) -> None:
            if email:
                self._open_search_results(email)

        self.app.push_screen(SearchDialog(), handle_result)

    def _open_search_results(self, email: str) -> None:
        """Open search results screen."""
        self.app.push_screen(SearchResultsScreen(email, self.user_email))

    def action_browse_labels(self) -> None:
        """Open label browser dialog."""
        from .dialogs import BrowseLabelsDialog
        from ..models import Label

        def handle_result(label: Optional[Label]) -> None:
            if label:
                self.app.push_screen(
                    LabelThreadsScreen(label.id, label.name, self.user_email)
                )

        self.app.push_screen(BrowseLabelsDialog(), handle_result)


class SearchResultsScreen(BaseListScreen[Thread]):
    """Screen showing search results for threads."""

    TITLE = "RESULTS"
    LOADING_TEXT = "Searching threads..."
    EMPTY_TEXT = "No results"
    LIST_ID = "search-list"
    EMPTY_ICON = "   ?\n  / \\\n |   |\n  \\_/"
    EMPTY_MESSAGE = "No results"
    EMPTY_HINT = "Try a different search"

    CSS = f"""
    SearchResultsScreen {{
        background: $surface;
        align: center middle;
    }}
    {CENTERED_LIST_CSS}
    """

    BINDINGS = [
        *BaseListScreen.BASE_BINDINGS,
        Binding("escape", "go_back", "Back"),
        Binding("q", "go_back", "Back"),
    ]

    def __init__(self, search_email: str, user_email: str) -> None:
        super().__init__()
        self.search_email = search_email
        self.user_email = user_email

    async def fetch_items(self) -> list[Thread]:
        """Search for threads by email."""
        gmail = get_gmail_client()
        # Search for threads from or to this email
        query = f"from:{self.search_email} OR to:{self.search_email}"
        threads = gmail.search_threads(query)
        # Sort by date descending
        threads.sort(
            key=lambda t: t.last_message_date or datetime.min,
            reverse=True,
        )
        return threads

    def create_list_item(self, item: Thread, index: int) -> BaseListItem:
        """Create a thread list item."""
        return ThreadListItem(item, index)

    def on_item_selected(self, item: Thread) -> None:
        """Open thread detail screen."""
        app: "EmailAssistantApp" = self.app  # type: ignore
        app.open_thread_screen(item, self.user_email)

    def get_title_with_count(self) -> str:
        return f"{self.TITLE}: {self.search_email} ({len(self.items)})"

    def get_empty_title(self) -> str:
        return f"{self.TITLE}: {self.search_email} (none)"

    def action_go_back(self) -> None:
        """Go back to previous screen."""
        self.app.pop_screen()


class LabelThreadsScreen(BaseListScreen[Thread]):
    """Screen showing threads with a specific label."""

    TITLE = "LABEL"
    LOADING_TEXT = "Loading threads..."
    EMPTY_TEXT = "No threads with this label"
    LIST_ID = "label-threads-list"
    EMPTY_ICON = "   ?\n  / \\\n |   |\n  \\_/"
    EMPTY_MESSAGE = "No threads"
    EMPTY_HINT = "This label has no threads"

    CSS = f"""
    LabelThreadsScreen {{
        background: $surface;
        align: center middle;
    }}
    {CENTERED_LIST_CSS}
    """

    BINDINGS = [
        *BaseListScreen.BASE_BINDINGS,
        Binding("escape", "go_back", "Back"),
        Binding("q", "go_back", "Back"),
    ]

    def __init__(self, label_id: str, label_name: str, user_email: str) -> None:
        super().__init__()
        self.label_id = label_id
        self.label_name = label_name
        self.user_email = user_email

    async def fetch_items(self) -> list[Thread]:
        """Fetch threads with this label."""
        gmail = get_gmail_client()
        threads = gmail.get_threads_with_label(self.label_id)
        threads.sort(
            key=lambda t: t.last_message_date or datetime.min,
            reverse=True,
        )
        return threads

    def create_list_item(self, item: Thread, index: int) -> BaseListItem:
        """Create a thread list item."""
        return ThreadListItem(item, index)

    def on_item_selected(self, item: Thread) -> None:
        """Open thread detail screen."""
        app: "EmailAssistantApp" = self.app  # type: ignore
        app.open_thread_screen(item, self.user_email)

    def get_title_with_count(self) -> str:
        return f"{self.label_name} ({len(self.items)})"

    def get_empty_title(self) -> str:
        return f"{self.label_name} (none)"

    def action_go_back(self) -> None:
        """Go back to previous screen."""
        self.app.pop_screen()
