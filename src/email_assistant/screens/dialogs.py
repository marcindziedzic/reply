"""Dialogs for Email Assistant."""

from datetime import date, timedelta
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ..services.snippet_service import Snippet

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Checkbox, Input, Label, ListItem, ListView, RadioButton, RadioSet, Static

from ..gmail import get_gmail_client
from ..services.context_service import get_context_service
from ..models import Label as GmailLabel
from .widgets import ContactsInput


class HintsDialog(ModalScreen[Optional[tuple[str, list[str]]]]):
    """Dialog for entering generation hints.

    Used for both initial generation and regeneration.
    Returns tuple of (hints, selected_optional_files) or None if cancelled.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    CSS = """
    HintsDialog, GenerateDialog, RegenerateDialog {
        align: center middle;
    }

    #hints-dialog {
        width: 70;
        height: auto;
        max-height: 30;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }

    #hints-title {
        text-style: bold;
        margin-bottom: 1;
    }

    #hints-label {
        margin-bottom: 1;
    }

    #hints-input {
        width: 100%;
        margin-bottom: 1;
    }

    #optional-files-label {
        margin-top: 1;
        margin-bottom: 0;
        color: $text-muted;
    }

    .optional-file-checkbox {
        padding: 0;
        margin: 0;
    }

    #hints-hint {
        color: $text-muted;
        text-align: center;
        margin-top: 1;
    }
    """

    def __init__(
        self,
        title: str = "Generate response",
        label: str = "Additional hints (optional):",
    ) -> None:
        super().__init__()
        self.dialog_title = title
        self.dialog_label = label
        self._optional_files = get_context_service().list_optional_files()

    def compose(self) -> ComposeResult:
        """Compose the dialog."""
        with Vertical(id="hints-dialog"):
            yield Static(self.dialog_title, id="hints-title")
            yield Label(self.dialog_label, id="hints-label")
            yield Input(
                placeholder="e.g. Suggest cheaper monitors, mention discounts...",
                id="hints-input",
            )
            if self._optional_files:
                yield Label("Include context:", id="optional-files-label")
                for idx, filename in enumerate(self._optional_files):
                    yield Checkbox(
                        filename,
                        classes="optional-file-checkbox",
                        id=f"opt-file-{idx}",
                    )
            yield Static("[Enter] generate  [Esc] cancel", id="hints-hint")

    def on_mount(self) -> None:
        """Handle mount."""
        self.query_one("#hints-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission - generate on Enter."""
        self._submit()

    def _submit(self) -> None:
        """Submit the dialog."""
        hints_input = self.query_one("#hints-input", Input)
        hints = hints_input.value.strip()

        selected_files: list[str] = []
        for idx, filename in enumerate(self._optional_files):
            checkbox = self.query_one(f"#opt-file-{idx}", Checkbox)
            if checkbox.value:
                selected_files.append(filename)

        self.dismiss((hints, selected_files))

    def action_cancel(self) -> None:
        """Cancel the dialog."""
        self.dismiss(None)


# Backward-compatible aliases
class GenerateDialog(HintsDialog):
    """Dialog for generating response with optional hints."""

    def __init__(self) -> None:
        super().__init__(
            title="Generate response",
            label="Additional hints (optional):",
        )


class RegenerateDialog(HintsDialog):
    """Dialog for regenerating response with hints."""

    def __init__(self) -> None:
        super().__init__(
            title="Regenerate response",
            label="Hints for new version (optional):",
        )


class LabelListItem(ListItem):
    """A list item representing a Gmail label."""

    def __init__(self, label: Optional[GmailLabel] = None) -> None:
        super().__init__()
        self.label = label  # None means "no label" option

    def compose(self) -> ComposeResult:
        if self.label is None:
            yield Static("(no label)")
        else:
            yield Static(self.label.name)


