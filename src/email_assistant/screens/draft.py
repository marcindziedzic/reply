"""Draft screen - view and edit generated email response."""

import re
import uuid
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, Static, TextArea

from .widgets import ContactsInput
from ..claude import get_claude_client
from ..config import get_config
from ..gmail import get_gmail_client
from ..models import Thread
from ..services.reminder_service import get_reminder_service

if TYPE_CHECKING:
    from ..app import EmailAssistantApp


class DraftScreen(Screen):
    """Screen for viewing and editing draft response."""

    BINDINGS = [
        Binding("e", "edit", "Edit"),
        Binding("a", "attach", "Attach"),
        Binding("s", "save_draft", "Save draft"),
        Binding("w", "send", "Send"),
        Binding("W", "send_with_reminder", "Send+Reminder"),
        Binding("L", "send_with_label", "Send+Label"),
        Binding("r", "regenerate", "Regenerate"),
        Binding("b", "go_back", "Back"),
        Binding("escape", "go_back", "Back", show=False),
        Binding("f2", "insert_snippet", "Snippet", show=False),
        Binding("f3", "insert_link", "Link", show=False),
        Binding("f4", "insert_image", "Image", show=False),
    ]

    CSS = """
    DraftScreen {
        background: $surface;
    }

    #draft-container {
        width: 100%;
        height: 100%;
        padding: 1;
    }

    #draft-header {
        text-style: bold;
        margin-bottom: 1;
    }

    #forwarded-notice {
        background: $warning 30%;
        padding: 0 1;
        margin-bottom: 1;
        color: $text;
    }

    #recipient-container {
        height: auto;
        margin-bottom: 1;
    }

    #recipient-label {
        margin-bottom: 0;
    }

    #recipient-input {
        width: 100%;
    }

    #subject-label {
        margin-bottom: 0;
        margin-top: 1;
    }

    #subject-input {
        width: 100%;
    }

    #loading-label {
        text-align: center;
        margin-top: 2;
    }

    #draft-content {
        width: 100%;
        padding: 1;
        background: $surface;
    }

    #draft-textarea {
        width: 100%;
        height: 100%;
        min-height: 20;
    }

    #view-mode-container {
        width: 100%;
        height: 1fr;
        padding: 1;
        background: $panel;
        border: solid $primary;
    }

    #edit-mode-container {
        width: 100%;
        height: 1fr;
        padding: 1;
    }

    .status-label {
        text-align: center;
        margin-top: 1;
        color: $success;
    }

    #attachments-container {
        height: auto;
        max-height: 6;
        margin-bottom: 1;
        padding: 0 1;
    }

    #attachments-label {
        text-style: bold;
        margin-bottom: 0;
    }

    #attachments-list {
        height: auto;
    }

    .attachment-item {
        height: auto;
        margin: 0;
        padding: 0;
    }

    .attachment-button {
        min-width: 0;
        height: 1;
        margin: 0;
        padding: 0 1;
        background: $primary 30%;
        border: none;
    }

    .attachment-button:hover {
        background: $primary 50%;
    }

    .remove-attachment {
        min-width: 3;
        height: 1;
        margin: 0 0 0 1;
        padding: 0;
        background: $error 30%;
        border: none;
        color: $error;
    }

    .remove-attachment:hover {
        background: $error 50%;
    }
    """

    def __init__(
        self,
        thread: Thread,
        user_email: str,
        is_forwarded: bool = False,
        initial_hints: Optional[str] = None,
        initial_content: Optional[str] = None,
        optional_context_files: Optional[list[str]] = None,
    ) -> None:
        super().__init__()
        self.thread = thread
        self.user_email = user_email
        self.is_forwarded = is_forwarded
        self.initial_hints = initial_hints
        self.initial_content = initial_content
        self.optional_context_files = optional_context_files or []
        self.draft_text = ""
        self.is_editing = False
        self.recipient_email = ""
        self.subject = ""
        self.attachments: list[Path] = []  # List of file paths to attach
        self.inline_images: dict[str, Path] = {}  # cid -> file path for inline images

        # Reminder scheduling (set after send)
        self._pending_reminder_date: Optional[date] = None
        self._pending_reminder_hour: int = 11

        # For forwarded emails, get recipient from Reply-To header
        if self.is_forwarded:
            self._extract_recipient_from_forwarded()

    def _extract_recipient_from_forwarded(self) -> None:
        """Get recipient email from Reply-To header for forwarded emails."""
        config = get_config()
        forwarding_config = None

        # Search all messages in thread for Reply-To header and forwarding config
        for msg in self.thread.messages:
            if msg.sender_email.lower() != self.user_email.lower():
                if msg.reply_to:
                    self.recipient_email = msg.reply_to
                # Get forwarding config for this sender
                if forwarding_config is None:
                    forwarding_config = config.gmail.get_forwarding_config(msg.sender_email)
                if self.recipient_email:
                    break

        # Use configured default subject for this forwarding address, or fall back to thread subject
        if forwarding_config and forwarding_config.default_subject:
            self.subject = forwarding_config.default_subject
        elif self.thread.subject:
            subject = self.thread.subject
            if not subject.lower().startswith("re:"):
                subject = f"Re: {subject}"
            self.subject = subject

    def compose(self) -> ComposeResult:
        """Compose the screen."""
        recipient_email = self.thread.get_reply_recipient(self.user_email)

        # Determine header text
        if self.thread.id == "__new__":
            header_text = "New message"
        else:
            header_text = f"{self.thread.subject} | To: {recipient_email}"

        yield Header()
        with Vertical(id="draft-container"):
            yield Static(header_text, id="draft-header")

            # Show recipient input for forwarded/new emails
            if self.is_forwarded:
                if self.thread.id == "__new__":
                    notice_text = "New message - enter recipient and subject"
                else:
                    notice_text = "[Forwarded] This email requires recipient and subject"
                yield Static(notice_text, id="forwarded-notice")
                with Container(id="recipient-container"):
                    yield Label("Recipient email:", id="recipient-label")
                    yield ContactsInput(
                        value=self.recipient_email,
                        placeholder="e.g. client@example.com",
                        input_id="recipient-input",
                    )
                    yield Label("Subject:", id="subject-label")
                    yield Input(
                        value=self.subject,
                        placeholder="e.g. Re: Product inquiry",
                        id="subject-input",
                    )

            # Attachments container (hidden initially if no attachments)
            with Container(id="attachments-container"):
                yield Label("Attachments:", id="attachments-label")
                yield Vertical(id="attachments-list")

            yield Label("Generating response...", id="loading-label")
            with VerticalScroll(id="view-mode-container"):
                yield Static("", id="draft-content")
            with Container(id="edit-mode-container"):
                yield TextArea(id="draft-textarea")
        yield Footer()

    def on_mount(self) -> None:
        """Handle screen mount."""
        # Hide edit mode initially
        self.query_one("#edit-mode-container").display = False
        # Hide attachments container initially (show when attachments added)
        self.query_one("#attachments-container").display = False

        # Show notification about Reply-To for forwarded messages (not for new messages)
        if self.is_forwarded and self.thread.id != "__new__":
            if self.recipient_email:
                self.notify(f"Reply-To: {self.recipient_email}")
            else:
                self.notify("No Reply-To header - enter manually", severity="warning")

        # For new messages or if initial_content is provided, go to edit mode
        if self.thread.id == "__new__" or self.initial_content is not None:
            self._set_initial_content()
        else:
            self.generate_draft(optional_context_files=self.optional_context_files)

    def _set_initial_content(self) -> None:
        """Set initial content without generating via Claude - goes directly to edit mode."""
        loading_label = self.query_one("#loading-label", Label)
        view_container = self.query_one("#view-mode-container", VerticalScroll)
        edit_container = self.query_one("#edit-mode-container")

        # Replace placeholders in initial content
        self.draft_text = self._replace_placeholders(self.initial_content or "")

        # Hide loading and view mode
        loading_label.display = False
        view_container.display = False

        # Go directly to edit mode
        self.is_editing = True
        edit_container.display = True

        textarea = self.query_one("#draft-textarea", TextArea)
        textarea.load_text(self.draft_text)
        textarea.focus()

    @work(exclusive=True)
    async def generate_draft(
        self,
        hints: Optional[str] = None,
        optional_context_files: Optional[list[str]] = None,
        is_regeneration: bool = False,
    ) -> None:
        """Generate draft response using Claude.

        Args:
            hints: Additional hints for generation
            optional_context_files: List of optional context files to include
            is_regeneration: If True, this is a regeneration request
        """
        loading_label = self.query_one("#loading-label", Label)
        view_container = self.query_one("#view-mode-container", VerticalScroll)
        draft_content = self.query_one("#draft-content", Static)

        loading_label.display = True
        if is_regeneration:
            loading_label.update("Regenerating response with Claude...")
        else:
            loading_label.update("Generating response with Claude...")
        view_container.display = False

        try:
            claude = get_claude_client()

            # Get sender email for context
            sender_email = ""
            for msg in self.thread.messages:
                if msg.sender_email.lower() != self.user_email.lower():
                    sender_email = msg.sender_email
                    break

            if is_regeneration:
                # For regeneration, pass previous response and original hints
                self.draft_text = claude.generate_response(
                    client_email=sender_email,
                    threads=[self.thread],
                    user_email=self.user_email,
                    hints=hints,  # New hints for modification
                    optional_context_files=optional_context_files,
                    previous_response=self.draft_text,
                    original_hints=self.initial_hints,
                )
            else:
                # First generation - use initial hints
                use_hints = hints if hints is not None else self.initial_hints
                self.draft_text = claude.generate_response(
                    client_email=sender_email,
                    threads=[self.thread],
                    user_email=self.user_email,
                    hints=use_hints,
                    optional_context_files=optional_context_files,
                )

            # Update view
            loading_label.display = False
            view_container.display = True
            draft_content.update(self.draft_text)

            # Also update textarea in case user switches to edit mode
            textarea = self.query_one("#draft-textarea", TextArea)
            textarea.load_text(self.draft_text)

        except Exception as e:
            loading_label.update(f"Generation error: {e}")

    def action_edit(self) -> None:
        """Switch to edit mode."""
        if self.is_editing:
            return

        self.is_editing = True

        # Hide view mode, show edit mode
        self.query_one("#view-mode-container").display = False
        edit_container = self.query_one("#edit-mode-container")
        edit_container.display = True

        # Set textarea content and focus
        textarea = self.query_one("#draft-textarea", TextArea)
        textarea.load_text(self.draft_text)
        textarea.focus()

        # Update bindings hint
        self.notify("Ctrl+S save | Esc cancel | F2 snippet | F3 link | F4 image")

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Handle text area changes."""
        if self.is_editing:
            self.draft_text = event.text_area.text

    def on_key(self, event) -> None:
        """Handle key events."""
        if self.is_editing:
            if event.key == "ctrl+s":
                self._finish_editing()
                event.prevent_default()
                event.stop()
            elif event.key == "escape":
                self._cancel_editing()
                event.prevent_default()
                event.stop()
            elif event.key == "f2":
                self.action_insert_snippet()
                event.prevent_default()
                event.stop()
            elif event.key == "f3":
                self.action_insert_link()
                event.prevent_default()
                event.stop()
            elif event.key == "f4":
                self.action_insert_image()
                event.prevent_default()
                event.stop()

    def action_insert_snippet(self) -> None:
        """Open snippet selection dialog (only in edit mode)."""
        if not self.is_editing:
            self.notify("Enter edit mode [e] to insert snippet")
            return

        from .dialogs import SnippetDialog

        def handle_snippet(snippet) -> None:
            if snippet is not None:
                self._insert_snippet(snippet.content)
                # Return focus to textarea
                self.query_one("#draft-textarea", TextArea).focus()

        self.app.push_screen(SnippetDialog(), handle_snippet)

    def action_insert_link(self) -> None:
        """Open link insertion dialog (only in edit mode)."""
        if not self.is_editing:
            self.notify("Enter edit mode [e] to insert link")
            return

        from .dialogs import InsertLinkDialog

        def handle_link(result) -> None:
            if result is not None:
                name, url = result
                link_text = f"[{name}]({url})"
                self._insert_text_at_cursor(link_text)
                # Return focus to textarea
                self.query_one("#draft-textarea", TextArea).focus()

        self.app.push_screen(InsertLinkDialog(), handle_link)

    def action_insert_image(self) -> None:
        """Open file picker to insert inline image (only in edit mode)."""
        if not self.is_editing:
            self.notify("Enter edit mode [e] to insert image")
            return

        file_path = self._open_image_file_dialog()
        if file_path:
            self._insert_inline_image(file_path)

    def _open_image_file_dialog(self) -> Optional[str]:
        """Open native Windows file dialog for images using ctypes."""
        import ctypes
        from ctypes import wintypes

        # Windows API constants
        OFN_FILEMUSTEXIST = 0x00001000
        OFN_PATHMUSTEXIST = 0x00000800
        OFN_NOCHANGEDIR = 0x00000008

        # OPENFILENAMEW structure
        class OPENFILENAMEW(ctypes.Structure):
            _fields_ = [
                ("lStructSize", wintypes.DWORD),
                ("hwndOwner", wintypes.HWND),
                ("hInstance", wintypes.HINSTANCE),
                ("lpstrFilter", wintypes.LPCWSTR),
                ("lpstrCustomFilter", wintypes.LPWSTR),
                ("nMaxCustFilter", wintypes.DWORD),
                ("nFilterIndex", wintypes.DWORD),
                ("lpstrFile", wintypes.LPWSTR),
                ("nMaxFile", wintypes.DWORD),
                ("lpstrFileTitle", wintypes.LPWSTR),
                ("nMaxFileTitle", wintypes.DWORD),
                ("lpstrInitialDir", wintypes.LPCWSTR),
                ("lpstrTitle", wintypes.LPCWSTR),
                ("Flags", wintypes.DWORD),
                ("nFileOffset", wintypes.WORD),
                ("nFileExtension", wintypes.WORD),
                ("lpstrDefExt", wintypes.LPCWSTR),
                ("lCustData", wintypes.LPARAM),
                ("lpfnHook", ctypes.c_void_p),
                ("lpTemplateName", wintypes.LPCWSTR),
                ("pvReserved", ctypes.c_void_p),
                ("dwReserved", wintypes.DWORD),
                ("FlagsEx", wintypes.DWORD),
            ]

        # File filter (null-separated, double-null terminated)
        filter_str = "Images (*.png;*.jpg;*.jpeg;*.gif;*.webp;*.bmp)\0*.png;*.jpg;*.jpeg;*.gif;*.webp;*.bmp\0All files (*.*)\0*.*\0\0"

        # Buffer for file path
        file_buffer = ctypes.create_unicode_buffer(260)

        ofn = OPENFILENAMEW()
        ofn.lStructSize = ctypes.sizeof(OPENFILENAMEW)
        ofn.hwndOwner = None
        ofn.lpstrFilter = filter_str
        ofn.lpstrFile = ctypes.cast(file_buffer, wintypes.LPWSTR)
        ofn.nMaxFile = 260
        ofn.lpstrTitle = "Select image to insert"
        ofn.Flags = OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_NOCHANGEDIR

        # Call GetOpenFileNameW
        comdlg32 = ctypes.windll.comdlg32
        if comdlg32.GetOpenFileNameW(ctypes.byref(ofn)):
            return file_buffer.value
        return None

    def _insert_inline_image(self, file_path: str) -> None:
        """Insert inline image at cursor position."""
        path = Path(file_path)

        # Check file size (max 10MB for inline images)
        max_size = 10 * 1024 * 1024
        if path.stat().st_size > max_size:
            self.notify("Image too large (max 10MB)", severity="error")
            return

        # Generate unique content ID
        cid = f"img_{uuid.uuid4().hex[:8]}"

        # Store mapping
        self.inline_images[cid] = path

        # Insert markdown at cursor
        markdown_img = f"![{path.name}](cid:{cid})"
        self._insert_text_at_cursor(markdown_img)

        self.notify(f"Image inserted: {path.name}")

    def _insert_text_at_cursor(self, text: str) -> None:
        """Insert text at cursor position in textarea."""
        textarea = self.query_one("#draft-textarea", TextArea)

        # Get current cursor position
        cursor_location = textarea.cursor_location

        # Get current text
        current_text = textarea.text
        lines = current_text.split("\n")

        # Calculate character offset
        row, col = cursor_location
        if row < len(lines):
            # Build text before and after cursor
            before_lines = lines[:row]
            current_line = lines[row] if row < len(lines) else ""
            after_lines = lines[row + 1:] if row + 1 < len(lines) else []

            before_cursor = current_line[:col]
            after_cursor = current_line[col:]

            # Insert text
            text_lines = text.split("\n")

            if len(text_lines) == 1:
                # Single line text
                new_current_line = before_cursor + text_lines[0] + after_cursor
                new_lines = before_lines + [new_current_line] + after_lines
            else:
                # Multi-line text
                first_part = before_cursor + text_lines[0]
                middle_parts = text_lines[1:-1]
                last_part = text_lines[-1] + after_cursor

                new_lines = before_lines + [first_part] + middle_parts + [last_part] + after_lines

            new_text = "\n".join(new_lines)
            textarea.load_text(new_text)

            # Move cursor to end of inserted content
            new_row = row + len(text_lines) - 1
            if len(text_lines) == 1:
                new_col = col + len(text_lines[0])
            else:
                new_col = len(text_lines[-1])

            textarea.move_cursor((new_row, new_col))
            self.draft_text = new_text
            self.notify("Link inserted")

    def _replace_placeholders(self, content: str) -> str:
        """Replace placeholders like [Name], [Role], etc. with user settings."""
        config = get_config()
        placeholders = config.user.get_placeholders()

        for placeholder, value in placeholders.items():
            if value:  # Only replace if value is set
                content = content.replace(placeholder, value)

        return content

    def _insert_snippet(self, content: str) -> None:
        """Insert snippet content at cursor position in textarea."""
        # Replace placeholders with user settings
        content = self._replace_placeholders(content)

        textarea = self.query_one("#draft-textarea", TextArea)

        # Get current cursor position
        cursor_location = textarea.cursor_location

        # Get current text
        current_text = textarea.text
        lines = current_text.split("\n")

        # Calculate character offset
        row, col = cursor_location
        if row < len(lines):
            # Build text before and after cursor
            before_lines = lines[:row]
            current_line = lines[row] if row < len(lines) else ""
            after_lines = lines[row + 1:] if row + 1 < len(lines) else []

            before_cursor = current_line[:col]
            after_cursor = current_line[col:]

            # Insert snippet content
            snippet_lines = content.split("\n")

            if len(snippet_lines) == 1:
                # Single line snippet
                new_current_line = before_cursor + snippet_lines[0] + after_cursor
                new_lines = before_lines + [new_current_line] + after_lines
            else:
                # Multi-line snippet
                first_part = before_cursor + snippet_lines[0]
                middle_parts = snippet_lines[1:-1]
                last_part = snippet_lines[-1] + after_cursor

                new_lines = before_lines + [first_part] + middle_parts + [last_part] + after_lines

            new_text = "\n".join(new_lines)
            textarea.load_text(new_text)

            # Move cursor to end of inserted content
            new_row = row + len(snippet_lines) - 1
            if len(snippet_lines) == 1:
                new_col = col + len(snippet_lines[0])
            else:
                new_col = len(snippet_lines[-1])

            textarea.move_cursor((new_row, new_col))
            self.draft_text = new_text
            self.notify("Snippet inserted")

    def _finish_editing(self) -> None:
        """Finish editing and return to view mode."""
        if not self.is_editing:
            return

        self.is_editing = False

        # Get text from textarea
        textarea = self.query_one("#draft-textarea", TextArea)
        self.draft_text = textarea.text

        # Update view
        draft_content = self.query_one("#draft-content", Static)
        draft_content.update(self.draft_text)

        # Switch to view mode
        self.query_one("#edit-mode-container").display = False
        self.query_one("#view-mode-container").display = True

        self.notify("Changes saved")

    def _cancel_editing(self) -> None:
        """Cancel editing and return to view mode."""
        if not self.is_editing:
            return

        self.is_editing = False

        # Switch to view mode without saving changes
        self.query_one("#edit-mode-container").display = False
        self.query_one("#view-mode-container").display = True

    def action_save_draft(self) -> None:
        """Save as Gmail draft."""
        if not self.draft_text.strip():
            self.notify("No content to save", severity="warning")
            return

        # For forwarded emails, get recipient and subject from inputs
        if self.is_forwarded:
            try:
                recipient_input = self.query_one("#recipient-input", Input)
                subject_input = self.query_one("#subject-input", Input)

                self.recipient_email = recipient_input.value.strip()
                self.subject = subject_input.value.strip()

                if not self.recipient_email:
                    self.notify("Enter recipient email", severity="warning")
                    recipient_input.focus()
                    return

                if not self.subject:
                    self.notify("Enter subject", severity="warning")
                    subject_input.focus()
                    return

            except Exception:
                pass

        self._save_to_gmail()

    @work(exclusive=True)
    async def _save_to_gmail(self) -> None:
        """Save draft to Gmail."""
        try:
            gmail = get_gmail_client()

            # Load attachment and inline images data
            attachments = self._get_attachments_data() if self.attachments else None
            inline_images = self._get_inline_images_data() if self.inline_images else None

            if self.is_forwarded:
                # Create a NEW draft (not a reply) for forwarded emails
                gmail.create_new_draft(
                    recipient=self.recipient_email,
                    subject=self.subject,
                    message_body=self.draft_text,
                    attachments=attachments,
                    inline_images=inline_images,
                )
                self.notify("New draft created in Gmail!", severity="information")
            else:
                # Normal reply draft
                gmail.create_draft(
                    self.thread.id,
                    self.draft_text,
                    attachments=attachments,
                    inline_images=inline_images,
                )
                self.notify("Draft saved to Gmail!", severity="information")

        except Exception as e:
            self.notify(f"Save error: {e}", severity="error")

    def _validate_send(self) -> bool:
        """Validate that we can send the email. Returns True if valid."""
        if not self.draft_text.strip():
            self.notify("No content to send", severity="warning")
            return False

        # For forwarded emails, get recipient and subject from inputs
        if self.is_forwarded:
            try:
                contacts_input = self.query_one(ContactsInput)
                subject_input = self.query_one("#subject-input", Input)

                self.recipient_email = contacts_input.value.strip()
                self.subject = subject_input.value.strip()

                if not self.recipient_email:
                    self.notify("Enter recipient email", severity="warning")
                    contacts_input.focus()
                    return False

                if not self.subject:
                    self.notify("Enter subject", severity="warning")
                    subject_input.focus()
                    return False

            except Exception:
                pass

        # Check for unreplaced variables like {variableName}
        unreplaced = re.findall(r'\{([a-zA-Z][a-zA-Z0-9_]*)\}', self.draft_text)
        if unreplaced:
            from .dialogs import WarningDialog

            vars_list = ", ".join(f"{{{v}}}" for v in unreplaced)

            def focus_editor(_) -> None:
                """Focus the text editor after dialog closes."""
                self.action_edit()

            self.app.push_screen(
                WarningDialog(
                    title="Unreplaced variables",
                    message=f"Fill in values before sending:\n{vars_list}",
                ),
                focus_editor,
            )
            return False

        return True

    def _get_confirm_info(self) -> tuple[str, str]:
        """Get recipient and subject for confirmation dialog."""
        if self.is_forwarded:
            return self.recipient_email, self.subject
        else:
            return self.thread.get_reply_recipient(self.user_email), self.thread.subject

    def action_send(self) -> None:
        """Send email without reminder."""
        if not self._validate_send():
            return

        from .dialogs import SendConfirmDialog

        confirm_recipient, confirm_subject = self._get_confirm_info()

        def handle_confirm(confirmed: bool) -> None:
            if confirmed:
                self._send_to_gmail(with_reminder=False)

        self.app.push_screen(
            SendConfirmDialog(confirm_recipient, confirm_subject),
            handle_confirm
        )

    def action_send_with_reminder(self) -> None:
        """Send email and set reminder."""
        if not self._validate_send():
            return

        from .dialogs import SendConfirmDialog

        confirm_recipient, confirm_subject = self._get_confirm_info()

        def handle_confirm(confirmed: bool) -> None:
            if confirmed:
                self._send_to_gmail(with_reminder=True)

        self.app.push_screen(
            SendConfirmDialog(confirm_recipient, confirm_subject),
            handle_confirm
        )

    def action_send_with_label(self) -> None:
        """Send email and set a label (removing any reminder labels)."""
        if not self._validate_send():
            return

        from .dialogs import SendConfirmDialog

        confirm_recipient, confirm_subject = self._get_confirm_info()

        def handle_confirm(confirmed: bool) -> None:
            if confirmed:
                self._send_to_gmail_with_label()

        self.app.push_screen(
            SendConfirmDialog(confirm_recipient, confirm_subject),
            handle_confirm
        )

    @work(exclusive=True)
    async def _send_to_gmail_with_label(self) -> None:
        """Send email via Gmail and then prompt for label selection."""
        try:
            gmail = get_gmail_client()

            # Load attachment and inline images data
            attachments = self._get_attachments_data() if self.attachments else None
            inline_images = self._get_inline_images_data() if self.inline_images else None

            # Determine thread ID for labeling
            thread_id: str = ""

            if self.is_forwarded:
                # Send as new message for forwarded/new emails
                result = gmail.send_new_message(
                    recipient=self.recipient_email,
                    subject=self.subject,
                    message_body=self.draft_text,
                    attachments=attachments,
                    inline_images=inline_images,
                )
                # Get thread ID from the response
                thread_id = result.get("threadId", "")
            else:
                # Send as reply
                gmail.send_reply(
                    self.thread.id,
                    self.draft_text,
                    attachments=attachments,
                    inline_images=inline_images,
                )
                thread_id = self.thread.id

            # Store thread_id for label assignment
            self._pending_thread_id = thread_id

            # Show label picker
            self._show_label_picker_after_send()

        except Exception as e:
            self.notify(f"Send error: {e}", severity="error")

    def _show_label_picker_after_send(self) -> None:
        """Show dialog to pick label after sending."""
        from .dialogs import MarkAsReadDialog

        def handle_result(result: Optional[tuple[bool, Optional[str]]]) -> None:
            if result and result[0]:
                # User selected a label (or no label)
                label_id = result[1]
                self._apply_label_after_send(label_id)
            else:
                # User cancelled - still archive and remove reminders
                self._apply_label_after_send(None)

        self.app.push_screen(MarkAsReadDialog(), handle_result)

    @work(exclusive=True)
    async def _apply_label_after_send(self, label_id: Optional[str]) -> None:
        """Apply label after sending message (also removes reminder labels)."""
        try:
            gmail = get_gmail_client()
            reminder_service = get_reminder_service()

            # mark_as_read removes UNREAD, INBOX, and any Reminders/* labels
            # and optionally adds the selected label
            gmail.mark_as_read([self._pending_thread_id], label_id=label_id, archive=True)

            # Also remove from local reminder tracking
            reminder_service.remove_reminder(self._pending_thread_id)

            if label_id:
                self.notify("Sent and labeled!", severity="information")
            else:
                self.notify("Sent and archived!", severity="information")
            self.app.pop_screen()
        except Exception as e:
            self.notify(f"Sent, but labeling error: {e}", severity="error")
            self.app.pop_screen()

    @work(exclusive=True)
    async def _send_to_gmail(self, with_reminder: bool = False) -> None:
        """Send email via Gmail.

        Args:
            with_reminder: If True, set a reminder after sending.
        """
        try:
            gmail = get_gmail_client()

            # Load attachment and inline images data
            attachments = self._get_attachments_data() if self.attachments else None
            inline_images = self._get_inline_images_data() if self.inline_images else None

            # Determine thread ID for reminder
            thread_id: str = ""

            if self.is_forwarded:
                # Send as new message for forwarded/new emails
                result = gmail.send_new_message(
                    recipient=self.recipient_email,
                    subject=self.subject,
                    message_body=self.draft_text,
                    attachments=attachments,
                    inline_images=inline_images,
                )
                # Get thread ID from the response
                thread_id = result.get("threadId", "")
            else:
                # Send as reply
                gmail.send_reply(
                    self.thread.id,
                    self.draft_text,
                    attachments=attachments,
                    inline_images=inline_images,
                )
                thread_id = self.thread.id

            # Archive thread (remove from INBOX) and remove reminder after sending reply
            if not self.is_forwarded:
                gmail.mark_as_read([self.thread.id], archive=True)
                # Also remove any existing reminder for this thread
                reminder_service = get_reminder_service()
                reminder_service.remove_reminder(self.thread.id)

            if with_reminder and thread_id:
                # Store thread_id for reminder
                self._pending_thread_id = thread_id

                # Show dialog to choose reminder time first
                self._show_reminder_picker()
            else:
                # Just notify and go back
                self.notify("Message sent!", severity="information")
                self.app.pop_screen()

        except Exception as e:
            self.notify(f"Send error: {e}", severity="error")

    def _show_reminder_picker(self) -> None:
        """Show dialog to pick reminder time after sending."""
        from .dialogs import RescheduleDialog

        def handle_result(result: Optional[tuple]) -> None:
            if result:
                reminder_date, reminder_hour = result
                self._set_reminder_after_send(reminder_date, reminder_hour)
            else:
                # User cancelled - no reminder
                self.notify("Message sent (no reminder)", severity="information")
                self.app.pop_screen()

        self.app.push_screen(
            RescheduleDialog(for_sent_message=True),
            handle_result,
        )

    @work(exclusive=True)
    async def _set_reminder_after_send(self, reminder_date: date, reminder_hour: int) -> None:
        """Set reminder after sending message."""
        try:
            service = get_reminder_service()
            service.set_reminder(self._pending_thread_id, reminder_date, reminder_hour)
            self.notify(f"Sent! Reminder: {reminder_date.isoformat()} {reminder_hour}:00")
            self.app.pop_screen()
        except Exception as e:
            self.notify(f"Sent, but reminder error: {e}", severity="error")
            self.app.pop_screen()

    def action_regenerate(self) -> None:
        """Open regenerate dialog."""
        from .dialogs import RegenerateDialog

        def handle_result(result: Optional[tuple[str, list[str]]]) -> None:
            if result is not None:
                hints, selected_files = result
                self.generate_draft(
                    hints if hints else None,
                    optional_context_files=selected_files if selected_files else None,
                    is_regeneration=True,
                )

        self.app.push_screen(RegenerateDialog(), handle_result)

    def action_attach(self) -> None:
        """Open native file picker dialog."""
        import tkinter as tk
        from tkinter import filedialog

        # Create hidden root window
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)  # Bring to front

        file_path = filedialog.askopenfilename(
            title="Select file to attach",
            filetypes=[
                ("All files", "*.*"),
                ("PDF", "*.pdf"),
                ("Documents", "*.doc;*.docx;*.odt"),
                ("Images", "*.png;*.jpg;*.jpeg;*.gif"),
                ("Spreadsheets", "*.xls;*.xlsx;*.csv"),
            ],
        )

        root.destroy()

        if file_path:
            self._add_attachment(file_path)

    def _add_attachment(self, file_path: str) -> None:
        """Add an attachment to the list."""
        path = Path(file_path)

        # Check if already attached
        if path in self.attachments:
            self.notify("File already added", severity="warning")
            return

        # Check file size (Gmail limit: 25MB)
        max_size = 25 * 1024 * 1024
        if path.stat().st_size > max_size:
            self.notify("File too large (max 25MB)", severity="error")
            return

        self.attachments.append(path)
        self._update_attachments_display()
        self.notify(f"Added: {path.name}")

    def _remove_attachment(self, index: int) -> None:
        """Remove an attachment from the list."""
        if 0 <= index < len(self.attachments):
            removed = self.attachments.pop(index)
            self._update_attachments_display()
            self.notify(f"Removed: {removed.name}")

    def _update_attachments_display(self) -> None:
        """Update the attachments list display."""
        container = self.query_one("#attachments-container")
        attachments_list = self.query_one("#attachments-list", Vertical)

        # Show/hide container based on whether there are attachments
        container.display = len(self.attachments) > 0

        # Clear existing items
        attachments_list.remove_children()

        # Add items for each attachment
        for i, path in enumerate(self.attachments):
            # Format file size
            size = path.stat().st_size
            if size < 1024:
                size_str = f"{size} B"
            elif size < 1024 * 1024:
                size_str = f"{size / 1024:.1f} KB"
            else:
                size_str = f"{size / (1024 * 1024):.1f} MB"

            item = Horizontal(classes="attachment-item")
            item.compose_add_child(
                Button(f"{path.name} ({size_str})", classes="attachment-button", id=f"att-{i}")
            )
            item.compose_add_child(
                Button("X", classes="remove-attachment", id=f"rm-att-{i}")
            )
            attachments_list.mount(item)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses (for attachment removal)."""
        button_id = event.button.id or ""
        if button_id.startswith("rm-att-"):
            try:
                index = int(button_id[7:])  # Remove "rm-att-" prefix
                self._remove_attachment(index)
            except (ValueError, IndexError):
                pass

    def _get_attachments_data(self) -> list[tuple[str, bytes]]:
        """Load attachment files and return as (filename, bytes) tuples."""
        result = []
        for path in self.attachments:
            try:
                content = path.read_bytes()
                result.append((path.name, content))
            except Exception as e:
                self.notify(f"Read error {path.name}: {e}", severity="error")
        return result

    def _get_inline_images_data(self) -> dict[str, tuple[str, bytes]]:
        """Load inline image files and return as {cid: (filename, bytes)} dict."""
        result = {}
        for cid, path in self.inline_images.items():
            try:
                content = path.read_bytes()
                result[cid] = (path.name, content)
            except Exception as e:
                self.notify(f"Read error {path.name}: {e}", severity="error")
        return result

    def action_go_back(self) -> None:
        """Go back to thread screen."""
        if self.is_editing:
            self._cancel_editing()
            return

        self.app.pop_screen()
