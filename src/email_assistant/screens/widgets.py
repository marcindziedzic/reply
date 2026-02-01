"""Shared widgets for Email Assistant screens."""

from abc import abstractmethod
from typing import Any, Callable, Generic, Optional, TypeVar

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, ListItem, ListView, Static

# Type variable for items in the list
T = TypeVar("T")


class BackgroundTaskMixin:
    """Mixin providing background task execution for Textual screens.

    Provides methods to run synchronous tasks in background threads
    with automatic success/error notifications.
    """

    def _run_background_task(
        self,
        task_fn: Callable[[], None],
        success_message: str,
        error_prefix: str = "Error",
    ) -> None:
        """Run a synchronous task in background worker with notification.

        Uses @work(exclusive=False) pattern so multiple background tasks can run
        concurrently (e.g., user deletes several items quickly).
        """
        self._execute_background_task(task_fn, success_message, error_prefix)

    @work(exclusive=False, thread=True)
    def _execute_background_task(
        self,
        task_fn: Callable[[], None],
        success_message: str,
        error_prefix: str,
    ) -> None:
        """Execute the task in a background thread."""
        try:
            task_fn()
            # Use app.notify instead of self.notify in case screen was popped
            self.app.call_from_thread(self.app.notify, success_message)
        except Exception as e:
            self.app.call_from_thread(
                self.app.notify, f"{error_prefix}: {e}", severity="error"
            )


# Shared CSS for centered list layout
CENTERED_LIST_CSS = """
    #list-container {
        width: 80%;
        max-width: 100;
        height: 100%;
        padding: 1 2;
    }

    #title-label {
        text-style: bold;
        margin-bottom: 1;
        text-align: center;
    }

    #loading-label {
        text-align: center;
        margin-top: 2;
    }

    #empty-container {
        width: 100%;
        height: 1fr;
        align: center middle;
        content-align: center middle;
        display: none;
    }

    #empty-icon {
        text-align: center;
        color: $text-muted;
        margin-bottom: 1;
    }

    #empty-message {
        text-align: center;
        color: $success;
        text-style: bold;
    }

    #empty-hint {
        text-align: center;
        color: $text-muted;
        margin-top: 1;
    }

    .item-line-1 {
        text-style: bold;
    }

    .item-line-2 {
        color: $text;
    }

    .item-line-3 {
        color: $text-muted;
    }

    ListView {
        background: transparent;
        border: none;
    }

    ListView:focus {
        border: none;
    }

    ListView > ListItem {
        background: transparent;
        padding: 0 1;
        margin-bottom: 1;
    }

    ListView:focus > ListItem.-highlight {
        background: transparent;
        border-left: thick orange;
    }
"""


class ItemListContainer(VerticalScroll):
    """A centered container for item lists."""

    def __init__(
        self,
        title: str = "List",
        loading_text: str = "Loading...",
        list_id: str = "items-list",
        empty_icon: str = "( )",
        empty_message: str = "No items",
        empty_hint: str = "",
        **kwargs,
    ) -> None:
        super().__init__(id="list-container", **kwargs)
        self._title = title
        self._loading_text = loading_text
        self._list_id = list_id
        self._empty_icon = empty_icon
        self._empty_message = empty_message
        self._empty_hint = empty_hint

    def compose(self) -> ComposeResult:
        yield Label(f"{self._title} (loading...)", id="title-label")
        yield Label(self._loading_text, id="loading-label")
        with Container(id="empty-container"):
            yield Static(self._empty_icon, id="empty-icon")
            yield Static(self._empty_message, id="empty-message")
            yield Static(self._empty_hint, id="empty-hint")
        yield ListView(id=self._list_id)


class BaseListItem(ListItem):
    """Base class for list items with 3-line layout."""

    def __init__(self, index: int, **kwargs) -> None:
        super().__init__(**kwargs)
        self.index = index

    def compose(self) -> ComposeResult:
        """Compose the list item with 3 lines."""
        yield Static(self.get_line_1(), classes="item-line-1")
        yield Static(self.get_line_2(), classes="item-line-2")
        yield Static(self.get_line_3(), classes="item-line-3")

    def get_line_1(self) -> str:
        """Override to provide first line (sender/title)."""
        return f"[{self.index + 1}] Item"

    def get_line_2(self) -> str:
        """Override to provide second line (subject)."""
        return "    Subject"

    def get_line_3(self) -> str:
        """Override to provide third line (metadata)."""
        return "    Meta"