class MarkAsReadDialog(ModalScreen[Optional[tuple[bool, Optional[str]]]]):
    """Dialog for marking messages as read with optional label."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("down", "focus_list", "List", show=False),
    ]

    CSS = """
    MarkAsReadDialog {
        align: center middle;
    }

    #mark-read-dialog {
        width: 60;
        height: 30;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }

    #mark-read-title {
        text-style: bold;
        margin-bottom: 1;
    }

    #search-label {
        margin-bottom: 0;
    }

    #search-input {
        width: 100%;
        margin-bottom: 1;
    }

    #labels-container {
        height: 1fr;
        margin-bottom: 1;
        background: $panel;
        border: solid $secondary;
    }

    #labels-list {
        height: 100%;
        background: transparent;
    }

    #labels-list > ListItem {
        padding: 0 1;
    }

    #labels-list > ListItem.--highlight {
        background: $accent 50%;
    }

    #loading-labels {
        text-align: center;
        padding: 2;
    }

    #hint-label {
        color: $text-muted;
        text-align: center;
        margin-top: 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.all_labels: list[GmailLabel] = []
        self.filtered_labels: list[GmailLabel] = []
        self.selected_label_id: Optional[str] = None

    def compose(self) -> ComposeResult:
        """Compose the dialog."""
        with Vertical(id="mark-read-dialog"):
            yield Static("Mark as read", id="mark-read-title")
            yield Label("Search label:", id="search-label")
            yield Input(placeholder="type label name...", id="search-input")
            with VerticalScroll(id="labels-container"):
                yield Static("Loading labels...", id="loading-labels")
                yield ListView(id="labels-list")
            yield Static("[↑↓] select  [Enter] confirm  [Esc] cancel", id="hint-label")

    def on_mount(self) -> None:
        """Handle mount."""
        self.query_one("#search-input", Input).focus()
        self.load_labels()

    @work(exclusive=True)
    async def load_labels(self) -> None:
        """Load Gmail labels."""
        loading = self.query_one("#loading-labels", Static)

        try:
            gmail = get_gmail_client()
            self.all_labels = gmail.get_user_labels()
            self.filtered_labels = self.all_labels.copy()

            loading.display = False
            await self._populate_labels_list()

        except Exception as e:
            loading.update(f"Error: {e}")

    async def _populate_labels_list(self, filter_text: str = "") -> None:
        """Populate the labels list with filtered labels."""
        labels_list = self.query_one("#labels-list", ListView)

        await labels_list.clear()

        filter_lower = filter_text.lower().strip()
        if filter_lower:
            self.filtered_labels = [
                label for label in self.all_labels
                if filter_lower in label.name.lower()
            ]
        else:
            self.filtered_labels = self.all_labels.copy()

        # Add "no label" option first
        await labels_list.append(LabelListItem(None))

        for label in self.filtered_labels:
            await labels_list.append(LabelListItem(label))

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle search input changes."""
        if event.input.id == "search-input":
            self._filter_labels(event.value)

    @work(exclusive=True)
    async def _filter_labels(self, filter_text: str) -> None:
        """Filter labels based on search text."""
        await self._populate_labels_list(filter_text)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle label selection - submit immediately on Enter."""
        if isinstance(event.item, LabelListItem):
            if event.item.label is None:
                self.selected_label_id = None
            else:
                self.selected_label_id = event.item.label.id

            self.dismiss((True, self.selected_label_id))

    def action_focus_list(self) -> None:
        """Focus the labels list for keyboard navigation."""
        labels_list = self.query_one("#labels-list", ListView)
        labels_list.focus()

    def on_key(self, event) -> None:
        """Handle key events for navigation."""
        if event.key == "down":
            search_input = self.query_one("#search-input", Input)
            if search_input.has_focus:
                labels_list = self.query_one("#labels-list", ListView)
                labels_list.focus()
                event.prevent_default()
        elif event.key == "up":
            labels_list = self.query_one("#labels-list", ListView)
            if labels_list.has_focus and labels_list.index == 0:
                self.query_one("#search-input", Input).focus()
                event.prevent_default()

    def action_cancel(self) -> None:
        """Cancel the dialog."""
        self.dismiss(None)


class BrowseLabelsDialog(ModalScreen[Optional[GmailLabel]]):
    """Dialog for browsing and selecting a label."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("down", "focus_list", "List", show=False),
    ]

    CSS = """
    BrowseLabelsDialog {
        align: center middle;
    }

    #browse-labels-dialog {
        width: 60;
        height: 30;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }

    #browse-labels-title {
        text-style: bold;
        margin-bottom: 1;
    }

    #browse-search-label {
        margin-bottom: 0;
    }

    #browse-search-input {
        width: 100%;
        margin-bottom: 1;
    }

    #browse-labels-container {
        height: 1fr;
        margin-bottom: 1;
        background: $panel;
        border: solid $secondary;
    }

    #browse-labels-list {
        height: 100%;
        background: transparent;
    }

    #browse-labels-list > ListItem {
        padding: 0 1;
    }

    #browse-labels-list > ListItem.-highlight {
        background: $accent 50%;
    }

    #browse-loading-labels {
        text-align: center;
        padding: 2;
    }

    #browse-hint-label {
        color: $text-muted;
        text-align: center;
        margin-top: 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.all_labels: list[GmailLabel] = []
        self.filtered_labels: list[GmailLabel] = []

    def compose(self) -> ComposeResult:
        """Compose the dialog."""
        with Vertical(id="browse-labels-dialog"):
            yield Static("Browse labels", id="browse-labels-title")
            yield Label("Search:", id="browse-search-label")
            yield Input(placeholder="type label name...", id="browse-search-input")
            with VerticalScroll(id="browse-labels-container"):
                yield Static("Loading labels...", id="browse-loading-labels")
                yield ListView(id="browse-labels-list")
            yield Static("[↑↓] select  [Enter] open  [Esc] cancel", id="browse-hint-label")

    def on_mount(self) -> None:
        """Handle mount."""
        self.query_one("#browse-search-input", Input).focus()
        self.load_labels()

    @work(exclusive=True)
    async def load_labels(self) -> None:
        """Load Gmail labels."""
        loading = self.query_one("#browse-loading-labels", Static)

        try:
            gmail = get_gmail_client()
            self.all_labels = gmail.get_user_labels()
            self.filtered_labels = self.all_labels.copy()

            loading.display = False
            await self._populate_labels_list()

        except Exception as e:
            loading.update(f"Error: {e}")

    async def _populate_labels_list(self, filter_text: str = "") -> None:
        """Populate the labels list with filtered labels."""
        labels_list = self.query_one("#browse-labels-list", ListView)

        await labels_list.clear()

        filter_lower = filter_text.lower().strip()
        if filter_lower:
            self.filtered_labels = [
                label for label in self.all_labels
                if filter_lower in label.name.lower()
            ]
        else:
            self.filtered_labels = self.all_labels.copy()

        for label in self.filtered_labels:
            await labels_list.append(LabelListItem(label))

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle search input changes."""
        if event.input.id == "browse-search-input":
            self._filter_labels(event.value)

    @work(exclusive=True)
    async def _filter_labels(self, filter_text: str) -> None:
        """Filter labels based on search text."""
        await self._populate_labels_list(filter_text)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle label selection."""
        if isinstance(event.item, LabelListItem) and event.item.label:
            self.dismiss(event.item.label)

    def action_focus_list(self) -> None:
        """Focus the labels list for keyboard navigation."""
        labels_list = self.query_one("#browse-labels-list", ListView)
        labels_list.focus()

    def on_key(self, event) -> None:
        """Handle key events for navigation."""
        if event.key == "down":
            search_input = self.query_one("#browse-search-input", Input)
            if search_input.has_focus:
                labels_list = self.query_one("#browse-labels-list", ListView)
                labels_list.focus()
                event.prevent_default()
        elif event.key == "up":
            labels_list = self.query_one("#browse-labels-list", ListView)
            if labels_list.has_focus and labels_list.index == 0:
                self.query_one("#browse-search-input", Input).focus()
                event.prevent_default()

    def action_cancel(self) -> None:
        """Cancel the dialog."""
        self.dismiss(None)


