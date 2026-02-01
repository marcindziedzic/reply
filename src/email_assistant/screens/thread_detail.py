"""Thread detail screen - unified view for email threads and reminders."""

import asyncio
from datetime import datetime, time
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Label, Markdown, Static

from .widgets import BackgroundTaskMixin

from ..claude import get_claude_client
from ..config import get_config
from ..gmail import get_gmail_client
from ..models import Attachment, Message, Thread
from ..services.email_parser import EmailParser
from ..services.reminder_service import Reminder, ReminderStatus, get_reminder_service
from ..services.snippet_service import get_snippet_service

if TYPE_CHECKING:
    from ..app import EmailAssistantApp


class ThreadDetailBase(Screen, BackgroundTaskMixin):
    """Base class for thread detail screens."""

    BINDINGS = [
        Binding("j", "next_message", "Next", show=False),
        Binding("k", "prev_message", "Previous", show=False),
        Binding("down", "next_message", "Next", show=False),
        Binding("up", "prev_message", "Previous", show=False),
        Binding("g", "generate", "Generate"),
        Binding("c", "compose", "Reply"),
        Binding("s", "summary", "Summary"),
        Binding("t", "timeline_summary", "Timeline"),
        Binding("u", "key_agreements", "Agreements"),
        Binding("a", "ask_ai", "Ask AI"),
        Binding("b", "go_back", "Back"),
        Binding("escape", "go_back", "Back", show=False),
    ]

    CSS = """
    ThreadDetailBase, ThreadDetailScreen {
        background: $surface;
    }

    #main-container {
        width: 100%;
        height: 100%;
    }

    #thread-header {
        text-style: bold;
        padding: 0 1;
        height: 1;
        background: $primary;
        color: $text;
    }

    #reminder-status {
        padding: 0 1;
        height: 1;
    }

    .status-overdue {
        background: $error 30%;
        color: $text;
    }

    .status-upcoming {
        background: $warning 30%;
        color: $text;
    }

    #split-container {
        width: 100%;
        height: 1fr;
    }

    #message-list-panel {
        width: 30%;
        min-width: 30;
        height: 100%;
        border-right: solid $primary;
        background: $surface-darken-1;
    }

    .message-list-item {
        width: 100%;
        height: auto;
        min-height: 3;
        padding: 0 1;
        margin: 0;
        border-bottom: solid $surface-lighten-1;
        background: $surface-darken-1;
    }

    .message-list-item:hover {
        background: $surface-lighten-1;
    }

    .message-list-item.selected {
        background: $primary 40%;
    }

    .message-list-item.from-me {
        color: $primary-lighten-2;
    }

    .message-list-item.from-other-1 {
        color: $warning;
    }

    .message-list-item.from-other-2 {
        color: $success;
    }

    .message-list-item.from-other-3 {
        color: #cc66ff;
    }

    #detail-panel {
        width: 1fr;
        height: 100%;
        padding: 1;
    }

    #detail-header {
        height: auto;
        margin-bottom: 1;
        padding-bottom: 1;
        border-bottom: solid $surface-lighten-1;
    }

    .detail-from {
        color: $text;
        text-style: bold;
    }

    .detail-date {
        color: $text-muted;
    }

    .detail-to {
        color: $text-muted;
    }

    #detail-body {
        height: 1fr;
    }

    #loading-label {
        text-align: center;
        margin-top: 2;
    }

    .attachments-container {
        margin-top: 1;
        padding-top: 1;
        border-top: solid $surface-lighten-1;
    }

    .attachments-label {
        color: $text-muted;
        margin-bottom: 0;
    }

    .attachment-link {
        background: transparent;
        border: none;
        color: $warning;
        text-style: underline;
        min-width: 0;
        width: auto;
        height: 1;
        padding: 0;
        margin: 0;
    }

    .attachment-link:hover {
        color: $accent;
        text-style: bold underline;
    }
    """

    def __init__(
        self,
        thread: Thread,
        user_email: str,
        reminder: Optional[Reminder] = None,
    ) -> None:
        super().__init__()
        self.thread = thread
        self.user_email = user_email
        self.reminder = reminder
        self.is_reminder_mode = reminder is not None

        # Thread mode specific
        self.is_forwarded = False
        self.reply_to_email = ""

        # Message selection
        self._messages: list[Message] = []
        self._selected_index: int = 0

        # Attachments
        self._attachments_map: dict[str, Attachment] = {}
        self._attachment_counter: int = 0

    def compose(self) -> ComposeResult:
        """Compose the screen."""
        yield Header()
        with Vertical(id="main-container"):
            prefix = "Reminder: " if self.is_reminder_mode else "Thread: "
            yield Static(f"{prefix}{self.thread.subject}", id="thread-header")
            if self.is_reminder_mode:
                yield Static("", id="reminder-status")
            with Horizontal(id="split-container"):
                with VerticalScroll(id="message-list-panel"):
                    yield Label("Loading...", id="loading-label")
                with VerticalScroll(id="detail-panel"):
                    with Vertical(id="detail-header"):
                        yield Static("", classes="detail-from")
                        yield Static("", classes="detail-date")
                        yield Static("", classes="detail-to")
                    yield Markdown("", id="detail-body")
        yield Footer()

    def on_mount(self) -> None:
        """Handle screen mount."""
        self._load_and_render()

    @work(exclusive=True)
    async def _load_and_render(self) -> None:
        """Load full messages if needed, then render the thread."""
        # Lazy load full messages if only metadata was fetched
        if not self.thread.messages_loaded:
            gmail = get_gmail_client()
            full_thread = gmail.get_thread(self.thread.id)
            if full_thread:
                self.thread = full_thread

        if not self.is_reminder_mode:
            self._check_if_forwarded()

        await self._do_render_thread()

    def _check_if_forwarded(self) -> None:
        """Check if this thread is from a forwarding address and determine reply-to."""
        config = get_config()

        for msg in self.thread.messages:
            if config.gmail.is_forwarding_address(msg.sender_email):
                self.is_forwarded = True
                break

        self.reply_to_email = self.thread.get_reply_recipient(self.user_email)

    async def _do_render_thread(self) -> None:
        """Render the thread messages."""
        header = self.query_one("#thread-header", Static)

        # Build header text
        if self.is_reminder_mode:
            sender_info = f" | Od: {self.reminder.sender_name} <{self.reminder.sender_email}>"
            header.update(f"Reminder: {self.thread.subject}{sender_info}")

            status_widget = self.query_one("#reminder-status", Static)
            status_text, status_class = self._format_reminder_status()
            status_widget.update(status_text)
            status_widget.set_classes(status_class)
        else:
            sender_info = ""
            for msg in self.thread.messages:
                if msg.sender_email.lower() != self.user_email.lower():
                    sender_info = f" | Od: {msg.sender} <{msg.sender_email}>"
                    break

            reply_to_info = f" | Reply to: {self.reply_to_email}" if self.reply_to_email else ""
            forwarded_marker = " [FWD]" if self.is_forwarded else ""
            header.update(f"{self.thread.subject}{sender_info}{reply_to_info}{forwarded_marker}")

        # Store messages (newest first)
        self._messages = list(reversed(self.thread.messages))

        if not self._messages:
            return

        # Render message list
        await self._render_message_list()

        # Select first message
        self._selected_index = 0
        await self._show_message(0)

    async def _render_message_list(self) -> None:
        """Render the message list panel."""
        list_panel = self.query_one("#message-list-panel", VerticalScroll)

        # Remove loading label
        try:
            loading = self.query_one("#loading-label", Label)
            loading.remove()
        except Exception:
            pass

        # Add message items
        if not self._messages:
            await list_panel.mount(Static("No messages", classes="message-list-item"))
            return

        # Build color mapping for other senders (not me)
        other_senders: dict[str, int] = {}
        color_index = 0
        for msg in self._messages:
            sender_lower = msg.sender_email.lower()
            if sender_lower != self.user_email.lower() and sender_lower not in other_senders:
                other_senders[sender_lower] = (color_index % 3) + 1  # 1, 2, 3
                color_index += 1

        for i, msg in enumerate(self._messages):
            is_me = msg.sender_email.lower() == self.user_email.lower()
            sender = "me" if is_me else msg.sender_email.split("@")[0][:12]
            date_str = msg.date.strftime("%d.%m %H:%M")

            # Preview snippet - strip markdown
            body_text = msg.body.strip()
            for char in ['*', '_', '#', '`', '[', ']', '(', ')']:
                body_text = body_text.replace(char, '')
            preview = body_text.replace("\n", " ")[:75].strip()
            if len(body_text) > 75:
                preview += "..."

            unread = "● " if msg.is_unread else "  "
            content = f"{unread}{sender} {date_str}\n  {preview}"

            item = Static(content, classes="message-list-item", id=f"msg-{i}")
            if i == 0:
                item.add_class("selected")
            if is_me:
                item.add_class("from-me")
            else:
                color_num = other_senders.get(msg.sender_email.lower(), 1)
                item.add_class(f"from-other-{color_num}")

            await list_panel.mount(item)

    async def _show_message(self, index: int) -> None:
        """Display the selected message in the detail panel."""
        if index < 0 or index >= len(self._messages):
            return

        msg = self._messages[index]

        # Update header
        from_widget = self.query_one(".detail-from", Static)
        date_widget = self.query_one(".detail-date", Static)
        to_widget = self.query_one(".detail-to", Static)

        sender = "me" if msg.sender_email.lower() == self.user_email.lower() else msg.sender
        from_widget.update(f"Od: {sender} <{msg.sender_email}>")
        date_widget.update(f"Data: {msg.date.strftime('%Y-%m-%d %H:%M')}")
        to_widget.update(f"Do: {msg.recipient}")

        # Update body
        body_widget = self.query_one("#detail-body", Markdown)
        body = EmailParser.strip_quoted_lines(msg.body.strip())
        await body_widget.update(body)

        # Update attachments
        await self._update_attachments(msg)

    async def _update_attachments(self, msg: Message) -> None:
        """Update attachments display for the current message."""
        detail_panel = self.query_one("#detail-panel", VerticalScroll)

        # Remove old attachments container
        try:
            old_container = self.query_one(".attachments-container")
            old_container.remove()
        except Exception:
            pass

        # Add new attachments if present
        if msg.attachments:
            await self._render_attachments(detail_panel, msg.attachments)

    def _update_selection(self, old_index: int, new_index: int) -> None:
        """Update visual selection state."""
        try:
            old_item = self.query_one(f"#msg-{old_index}", Static)
            old_item.remove_class("selected")
        except Exception:
            pass

        try:
            new_item = self.query_one(f"#msg-{new_index}", Static)
            new_item.add_class("selected")
            new_item.scroll_visible()
        except Exception:
            pass

    def action_next_message(self) -> None:
        """Select next message."""
        if self._selected_index < len(self._messages) - 1:
            old_index = self._selected_index
            self._selected_index += 1
            self._update_selection(old_index, self._selected_index)
            self._show_message_sync(self._selected_index)

    def action_prev_message(self) -> None:
        """Select previous message."""
        if self._selected_index > 0:
            old_index = self._selected_index
            self._selected_index -= 1
            self._update_selection(old_index, self._selected_index)
            self._show_message_sync(self._selected_index)

    @work(exclusive=True)
    async def _show_message_sync(self, index: int) -> None:
        """Show message (for use from sync context)."""
        await self._show_message(index)

    def _format_reminder_status(self) -> tuple[str, str]:
        """Format the reminder status for display."""
        if not self.reminder:
            return "", ""

        if self.reminder.status == ReminderStatus.OVERDUE:
            if self.reminder.scheduled_datetime:
                scheduled = self.reminder.scheduled_datetime
                return (f"OVERDUE - Scheduled for: {scheduled.strftime('%Y-%m-%d %H:%M')}", "status-overdue")
            else:
                return "OVERDUE - Archive", "status-overdue"
        elif self.reminder.status == ReminderStatus.UPCOMING:
            if self.reminder.scheduled_datetime:
                scheduled = self.reminder.scheduled_datetime
                return (f"UPCOMING - Scheduled for: {scheduled.strftime('%H:%M')} today", "status-upcoming")
            else:
                return "UPCOMING", "status-upcoming"
        else:
            if self.reminder.scheduled_datetime:
                scheduled = self.reminder.scheduled_datetime
                return (f"Scheduled for: {scheduled.strftime('%Y-%m-%d %H:%M')}", "")
            else:
                return "Scheduled", ""

    # === Attachment handling ===

    async def _render_attachments(self, container, attachments: list[Attachment]) -> None:
        """Render attachment list with download buttons styled as links."""
        attachments_container = Vertical(classes="attachments-container")
        await container.mount(attachments_container)

        await attachments_container.mount(
            Static(f"Attachments ({len(attachments)}):", classes="attachments-label")
        )

        for att in attachments:
            self._attachment_counter += 1
            btn_id = f"att-{self._attachment_counter}"
            self._attachments_map[btn_id] = att

            size_str = self._format_size(att.size)
            await attachments_container.mount(
                Button(f"  {att.filename} ({size_str})", id=btn_id, classes="attachment-link")
            )

    def _format_size(self, size: int) -> str:
        """Format file size in human-readable form."""
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size // 1024} KB"
        else:
            return f"{size // (1024 * 1024)} MB"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle attachment download button press."""
        btn_id = event.button.id
        if btn_id and btn_id in self._attachments_map:
            attachment = self._attachments_map[btn_id]
            self._download_attachment(attachment)

    @work(exclusive=True)
    async def _download_attachment(self, attachment: Attachment) -> None:
        """Download attachment to Downloads folder."""
        try:
            gmail = get_gmail_client()
            content = gmail.download_attachment(attachment.message_id, attachment.attachment_id)

            downloads = Path.home() / "Downloads"
            downloads.mkdir(exist_ok=True)

            # Sanitize filename - replace path separators with underscores
            safe_filename = attachment.filename.replace("/", "_").replace("\\", "_")
            filepath = downloads / safe_filename
            if filepath.exists():
                stem = filepath.stem
                suffix = filepath.suffix
                counter = 1
                while filepath.exists():
                    filepath = downloads / f"{stem}_{counter}{suffix}"
                    counter += 1

            filepath.write_bytes(content)
            self.notify(f"Downloaded: {filepath.name}")

        except Exception as e:
            self.notify(f"Download error: {e}", severity="error")

    # === Common actions ===

    def _get_selected_message(self) -> Optional[Message]:
        """Get currently selected message."""
        if 0 <= self._selected_index < len(self._messages):
            return self._messages[self._selected_index]
        return None

    def action_summary(self) -> None:
        """Generate summary from the selected message using AI."""
        self._generate_summary()

    @work(exclusive=True)
    async def _generate_summary(self) -> None:
        """Use Claude to generate summary from selected message."""
        msg = self._get_selected_message()
        if not msg:
            self.notify("No message", severity="warning")
            return

        from .dialogs import LoadingDialog, EssenceDialog

        loading = LoadingDialog("Generating summary...")
        self.app.push_screen(loading)
        await asyncio.sleep(0.05)  # Let UI render

        try:
            claude = get_claude_client()
            summary = claude.extract_essence(msg.body)

            self.app.pop_screen()  # Remove loading
            self.app.push_screen(EssenceDialog(summary))

        except Exception as e:
            self.app.pop_screen()  # Remove loading
            self.notify(f"Error: {e}", severity="error")

    def action_timeline_summary(self) -> None:
        """Generate timeline summary of all messages in the thread."""
        self._generate_timeline_summary()

    @work(exclusive=True)
    async def _generate_timeline_summary(self) -> None:
        """Use Claude to generate timeline summary of the thread."""
        if not self.thread.messages:
            self.notify("No messages", severity="warning")
            return

        from .dialogs import LoadingDialog, EssenceDialog

        loading = LoadingDialog("Generating timeline...")
        self.app.push_screen(loading)
        await asyncio.sleep(0.05)  # Let UI render

        try:
            claude = get_claude_client()
            summary = claude.generate_timeline_summary(self.thread, self.user_email)

            self.app.pop_screen()  # Remove loading
            self.app.push_screen(EssenceDialog(summary))

        except Exception as e:
            self.app.pop_screen()  # Remove loading
            self.notify(f"Error: {e}", severity="error")

    def action_key_agreements(self) -> None:
        """Generate key agreements summary from all messages in the thread."""
        self._generate_key_agreements()

    @work(exclusive=True)
    async def _generate_key_agreements(self) -> None:
        """Use Claude to generate key agreements summary of the thread."""
        if not self.thread.messages:
            self.notify("No messages", severity="warning")
            return

        from .dialogs import LoadingDialog, EssenceDialog

        loading = LoadingDialog("Generating agreements...")
        self.app.push_screen(loading)
        await asyncio.sleep(0.05)  # Let UI render

        try:
            claude = get_claude_client()
            summary = claude.generate_key_agreements(self.thread, self.user_email)

            self.app.pop_screen()  # Remove loading
            self.app.push_screen(EssenceDialog(summary))

        except Exception as e:
            self.app.pop_screen()  # Remove loading
            self.notify(f"Error: {e}", severity="error")

    def action_ask_ai(self) -> None:
        """Open ask AI dialog."""
        from .dialogs import AskAIDialog

        def handle_result(question: str | None) -> None:
            if question is not None:
                self._process_ai_question(question)

        self.app.push_screen(AskAIDialog(), handle_result)

    @work(exclusive=True)
    async def _process_ai_question(self, question: str) -> None:
        """Process the AI question and show answer."""
        if not self.thread.messages:
            self.notify("No messages", severity="warning")
            return

        from .dialogs import LoadingDialog, AIAnswerDialog

        loading = LoadingDialog("Processing question...")
        self.app.push_screen(loading)
        await asyncio.sleep(0.05)  # Let UI render

        try:
            claude = get_claude_client()
            answer = claude.ask_question(question, self.thread, self.user_email)

            self.app.pop_screen()  # Remove loading
            self.app.push_screen(AIAnswerDialog(question, answer))

        except Exception as e:
            self.app.pop_screen()  # Remove loading
            self.notify(f"Error: {e}", severity="error")

    def action_generate(self) -> None:
        """Open generate dialog and then generate response."""
        from .dialogs import GenerateDialog

        def handle_result(result: Optional[tuple[str, list[str]]]) -> None:
            if result is not None:
                hints, selected_files = result
                app: "EmailAssistantApp" = self.app  # type: ignore
                app.open_draft_screen(
                    self.thread,
                    self.user_email,
                    self.is_forwarded,
                    hints,
                    optional_context_files=selected_files if selected_files else None,
                )

        self.app.push_screen(GenerateDialog(), handle_result)

    def action_compose(self) -> None:
        """Open compose screen with Compose.md snippet (skip AI generation)."""
        snippet_service = get_snippet_service()
        compose_content = snippet_service.get_compose_content()

        app: "EmailAssistantApp" = self.app  # type: ignore
        app.open_draft_screen(
            thread=self.thread,
            user_email=self.user_email,
            is_forwarded=self.is_forwarded,
            initial_content=compose_content,
        )

    def action_go_back(self) -> None:
        """Go back to previous screen and refresh the list."""
        app: "EmailAssistantApp" = self.app  # type: ignore
        app.pop_screen()

        current = app.screen
        if hasattr(current, "load_items"):
            current.load_items()

    def _pop_and_remove_from_parent_list(self) -> None:
        """Pop this screen and optimistically remove thread from parent list."""
        thread_id = self.thread.id
        self.app.pop_screen()

        parent = self.app.screen
        if hasattr(parent, "_remove_item_by_id"):
            parent._remove_item_by_id(thread_id)

    def _pop_and_update_reminder_in_parent(self, new_date, new_hour: int) -> None:
        """Pop this screen and update reminder in parent list (for reschedule)."""
        thread_id = self.thread.id
        self.app.pop_screen()

        parent = self.app.screen
        if not hasattr(parent, "items") or not hasattr(parent, "_refresh_list_item_display"):
            return

        # Find the reminder in parent's items
        for i, item in enumerate(parent.items):
            item_thread_id = getattr(item, "thread", None)
            if item_thread_id and getattr(item_thread_id, "id", None) == thread_id:
                # Update reminder in memory
                new_datetime = datetime.combine(new_date, time(hour=new_hour))
                item.scheduled_datetime = new_datetime
                item.is_outdated = False

                # Update status based on new time
                now = datetime.now()
                if new_datetime < now:
                    item.status = ReminderStatus.OVERDUE
                elif (new_datetime - now).total_seconds() < 3600:
                    item.status = ReminderStatus.UPCOMING
                else:
                    item.status = ReminderStatus.FUTURE

                # Refresh the display
                parent._refresh_list_item_display(i)
                break


class ThreadDetailScreen(ThreadDetailBase):
    """Unified screen for viewing email threads and reminders."""

    BINDINGS = [
        Binding("f", "reminder", "Reminder"),
        Binding("l", "mark_read", "Mark read"),
        Binding("d", "delete", "Delete"),
        Binding("x", "cancel_reminder", "Cancel reminder"),
    ]

    def __init__(
        self,
        thread: Thread,
        user_email: str,
        reminder: Optional[Reminder] = None,
    ) -> None:
        super().__init__(thread, user_email, reminder=reminder)
        self._cached_has_reminder: Optional[bool] = None

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Control action availability based on state."""
        if action == "cancel_reminder":
            return self._has_reminder()
        return True

    def _has_reminder(self) -> bool:
        """Check if this thread has a reminder."""
        # If we were opened with a reminder, we know it has one
        if self.reminder is not None:
            return True
        # Cache the result to avoid repeated API calls
        if self._cached_has_reminder is None:
            service = get_reminder_service()
            self._cached_has_reminder = service.has_reminder(self.thread.id)
        return self._cached_has_reminder

    def action_mark_read(self) -> None:
        """Open mark as read dialog."""
        from .dialogs import MarkAsReadDialog

        def handle_result(result: Optional[tuple[bool, Optional[str]]]) -> None:
            if result and result[0]:
                thread_id = self.thread.id
                label_id = result[1]

                self._pop_and_remove_from_parent_list()

                def do_mark_read():
                    gmail = get_gmail_client()
                    gmail.mark_as_read([thread_id], label_id)

                self._run_background_task(
                    do_mark_read, "Thread marked as read", "Mark read failed"
                )

        self.app.push_screen(MarkAsReadDialog(), handle_result)

    def action_delete(self) -> None:
        """Delete thread (remove reminder first if present, then trash)."""
        has_reminder = self._has_reminder()
        thread_id = self.thread.id

        self._pop_and_remove_from_parent_list()

        def do_delete():
            if has_reminder:
                service = get_reminder_service()
                service.remove_reminder(thread_id)
            gmail = get_gmail_client()
            gmail.trash_thread(thread_id)

        self._run_background_task(do_delete, "Moved to trash", "Delete failed")

    def action_cancel_reminder(self) -> None:
        """Cancel reminder and restore thread to inbox."""
        if not self._has_reminder():
            self.notify("Thread has no reminder set", severity="warning")
            return

        thread_id = self.thread.id
        self._pop_and_remove_from_parent_list()

        def do_cancel():
            service = get_reminder_service()
            service.remove_reminder(thread_id)
            gmail = get_gmail_client()
            gmail.add_labels_to_thread(thread_id, ["INBOX", "UNREAD"])

        self._run_background_task(
            do_cancel, "Reminder cancelled - thread moved to Inbox", "Cancel failed"
        )

    def action_reminder(self) -> None:
        """Set or reschedule reminder for this thread."""
        from .dialogs import RescheduleDialog

        def handle_result(result: Optional[tuple]) -> None:
            if result:
                reminder_date, reminder_hour = result
                thread_id = self.thread.id
                has_reminder = self._has_reminder()

                if has_reminder:
                    # Reschedule: update in place, don't remove
                    self._pop_and_update_reminder_in_parent(reminder_date, reminder_hour)
                    msg = f"Rescheduled to: {reminder_date.isoformat()} {reminder_hour}:00"
                else:
                    # New reminder: remove from inbox list
                    self._pop_and_remove_from_parent_list()
                    msg = f"Reminder set for: {reminder_date.isoformat()} {reminder_hour}:00"

                def do_set_reminder():
                    service = get_reminder_service()
                    if has_reminder:
                        service.reschedule_reminder(thread_id, reminder_date, reminder_hour)
                    else:
                        service.set_reminder(thread_id, reminder_date, reminder_hour)

                self._run_background_task(do_set_reminder, msg, "Reminder failed")

        self.app.push_screen(RescheduleDialog(), handle_result)