class BaseListScreen(Screen, Generic[T], BackgroundTaskMixin):
    """Base screen for item lists with shared navigation."""

    # Subclasses should override these
    TITLE = "Items"
    LOADING_TEXT = "Loading..."
    EMPTY_TEXT = "No items"
    LIST_ID = "items-list"
    EMPTY_ICON = "\\[  ]"
    EMPTY_MESSAGE = "List is empty"
    EMPTY_HINT = ""

    # Shared bindings for navigation
    BASE_BINDINGS = [
        Binding("j", "cursor_down", "Next", show=False),
        Binding("k", "cursor_up", "Previous", show=False),
        Binding("o", "select_current", "Open", show=False),
        Binding("1", "select_1", "1", show=False),
        Binding("2", "select_2", "2", show=False),
        Binding("3", "select_3", "3", show=False),
        Binding("4", "select_4", "4", show=False),
        Binding("5", "select_5", "5", show=False),
        Binding("6", "select_6", "6", show=False),
        Binding("7", "select_7", "7", show=False),
        Binding("8", "select_8", "8", show=False),
        Binding("9", "select_9", "9", show=False),
    ]


    def __init__(self) -> None:
        super().__init__()
        self.items: list[T] = []

    def compose(self) -> ComposeResult:
        """Compose the screen."""
        yield Header()
        yield ItemListContainer(
            title=self.TITLE,
            loading_text=self.LOADING_TEXT,
            list_id=self.LIST_ID,
            empty_icon=self.EMPTY_ICON,
            empty_message=self.EMPTY_MESSAGE,
            empty_hint=self.EMPTY_HINT,
        )
        yield Footer()

    def on_mount(self) -> None:
        """Handle screen mount."""
        self.load_items()

    @work(exclusive=True)
    async def load_items(self) -> None:
        """Load items into the list."""
        loading_label = self.query_one("#loading-label", Label)
        title_label = self.query_one("#title-label", Label)
        empty_container = self.query_one("#empty-container", Container)
        items_list = self.query_one(f"#{self.LIST_ID}", ListView)

        loading_label.display = True
        loading_label.update(self.LOADING_TEXT)
        empty_container.display = False

        try:
            # Fetch items - subclasses implement this
            self.items = await self.fetch_items()

            # Update UI
            loading_label.display = False
            await items_list.clear()

            if not self.items:
                title_label.display = False
                empty_container.display = True
            else:
                title_label.display = True
                title_label.update(self.get_title_with_count())
                for i, item in enumerate(self.items):
                    list_item = self.create_list_item(item, i)
                    await items_list.append(list_item)

                # Focus the list and select first item
                items_list.focus()
                items_list.index = 0

        except Exception as e:
            loading_label.update(f"Error: {e}")

    @abstractmethod
    async def fetch_items(self) -> list[T]:
        """Fetch items to display. Override in subclasses."""
        raise NotImplementedError

    @abstractmethod
    def create_list_item(self, item: T, index: int) -> BaseListItem:
        """Create a list item widget. Override in subclasses."""
        raise NotImplementedError

    @abstractmethod
    def on_item_selected(self, item: T) -> None:
        """Handle item selection. Override in subclasses."""
        raise NotImplementedError

    def get_title_with_count(self) -> str:
        """Get title with item count. Override for custom format."""
        return f"{self.TITLE} ({len(self.items)})"

    def get_empty_title(self) -> str:
        """Get title when list is empty. Override for custom format."""
        return f"{self.TITLE} (none)"

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle list item selection."""
        if isinstance(event.item, BaseListItem):
            index = event.item.index
            if 0 <= index < len(self.items):
                self.on_item_selected(self.items[index])

    def action_refresh(self) -> None:
        """Refresh items list."""
        self.load_items()

    def action_quit(self) -> None:
        """Quit application."""
        self.app.exit()

    # Navigation actions
    def action_cursor_down(self) -> None:
        """Move cursor down in list."""
        if not self.items:
            return
        items_list = self.query_one(f"#{self.LIST_ID}", ListView)
        items_list.action_cursor_down()

    def action_cursor_up(self) -> None:
        """Move cursor up in list."""
        if not self.items:
            return
        items_list = self.query_one(f"#{self.LIST_ID}", ListView)
        items_list.action_cursor_up()

    def action_select_current(self) -> None:
        """Select the currently highlighted item."""
        if not self.items:
            return
        items_list = self.query_one(f"#{self.LIST_ID}", ListView)
        if items_list.highlighted_child is not None:
            items_list.action_select_cursor()

    def _select_by_number(self, number: int) -> None:
        """Select item by number."""
        if 0 <= number < len(self.items):
            self.on_item_selected(self.items[number])

    def action_select_1(self) -> None:
        self._select_by_number(0)

    def action_select_2(self) -> None:
        self._select_by_number(1)

    def action_select_3(self) -> None:
        self._select_by_number(2)

    def action_select_4(self) -> None:
        self._select_by_number(3)

    def action_select_5(self) -> None:
        self._select_by_number(4)

    def action_select_6(self) -> None:
        self._select_by_number(5)

    def action_select_7(self) -> None:
        self._select_by_number(6)

    def action_select_8(self) -> None:
        self._select_by_number(7)

    def action_select_9(self) -> None:
        self._select_by_number(8)

    # --- Optimistic UI helpers ---

    def _get_selected_index(self) -> Optional[int]:
        """Get the currently selected list index."""
        items_list = self.query_one(f"#{self.LIST_ID}", ListView)
        if items_list.index is not None and 0 <= items_list.index < len(self.items):
            return items_list.index
        return None

    def _remove_item_optimistically(self, index: int) -> T:
        """Remove item from list immediately. Returns removed item for rollback.

        This method:
        1. Removes the item from self.items
        2. Removes the ListItem widget from ListView
        3. Adjusts selection if needed
        4. Updates title count
        5. Handles empty list case
        """
        # Pop from items list
        removed_item = self.items.pop(index)

        # Remove widget from ListView
        items_list = self.query_one(f"#{self.LIST_ID}", ListView)
        list_items = list(items_list.children)
        if 0 <= index < len(list_items):
            list_items[index].remove()

        # Adjust selection
        if self.items:
            # Keep selection in bounds
            new_index = min(index, len(self.items) - 1)
            items_list.index = new_index
        else:
            items_list.index = None

        # Update title count
        title_label = self.query_one("#title-label", Label)
        if self.items:
            title_label.update(self.get_title_with_count())
        else:
            # Show empty state
            title_label.display = False
            empty_container = self.query_one("#empty-container", Container)
            empty_container.display = True

        return removed_item

    def _get_item_id(self, item: T) -> str:
        """Get the ID of an item for lookup.

        Handles both Thread objects (.id) and Reminder objects (.thread.id).
        """
        if hasattr(item, "id"):
            return item.id
        if hasattr(item, "thread") and hasattr(item.thread, "id"):
            return item.thread.id
        raise NotImplementedError("Item must have 'id' or 'thread.id' attribute")

    def _remove_item_by_id(self, item_id: str) -> Optional[T]:
        """Remove item from list by ID. Returns removed item or None if not found."""
        for i, item in enumerate(self.items):
            if self._get_item_id(item) == item_id:
                return self._remove_item_optimistically(i)
        return None


class ContactListItem(ListItem):
    """List item for a contact suggestion in autocomplete dropdown."""

    def __init__(self, contact: "Contact") -> None:
        super().__init__()
        self.contact = contact

    def compose(self) -> ComposeResult:
        """Compose the contact item."""
        if self.contact.name:
            display = f"{self.contact.name} <{self.contact.email}>"
        else:
            display = self.contact.email
        yield Static(display)


class ContactsInput(Container):
    """Input field with contacts autocomplete dropdown.

    Shows suggestions from Google Contacts as user types.
    """

    DEFAULT_CSS = """
    ContactsInput {
        height: auto;
        width: 100%;
    }

    ContactsInput > Input {
        width: 100%;
    }

    ContactsInput > #suggestions-container {
        height: auto;
        max-height: 8;
        display: none;
        background: $surface;
        border: solid $primary;
        padding: 0;
        margin-top: 0;
    }

    ContactsInput > #suggestions-container.visible {
        display: block;
    }

    ContactsInput ListView {
        height: auto;
        max-height: 7;
        background: transparent;
        border: none;
    }

    ContactsInput ListView > ListItem {
        padding: 0 1;
    }

    ContactsInput ListView:focus > ListItem.-highlight {
        background: $accent;
    }
    """

    def __init__(
        self,
        value: str = "",
        placeholder: str = "e.g. client@example.com",
        input_id: str = "recipient-input",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._initial_value = value
        self._placeholder = placeholder
        self._input_id = input_id
        self._search_timer = None
        self._contacts: list["Contact"] = []
        self._skip_next_search = False  # Flag to skip search after selection

    def compose(self) -> ComposeResult:
        """Compose the input with dropdown."""
        from textual.widgets import Input
        yield Input(
            value=self._initial_value,
            placeholder=self._placeholder,
            id=self._input_id,
        )
        with Container(id="suggestions-container"):
            yield ListView(id="suggestions-list")

    @property
    def value(self) -> str:
        """Get the current input value."""
        from textual.widgets import Input
        return self.query_one(f"#{self._input_id}", Input).value

    @value.setter
    def value(self, new_value: str) -> None:
        """Set the input value."""
        from textual.widgets import Input
        self.query_one(f"#{self._input_id}", Input).value = new_value

    def focus(self) -> None:
        """Focus the input field."""
        from textual.widgets import Input
        self.query_one(f"#{self._input_id}", Input).focus()

    def _get_current_query(self, value: str) -> tuple[str, str]:
        """Extract the current query (part after last comma) from input value.

        Returns:
            Tuple of (prefix to keep, current query to search).
            prefix includes everything up to and including the last comma.
        """
        if "," in value:
            last_comma = value.rfind(",")
            prefix = value[:last_comma + 1]
            query = value[last_comma + 1:].strip()
            return prefix, query
        return "", value.strip()

    def on_input_changed(self, event) -> None:
        """Handle input changes - trigger contact search."""
        from textual.widgets import Input
        if event.input.id != self._input_id:
            return

        # Skip search if we just selected a contact
        if self._skip_next_search:
            self._skip_next_search = False
            return

        # Get only the part after the last comma for searching
        prefix, query = self._get_current_query(event.value)

        # Need at least 3 characters to search
        if len(query) < 3:
            self._hide_suggestions()
            return

        # Debounce: cancel previous timer and set new one
        if self._search_timer:
            self._search_timer.stop()

        self._search_timer = self.set_timer(0.15, lambda: self._search_contacts(query))

    @work(exclusive=True, thread=True)
    def _search_contacts(self, query: str) -> None:
        """Search contacts in background thread."""
        from ..contacts import get_contacts_client

        try:
            client = get_contacts_client()
            self._contacts = client.search_contacts(query, limit=5)
        except Exception:
            self._contacts = []

        # Update UI in main thread
        self.app.call_from_thread(self._update_suggestions)

    def _update_suggestions(self) -> None:
        """Update the suggestions list."""
        suggestions_container = self.query_one("#suggestions-container", Container)
        suggestions_list = self.query_one("#suggestions-list", ListView)

        # Clear existing items
        suggestions_list.clear()

        if not self._contacts:
            self._hide_suggestions()
            return

        # Add contact items
        for contact in self._contacts:
            item = ContactListItem(contact)
            suggestions_list.append(item)

        # Show dropdown
        suggestions_container.add_class("visible")

    def _hide_suggestions(self) -> None:
        """Hide the suggestions dropdown."""
        suggestions_container = self.query_one("#suggestions-container", Container)
        suggestions_container.remove_class("visible")
        self._contacts = []

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle contact selection from dropdown."""
        if isinstance(event.item, ContactListItem):
            # Skip next search triggered by value change
            self._skip_next_search = True
            # Preserve any emails before the last comma
            prefix, _ = self._get_current_query(self.value)
            # Set the email in the input (append to prefix if exists)
            if prefix:
                self.value = f"{prefix} {event.item.contact.email}"
            else:
                self.value = event.item.contact.email
            self._hide_suggestions()
            # Move focus back to input
            self.focus()

    def on_key(self, event) -> None:
        """Handle keyboard navigation."""
        from textual.widgets import Input

        input_field = self.query_one(f"#{self._input_id}", Input)
        suggestions_container = self.query_one("#suggestions-container", Container)
        suggestions_list = self.query_one("#suggestions-list", ListView)

        is_visible = suggestions_container.has_class("visible")

        if event.key == "down" and input_field.has_focus and is_visible:
            # Move from input to suggestions list
            suggestions_list.focus()
            if suggestions_list.index is None:
                suggestions_list.index = 0
            event.prevent_default()
            event.stop()

        elif event.key == "up" and suggestions_list.has_focus:
            # Move back to input if at top of list
            if suggestions_list.index == 0:
                input_field.focus()
                event.prevent_default()
                event.stop()

        elif event.key == "escape" and is_visible:
            # Hide suggestions on Escape
            self._hide_suggestions()
            input_field.focus()
            event.prevent_default()
            event.stop()

        elif event.key == "tab" and is_visible:
            # Hide suggestions on Tab (moving to next field)
            self._hide_suggestions()