class SendConfirmDialog(ModalScreen[bool]):
    """Dialog to confirm sending an email."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("enter", "confirm", "Send"),
    ]

    CSS = """
    SendConfirmDialog {
        align: center middle;
    }

    #send-dialog {
        width: 50;
        height: auto;
        max-height: 12;
        background: $surface;
        border: solid $warning;
        padding: 1 2;
    }

    #send-title {
        text-style: bold;
        margin-bottom: 1;
        color: $warning;
    }

    #send-recipient {
        margin-bottom: 1;
    }

    #send-hint {
        color: $text-muted;
        text-align: center;
        margin-top: 1;
    }
    """

    def __init__(self, recipient: str, subject: str) -> None:
        super().__init__()
        self.recipient = recipient
        self.subject = subject

    def compose(self) -> ComposeResult:
        """Compose the dialog."""
        with Vertical(id="send-dialog"):
            yield Static("Send message?", id="send-title")
            yield Static(f"To: {self.recipient}", id="send-recipient")
            yield Static(f"Subject: {self.subject[:40]}{'...' if len(self.subject) > 40 else ''}")
            yield Static("[Enter] send  [Esc] cancel", id="send-hint")

    def action_confirm(self) -> None:
        """Confirm sending."""
        self.dismiss(True)

    def action_cancel(self) -> None:
        """Cancel sending."""
        self.dismiss(False)


class DeleteConfirmDialog(ModalScreen[bool]):
    """Dialog to confirm deleting a thread."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("enter", "confirm", "Delete"),
        Binding("d", "confirm", "Delete", show=False),
    ]

    CSS = """
    DeleteConfirmDialog {
        align: center middle;
    }

    #delete-dialog {
        width: 50;
        height: auto;
        max-height: 12;
        background: $surface;
        border: solid $error;
        padding: 1 2;
    }

    #delete-title {
        text-style: bold;
        margin-bottom: 1;
        color: $error;
    }

    #delete-subject {
        margin-bottom: 1;
    }

    #delete-hint {
        color: $text-muted;
        text-align: center;
        margin-top: 1;
    }
    """

    def __init__(self, subject: str, is_reminder: bool = False) -> None:
        super().__init__()
        self.subject = subject
        self.is_reminder = is_reminder

    def compose(self) -> ComposeResult:
        """Compose the dialog."""
        title = "Delete reminder?" if self.is_reminder else "Delete thread?"
        with Vertical(id="delete-dialog"):
            yield Static(title, id="delete-title")
            yield Static(f"Subject: {self.subject[:40]}{'...' if len(self.subject) > 40 else ''}", id="delete-subject")
            yield Static("[Enter/d] delete  [Esc] cancel", id="delete-hint")

    def action_confirm(self) -> None:
        """Confirm deletion."""
        self.dismiss(True)

    def action_cancel(self) -> None:
        """Cancel deletion."""
        self.dismiss(False)


class WarningDialog(ModalScreen[None]):
    """Dialog to show a warning message in the center of the screen."""

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("enter", "close", "Close"),
    ]

    CSS = """
    WarningDialog {
        align: center middle;
    }

    #warning-dialog {
        width: 60;
        height: auto;
        max-height: 15;
        background: $surface;
        border: solid $warning;
        padding: 1 2;
    }

    #warning-title {
        text-style: bold;
        margin-bottom: 1;
        color: $warning;
    }

    #warning-message {
        margin-bottom: 1;
    }

    #warning-hint {
        color: $text-muted;
        text-align: center;
        margin-top: 1;
    }
    """

    def __init__(self, title: str, message: str) -> None:
        super().__init__()
        self.title_text = title
        self.message = message

    def compose(self) -> ComposeResult:
        """Compose the dialog."""
        with Vertical(id="warning-dialog"):
            yield Static(self.title_text, id="warning-title")
            yield Static(self.message, id="warning-message")
            yield Static("[Enter/Esc] close", id="warning-hint")

    def action_close(self) -> None:
        """Close the dialog."""
        self.dismiss(None)


