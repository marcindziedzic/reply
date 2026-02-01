"""Main Textual application for Email Assistant."""

from typing import TYPE_CHECKING, Optional

from textual.app import App

# Only LoadingScreen is imported eagerly - it's lightweight
from .screens.loading import LoadingScreen

# Heavy imports are deferred to avoid slow startup
if TYPE_CHECKING:
    from .models import Message, Thread
    from .services.reminder_service import Reminder


class EmailAssistantApp(App):
    """Main Email Assistant application."""

    TITLE = "Email Assistant v0.1"

    CSS = """
    Screen {
        background: $surface;
    }
    """

    def on_mount(self) -> None:
        """Handle app mount."""
        # Show loading screen with initialization progress
        self.push_screen(LoadingScreen())

    def open_thread_screen(
        self,
        thread: "Thread",
        user_email: str,
        reminder: "Optional[Reminder]" = None,
    ) -> None:
        """Open the thread view screen."""
        from .screens.thread_detail import ThreadDetailScreen

        self.push_screen(ThreadDetailScreen(thread, user_email, reminder))

    def open_draft_screen(
        self,
        thread: "Thread",
        user_email: str,
        is_forwarded: bool = False,
        hints: str = "",
        initial_content: Optional[str] = None,
        optional_context_files: Optional[list[str]] = None,
    ) -> None:
        """Open the draft screen.

        If initial_content is provided (even empty string), skip AI generation.
        """
        from .screens.draft import DraftScreen

        self.push_screen(DraftScreen(
            thread,
            user_email,
            is_forwarded,
            hints or None,
            initial_content=initial_content,
            optional_context_files=optional_context_files,
        ))

    def open_reminders_screen(self) -> None:
        """Open the reminders screen."""
        from .screens.reminders import RemindersScreen

        self.push_screen(RemindersScreen())

    def open_new_message_screen(
        self,
        user_email: str,
        recipient: str,
        subject: str,
    ) -> None:
        """Open draft screen for a new message (not a reply)."""
        from .models import Thread
        from .screens.draft import DraftScreen
        from .services.snippet_service import get_snippet_service

        # Load Compose.md snippet
        snippet_service = get_snippet_service()
        compose_content = snippet_service.get_compose_content()

        # Create a dummy thread for new message
        dummy_thread = Thread(
            id="__new__",
            subject=subject,
            messages=[],
        )

        # Open DraftScreen in "new message" mode with Compose.md content
        screen = DraftScreen(
            dummy_thread,
            user_email,
            is_forwarded=True,  # This enables recipient/subject inputs
            initial_content=compose_content,
        )
        # Pre-fill recipient and subject
        screen.recipient_email = recipient
        screen.subject = subject

        self.push_screen(screen)

    def open_forward_screen(
        self,
        thread: "Thread",
        user_email: str,
        recipients: str,
    ) -> None:
        """Open draft screen for forwarding an email.

        Args:
            thread: The thread to forward.
            user_email: Current user's email address.
            recipients: Comma-separated recipient email addresses.
        """
        from .models import Thread as ThreadModel
        from .screens.draft import DraftScreen

        # Get the last message to forward
        if not thread.messages:
            return

        last_message = thread.messages[-1]

        # Format the forwarded message content
        forward_content = self._format_forward_content(last_message)

        # Create subject with "Fwd: " prefix
        subject = thread.subject
        if not subject.lower().startswith("fwd:"):
            subject = f"Fwd: {subject}"

        # Create a dummy thread for the forward
        dummy_thread = ThreadModel(
            id="__forward__",
            subject=subject,
            messages=[],
        )

        # Open DraftScreen in forward mode
        screen = DraftScreen(
            dummy_thread,
            user_email,
            is_forwarded=True,  # This enables recipient/subject inputs
            initial_content=forward_content,
        )
        # Pre-fill recipient and subject
        screen.recipient_email = recipients
        screen.subject = subject

        self.push_screen(screen)

    def _format_forward_content(self, message: "Message") -> str:
        """Format the forwarded message content with headers.

        Args:
            message: The message to format for forwarding.

        Returns:
            Formatted string with forward headers and original message body.
        """
        from .models import Message

        # Format date nicely
        date_str = message.date.strftime("%a, %b %d, %Y at %I:%M %p") if message.date else "Unknown"

        # Build forwarded message header
        lines = [
            "",
            "---------- Forwarded message ---------",
            f"From: {message.sender} <{message.sender_email}>",
            f"Date: {date_str}",
            f"Subject: {message.subject}",
            f"To: {message.recipient}",
            "",
            message.body or "",
        ]

        return "\n".join(lines)