class RescheduleDialog(ModalScreen[Optional[tuple[date, int]]]):
    """Dialog for rescheduling a reminder (selecting date and hour)."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("enter", "confirm", "Confirm", show=False),
    ]

    CSS = """
    RescheduleDialog {
        align: center middle;
    }

    #reschedule-dialog {
        width: 60;
        height: auto;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }

    #reschedule-title {
        text-style: bold;
        margin-bottom: 1;
    }

    .section-label {
        text-style: bold;
        margin-bottom: 0;
        margin-top: 1;
    }

    RadioSet {
        background: transparent;
        border: none;
        height: auto;
    }

    RadioSet:focus {
        border: none;
    }

    RadioButton {
        background: transparent;
        padding: 0;
        margin: 0;
    }

    #hint-label {
        color: $text-muted;
        text-align: center;
        margin-top: 1;
    }
    """

    HOURS = [9, 11, 13, 15, 17]

    def __init__(self, for_sent_message: bool = False) -> None:
        """Initialize the dialog.

        Args:
            for_sent_message: If True, defaults to "In 2 days" at 11:00 (after sending).
                              If False, defaults to "Today" at next available hour slot.
        """
        super().__init__()
        self.for_sent_message = for_sent_message
        self._date_options: list[tuple[str, date]] = []

        # Calculate defaults based on context
        if for_sent_message:
            # After sending: +2 days at 11:00
            self.default_date_index = 2  # "In 2 days"
            self.selected_hour = 11
        else:
            # Manual reminder: today at next slot
            self.default_date_index = 0  # "Today"
            self.selected_hour = self._get_next_hour_slot()

        self.selected_date: date = date.today()  # Will be set properly in compose()

    def _get_next_hour_slot(self) -> int:
        """Get the next available hour slot after current time."""
        from datetime import datetime
        current_hour = datetime.now().hour
        for hour in self.HOURS:
            if hour > current_hour:
                return hour
        # If all slots passed, return first slot (for tomorrow)
        return self.HOURS[0]

    def _calculate_date_options(self) -> list[tuple[str, date]]:
        """Calculate the date options based on today's date."""
        today = date.today()
        options = []

        # Today
        options.append(("Today", today))

        # Tomorrow
        options.append(("Tomorrow", today + timedelta(days=1)))

        # In 2 days
        options.append(("In 2 days", today + timedelta(days=2)))

        # Next Friday (if today is Friday, then next Friday)
        days_until_friday = (4 - today.weekday()) % 7
        if days_until_friday == 0:
            days_until_friday = 7  # Next Friday
        next_friday = today + timedelta(days=days_until_friday)
        options.append(("Friday", next_friday))

        # Next week (Monday)
        days_until_monday = (7 - today.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7  # Next Monday
        next_monday = today + timedelta(days=days_until_monday)
        options.append(("Monday", next_monday))

        # In two weeks
        two_weeks = today + timedelta(days=14)
        options.append(("In 2 weeks", two_weeks))

        return options

    def compose(self) -> ComposeResult:
        """Compose the dialog."""
        self._date_options = self._calculate_date_options()

        # Set selected_date based on default index
        if 0 <= self.default_date_index < len(self._date_options):
            self.selected_date = self._date_options[self.default_date_index][1]

        with Vertical(id="reschedule-dialog"):
            yield Static("Set reminder", id="reschedule-title")

            yield Static("When:", classes="section-label")
            with RadioSet(id="date-radioset"):
                for i, (label, d) in enumerate(self._date_options):
                    days_en = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
                    months_en = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                 "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
                    day_name = days_en[d.weekday()]
                    month_name = months_en[d.month - 1]
                    full_label = f"{label} ({day_name}, {month_name} {d.day})"
                    yield RadioButton(full_label, id=f"date-{i}", value=(i == self.default_date_index))

            yield Static("Hour:", classes="section-label")
            with RadioSet(id="hour-radioset"):
                for hour in self.HOURS:
                    yield RadioButton(
                        f"{hour:02d}:00",
                        id=f"hour-{hour}",
                        value=(hour == self.selected_hour),
                    )

            yield Static("Tab: switch | Enter: ok | Esc: cancel", id="hint-label")

    def on_mount(self) -> None:
        """Handle mount - focus on date selection."""
        self.query_one("#date-radioset", RadioSet).focus()

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        """Handle radio button selection."""
        if event.pressed is None:
            return

        btn_id = event.pressed.id or ""

        if btn_id.startswith("date-"):
            idx_str = btn_id[5:]  # Remove "date-" prefix
            try:
                idx = int(idx_str)
                if 0 <= idx < len(self._date_options):
                    self.selected_date = self._date_options[idx][1]
            except ValueError:
                pass
        elif btn_id.startswith("hour-"):
            hour_str = btn_id[5:]  # Remove "hour-" prefix
            try:
                self.selected_hour = int(hour_str)
            except ValueError:
                pass

    def on_key(self, event) -> None:
        """Handle key events - Enter to confirm, Escape to cancel."""
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            self.action_confirm()
        elif event.key == "escape":
            event.prevent_default()
            event.stop()
            self.action_cancel()

    def action_confirm(self) -> None:
        """Confirm the selection."""
        self.dismiss((self.selected_date, self.selected_hour))

    def action_cancel(self) -> None:
        """Cancel the dialog."""
        self.dismiss(None)


class ReminderConfirmDialog(ModalScreen[Optional[str]]):
    """Dialog shown after sending a message to confirm/change reminder."""

    BINDINGS = [
        Binding("escape", "accept", "OK", show=False),
        Binding("enter", "accept", "OK"),
        Binding("z", "change", "Change time"),
    ]

    CSS = """
    ReminderConfirmDialog {
        align: center middle;
    }

    #confirm-dialog {
        width: 65;
        height: auto;
        max-height: 15;
        background: $surface;
        border: solid $success;
        padding: 1 2;
    }

    #confirm-title {
        text-style: bold;
        margin-bottom: 1;
        color: $success;
    }

    #reminder-info {
        margin-bottom: 1;
    }

    #hint-label {
        color: $text-muted;
        text-align: center;
        margin-top: 1;
    }
    """

    def __init__(self, reminder_date: date, reminder_hour: int) -> None:
        super().__init__()
        self.reminder_date = reminder_date
        self.reminder_hour = reminder_hour

    def compose(self) -> ComposeResult:
        """Compose the dialog."""
        # Format the date
        days_en = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        months_en = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

        day_name = days_en[self.reminder_date.weekday()]
        month_name = months_en[self.reminder_date.month - 1]
        date_str = f"{day_name}, {month_name} {self.reminder_date.day}"
        time_str = f"{self.reminder_hour:02d}:00"

        with Vertical(id="confirm-dialog"):
            yield Static("Message sent!", id="confirm-title")
            yield Static(
                f"Reminder set for: {date_str} at {time_str}",
                id="reminder-info",
            )
            yield Static("[Enter] ok  [z] change time", id="hint-label")

    def action_accept(self) -> None:
        """Accept the default reminder."""
        self.dismiss("accept")

    def action_change(self) -> None:
        """Request to change the reminder time."""
        self.dismiss("change")


class SnippetListItem(ListItem):
    """A list item representing a snippet or category header."""

    def __init__(
        self,
        snippet: Optional["Snippet"] = None,
        category_header: str = "",
        is_header: bool = False,
    ) -> None:
        super().__init__()
        self.snippet = snippet
        self.category_header = category_header
        self.is_header = is_header

    def compose(self) -> ComposeResult:
        if self.is_header:
            yield Static(f"[bold]{self.category_header}/[/bold]")
        elif self.snippet:
            # Indent snippet titles under category
            prefix = "  " if self.snippet.category else ""
            yield Static(f"{prefix}{self.snippet.title}")


class SnippetDialog(ModalScreen[Optional["Snippet"]]):
    """Dialog for selecting and inserting a snippet."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("r", "refresh", "Refresh"),
    ]

    CSS = """
    SnippetDialog {
        align: center middle;
    }

    #snippet-dialog {
        width: 80;
        height: 35;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }

    #snippet-title {
        text-style: bold;
        margin-bottom: 1;
    }

    #search-container {
        height: auto;
        margin-bottom: 1;
    }

    #search-input {
        width: 100%;
    }

    #content-container {
        height: 1fr;
    }

    #list-container {
        width: 1fr;
        height: 100%;
        background: $panel;
        border: solid $secondary;
    }

    #snippet-list {
        height: 100%;
        background: transparent;
    }

    #snippet-list > ListItem {
        padding: 0 1;
    }

    #snippet-list > ListItem.--highlight {
        background: $accent 50%;
    }

    #preview-container {
        width: 1fr;
        height: 100%;
        margin-left: 1;
        background: $panel;
        border: solid $secondary;
        padding: 1;
    }

    #preview-title {
        text-style: bold;
        margin-bottom: 1;
    }

    #preview-content {
        height: 1fr;
        overflow: auto;
    }

    #hint-label {
        color: $text-muted;
        text-align: center;
        margin-top: 1;
    }

    .category-header {
        color: $text-muted;
        text-style: bold;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.all_snippets: list["Snippet"] = []
        self.filtered_items: list[SnippetListItem] = []
        self.selected_snippet: Optional["Snippet"] = None

    def compose(self) -> ComposeResult:
        """Compose the dialog."""
        with Vertical(id="snippet-dialog"):
            yield Static("Insert snippet", id="snippet-title")
            with Container(id="search-container"):
                yield Input(placeholder="type to search...", id="search-input")
            with Horizontal(id="content-container"):
                with VerticalScroll(id="list-container"):
                    yield ListView(id="snippet-list")
                with Vertical(id="preview-container"):
                    yield Static("Preview:", id="preview-title")
                    yield Static("", id="preview-content")
            yield Static("(↑↓) select  (Enter) insert  (r) refresh  (Esc) cancel", id="hint-label")

    def on_mount(self) -> None:
        """Handle mount."""
        self.query_one("#search-input", Input).focus()
        self._load_snippets()

    @work(exclusive=True)
    async def _load_snippets(self) -> None:
        """Load snippets from disk."""
        from ..services.snippet_service import get_snippet_service

        service = get_snippet_service()
        self.all_snippets = service.get_snippets()
        await self._populate_list()

    async def _populate_list(self, filter_text: str = "") -> None:
        """Populate the snippet list, optionally filtered."""
        from ..services.snippet_service import get_snippet_service

        snippet_list = self.query_one("#snippet-list", ListView)
        await snippet_list.clear()

        service = get_snippet_service()

        if filter_text:
            # Search mode - flat list of matching snippets
            matching = service.search_snippets(filter_text)
            for snippet in matching:
                item = SnippetListItem(snippet=snippet)
                await snippet_list.append(item)
        else:
            # Normal mode - grouped by category
            by_category = service.get_snippets_by_category()

            # Sort categories, empty string (uncategorized) last
            categories = sorted(by_category.keys(), key=lambda c: (c == "", c.lower()))

            for category in categories:
                snippets = by_category[category]
                if category:
                    # Add category header
                    header_item = SnippetListItem(category_header=category, is_header=True)
                    header_item.disabled = True  # Can't select headers
                    await snippet_list.append(header_item)

                for snippet in snippets:
                    item = SnippetListItem(snippet=snippet)
                    await snippet_list.append(item)

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle search input changes."""
        if event.input.id == "search-input":
            self._filter_snippets(event.value)

    @work(exclusive=True)
    async def _filter_snippets(self, filter_text: str) -> None:
        """Filter snippets based on search text."""
        await self._populate_list(filter_text)

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        """Handle snippet highlight - show preview."""
        if event.item and isinstance(event.item, SnippetListItem):
            if event.item.snippet:
                self.selected_snippet = event.item.snippet
                self._update_preview(event.item.snippet)
            else:
                self.selected_snippet = None
                self._clear_preview()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle snippet selection - insert it."""
        if isinstance(event.item, SnippetListItem):
            if event.item.snippet:
                self.dismiss(event.item.snippet)

    def _update_preview(self, snippet: "Snippet") -> None:
        """Update the preview panel with snippet content."""
        preview = self.query_one("#preview-content", Static)
        # Truncate if too long for preview
        content = snippet.content
        lines = content.split("\n")
        if len(lines) > 15:
            content = "\n".join(lines[:15]) + "\n..."
        preview.update(content)

    def _clear_preview(self) -> None:
        """Clear the preview panel."""
        preview = self.query_one("#preview-content", Static)
        preview.update("")

    def on_key(self, event) -> None:
        """Handle key events for navigation."""
        if event.key == "down":
            search_input = self.query_one("#search-input", Input)
            if search_input.has_focus:
                snippet_list = self.query_one("#snippet-list", ListView)
                snippet_list.focus()
                event.prevent_default()
        elif event.key == "up":
            snippet_list = self.query_one("#snippet-list", ListView)
            if snippet_list.has_focus and snippet_list.index == 0:
                self.query_one("#search-input", Input).focus()
                event.prevent_default()

    def action_cancel(self) -> None:
        """Cancel the dialog."""
        self.dismiss(None)

    def action_refresh(self) -> None:
        """Refresh snippets from disk."""
        from ..services.snippet_service import get_snippet_service

        service = get_snippet_service()
        service.refresh()
        self._load_snippets()
        self.notify("Snippets refreshed")


class EssenceDialog(ModalScreen[None]):
    """Dialog showing extracted essence from an email."""

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("enter", "close", "Close"),
    ]

    CSS = """
    EssenceDialog {
        align: center middle;
    }

    #essence-dialog {
        width: 90%;
        max-width: 100;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: solid $success;
        padding: 1 2;
    }

    #essence-title {
        text-style: bold;
        color: $success;
        margin-bottom: 1;
    }

    #essence-scroll {
        max-height: 40;
        margin-bottom: 1;
        background: $panel;
        border: solid $secondary;
    }

    #essence-content {
        padding: 1;
    }

    #essence-hint {
        color: $text-muted;
        text-align: center;
    }
    """

    def __init__(self, essence: str) -> None:
        super().__init__()
        self.essence = essence

    def compose(self) -> ComposeResult:
        """Compose the dialog."""
        with Vertical(id="essence-dialog"):
            yield Static("Summary:", id="essence-title")
            with VerticalScroll(id="essence-scroll"):
                yield Static(self.essence, id="essence-content")
            yield Static("[Enter/Esc] close | [j/k] scroll", id="essence-hint")

    def action_close(self) -> None:
        """Close the dialog."""
        self.dismiss(None)


class LoadingDialog(ModalScreen[None]):
    """Dialog showing a loading indicator during AI operations."""

    CSS = """
    LoadingDialog {
        align: center middle;
    }

    #loading-dialog {
        width: 50;
        height: 7;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }

    #loading-title {
        text-style: bold;
        color: $primary;
        text-align: center;
        margin-bottom: 1;
    }

    #loading-spinner {
        text-align: center;
        color: $text-muted;
    }
    """

    def __init__(self, message: str = "Processing...") -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        """Compose the dialog."""
        with Vertical(id="loading-dialog"):
            yield Static(self.message, id="loading-title")
            yield Static("◐ Please wait...", id="loading-spinner")

    def on_mount(self) -> None:
        """Start spinner animation."""
        self._animate_spinner()

    def _animate_spinner(self) -> None:
        """Animate the spinner."""
        self.set_interval(0.15, self._update_spinner)
        self._spinner_frames = ["◐", "◓", "◑", "◒"]
        self._spinner_index = 0

    def _update_spinner(self) -> None:
        """Update spinner frame."""
        self._spinner_index = (self._spinner_index + 1) % 4
        frame = self._spinner_frames[self._spinner_index]
        try:
            spinner = self.query_one("#loading-spinner", Static)
            spinner.update(f"{frame} Please wait...")
        except Exception:
            pass


class AskAIDialog(ModalScreen[Optional[str]]):
    """Dialog for asking AI a question about the thread."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    CSS = """
    AskAIDialog {
        align: center middle;
    }

    #ask-ai-dialog {
        width: 70;
        height: auto;
        max-height: 20;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }

    #ask-ai-title {
        text-style: bold;
        margin-bottom: 1;
    }

    #ask-ai-label {
        margin-bottom: 1;
    }

    #ask-ai-input {
        width: 100%;
        margin-bottom: 1;
    }

    #ask-ai-hint {
        color: $text-muted;
        text-align: center;
    }
    """

    def compose(self) -> ComposeResult:
        """Compose the dialog."""
        with Vertical(id="ask-ai-dialog"):
            yield Static("Ask AI", id="ask-ai-title")
            yield Label("Your question about the thread:", id="ask-ai-label")
            yield Input(
                placeholder="e.g. What is the final price? When is the delivery?",
                id="ask-ai-input",
            )
            yield Static("[Enter] send  [Esc] cancel", id="ask-ai-hint")

    def on_mount(self) -> None:
        """Handle mount."""
        self.query_one("#ask-ai-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission."""
        self._submit()

    def _submit(self) -> None:
        """Submit the question."""
        question_input = self.query_one("#ask-ai-input", Input)
        question = question_input.value.strip()
        if question:
            self.dismiss(question)
        else:
            self.notify("Enter a question", severity="warning")

    def action_cancel(self) -> None:
        """Cancel the dialog."""
        self.dismiss(None)


class AIAnswerDialog(ModalScreen[None]):
    """Dialog showing AI answer to a question."""

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("enter", "close", "Close"),
    ]

    CSS = """
    AIAnswerDialog {
        align: center middle;
    }

    #ai-answer-dialog {
        width: 80;
        height: auto;
        max-height: 35;
        background: $surface;
        border: solid $success;
        padding: 1 2;
    }

    #ai-answer-title {
        text-style: bold;
        color: $success;
        margin-bottom: 1;
    }

    #ai-answer-question {
        color: $text-muted;
        margin-bottom: 1;
    }

    #ai-answer-content {
        margin-bottom: 1;
        padding: 1;
        background: $panel;
        border: solid $secondary;
        max-height: 25;
        overflow: auto;
    }

    #ai-answer-hint {
        color: $text-muted;
        text-align: center;
    }
    """

    def __init__(self, question: str, answer: str) -> None:
        super().__init__()
        self.question = question
        self.answer = answer

    def compose(self) -> ComposeResult:
        """Compose the dialog."""
        with Vertical(id="ai-answer-dialog"):
            yield Static("AI Answer:", id="ai-answer-title")
            # Truncate question if too long
            q_display = self.question if len(self.question) <= 60 else self.question[:57] + "..."
            yield Static(f"Question: {q_display}", id="ai-answer-question")
            with VerticalScroll(id="ai-answer-content"):
                yield Static(self.answer)
            yield Static("[Enter/Esc] close", id="ai-answer-hint")

    def action_close(self) -> None:
        """Close the dialog."""
        self.dismiss(None)


class NewMessageDialog(ModalScreen[Optional[tuple[str, str]]]):
    """Dialog for creating a new message - get recipient and subject."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    CSS = """
    NewMessageDialog {
        align: center middle;
    }

    #new-msg-dialog {
        width: 70;
        height: auto;
        max-height: 30;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }

    #new-msg-title {
        text-style: bold;
        margin-bottom: 1;
    }

    .new-msg-label {
        margin-bottom: 0;
        margin-top: 1;
    }

    .new-msg-label:first-of-type {
        margin-top: 0;
    }

    #recipient-input, #subject-input {
        width: 100%;
    }

    #new-msg-hint {
        color: $text-muted;
        text-align: center;
        margin-top: 1;
    }
    """

    def compose(self) -> ComposeResult:
        """Compose the dialog."""
        with Vertical(id="new-msg-dialog"):
            yield Static("New message", id="new-msg-title")
            yield Label("Recipient:", classes="new-msg-label")
            yield ContactsInput(
                placeholder="e.g. client@example.com",
                input_id="recipient-input",
            )
            yield Label("Subject:", classes="new-msg-label")
            yield Input(
                placeholder="Message subject",
                id="subject-input",
            )
            yield Static("[Enter] next  [Esc] cancel", id="new-msg-hint")

    def on_mount(self) -> None:
        """Handle mount."""
        self.query_one(ContactsInput).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission."""
        if event.input.id == "recipient-input":
            self.query_one("#subject-input", Input).focus()
        elif event.input.id == "subject-input":
            self._submit()

    def _submit(self) -> None:
        """Submit the dialog."""
        contacts_input = self.query_one(ContactsInput)
        recipient = contacts_input.value.strip()
        subject = self.query_one("#subject-input", Input).value.strip()

        if not recipient:
            self.notify("Enter recipient address", severity="warning")
            contacts_input.focus()
            return

        if not subject:
            self.notify("Enter message subject", severity="warning")
            self.query_one("#subject-input", Input).focus()
            return

        self.dismiss((recipient, subject))

    def action_cancel(self) -> None:
        """Cancel the dialog."""
        self.dismiss(None)


class ForwardDialog(ModalScreen[Optional[str]]):
    """Dialog for forwarding an email - get recipient(s).

    Returns comma-separated recipient emails or None if cancelled.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    CSS = """
    ForwardDialog {
        align: center middle;
    }

    #forward-dialog {
        width: 70;
        height: auto;
        max-height: 20;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }

    #forward-title {
        text-style: bold;
        margin-bottom: 1;
    }

    #forward-label {
        margin-bottom: 0;
    }

    #forward-hint {
        color: $text-muted;
        text-align: center;
        margin-top: 1;
    }
    """

    def compose(self) -> ComposeResult:
        """Compose the dialog."""
        with Vertical(id="forward-dialog"):
            yield Static("Forward email", id="forward-title")
            yield Label("To (comma-separated for multiple):", id="forward-label")
            yield ContactsInput(
                placeholder="e.g. alice@example.com, bob@example.com",
                input_id="forward-recipient-input",
            )
            yield Static("[Enter] forward  [Esc] cancel", id="forward-hint")

    def on_mount(self) -> None:
        """Handle mount."""
        self.query_one(ContactsInput).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission."""
        if event.input.id == "forward-recipient-input":
            self._submit()

    def _submit(self) -> None:
        """Submit the dialog."""
        contacts_input = self.query_one(ContactsInput)
        recipients = contacts_input.value.strip()

        if not recipients:
            self.notify("Enter at least one recipient", severity="warning")
            contacts_input.focus()
            return

        self.dismiss(recipients)

    def action_cancel(self) -> None:
        """Cancel the dialog."""
        self.dismiss(None)


class AttachFileDialog(ModalScreen[Optional[str]]):
    """Dialog for attaching a file by path."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    CSS = """
    AttachFileDialog {
        align: center middle;
    }

    #attach-dialog {
        width: 70;
        height: auto;
        max-height: 20;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }

    #attach-title {
        text-style: bold;
        margin-bottom: 1;
    }

    #attach-label {
        margin-bottom: 1;
    }

    #attach-input {
        width: 100%;
        margin-bottom: 1;
    }

    #attach-error {
        color: $error;
        margin-bottom: 1;
    }

    #attach-hint {
        color: $text-muted;
        text-align: center;
    }
    """

    def __init__(self) -> None:
        super().__init__()

    def compose(self) -> ComposeResult:
        """Compose the dialog."""
        from pathlib import Path

        # Default to user's home directory
        default_path = str(Path.home())

        with Vertical(id="attach-dialog"):
            yield Static("Add attachment", id="attach-title")
            yield Label("File path:", id="attach-label")
            yield Input(
                value=default_path,
                placeholder="e.g. C:\\Users\\...\\document.pdf",
                id="attach-input",
            )
            yield Static("", id="attach-error")
            yield Static("[Enter] add  [Esc] cancel", id="attach-hint")

    def on_mount(self) -> None:
        """Handle mount."""
        input_widget = self.query_one("#attach-input", Input)
        input_widget.focus()
        # Select all text so user can easily replace
        input_widget.action_select_all()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission."""
        self._submit()

    def _submit(self) -> None:
        """Submit the file path."""
        from pathlib import Path

        path_input = self.query_one("#attach-input", Input)
        error_label = self.query_one("#attach-error", Static)
        file_path = path_input.value.strip()

        if not file_path:
            error_label.update("Enter file path")
            return

        path = Path(file_path)

        if not path.exists():
            error_label.update("File does not exist")
            return

        if not path.is_file():
            error_label.update("Path is not a file")
            return

        # Check file size (limit to 25MB for Gmail)
        max_size = 25 * 1024 * 1024  # 25MB
        if path.stat().st_size > max_size:
            error_label.update("File is too large (max 25MB)")
            return

        self.dismiss(file_path)

    def action_cancel(self) -> None:
        """Cancel the dialog."""
        self.dismiss(None)


class SearchDialog(ModalScreen[Optional[str]]):
    """Dialog for searching threads by email address."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    CSS = """
    SearchDialog {
        align: center middle;
    }

    #search-dialog {
        width: 70;
        height: auto;
        max-height: 15;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }

    #search-title {
        text-style: bold;
        margin-bottom: 1;
    }

    #search-label {
        margin-bottom: 1;
    }

    #email-input {
        width: 100%;
        margin-bottom: 1;
    }

    #search-hint {
        color: $text-muted;
        text-align: center;
    }
    """

    def compose(self) -> ComposeResult:
        """Compose the dialog."""
        with Vertical(id="search-dialog"):
            yield Static("Search threads", id="search-title")
            yield Label("Email address:", id="search-label")
            yield Input(
                placeholder="e.g. client@example.com",
                id="email-input",
            )
            yield Static("[Enter] search  [Esc] cancel", id="search-hint")

    def on_mount(self) -> None:
        """Handle mount."""
        self.query_one("#email-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission."""
        self._submit()

    def _submit(self) -> None:
        """Submit the search."""
        email_input = self.query_one("#email-input", Input)
        email = email_input.value.strip()
        if email:
            self.dismiss(email)
        else:
            self.notify("Enter email address", severity="warning")

    def action_cancel(self) -> None:
        """Cancel the dialog."""
        self.dismiss(None)


class InsertLinkDialog(ModalScreen[Optional[tuple[str, str]]]):
    """Dialog for inserting a link with name and URL."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    CSS = """
    InsertLinkDialog {
        align: center middle;
    }

    #insert-link-dialog {
        width: 70;
        height: auto;
        max-height: 20;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }

    #insert-link-title {
        text-style: bold;
        margin-bottom: 1;
    }

    .link-label {
        margin-bottom: 0;
        margin-top: 1;
    }

    .link-label:first-of-type {
        margin-top: 0;
    }

    #link-name-input, #link-url-input {
        width: 100%;
    }

    #insert-link-hint {
        color: $text-muted;
        text-align: center;
        margin-top: 1;
    }
    """

    def compose(self) -> ComposeResult:
        """Compose the dialog."""
        with Vertical(id="insert-link-dialog"):
            yield Static("Insert link", id="insert-link-title")
            yield Label("Link name:", classes="link-label")
            yield Input(
                placeholder="e.g. Product offer",
                id="link-name-input",
            )
            yield Label("URL:", classes="link-label")
            yield Input(
                placeholder="e.g. https://example.com/offer",
                id="link-url-input",
            )
            yield Static("[Enter] insert  [Esc] cancel", id="insert-link-hint")

    def on_mount(self) -> None:
        """Handle mount."""
        self.query_one("#link-name-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission."""
        if event.input.id == "link-name-input":
            self.query_one("#link-url-input", Input).focus()
        elif event.input.id == "link-url-input":
            self._submit()

    def _submit(self) -> None:
        """Submit the link."""
        name = self.query_one("#link-name-input", Input).value.strip()
        url = self.query_one("#link-url-input", Input).value.strip()

        if not name:
            self.notify("Enter link name", severity="warning")
            self.query_one("#link-name-input", Input).focus()
            return

        if not url:
            self.notify("Enter URL", severity="warning")
            self.query_one("#link-url-input", Input).focus()
            return

        self.dismiss((name, url))

    def action_cancel(self) -> None:
        """Cancel the dialog."""
        self.dismiss(None)
