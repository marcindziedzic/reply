"""Main Textual application for Email Assistant."""

from typing import TYPE_CHECKING, Optional

from textual.app import App

# Only LoadingScreen is imported eagerly - it's lightweight
from .screens.loading import LoadingScreen

# Heavy imports are deferred to avoid slow startup
if TYPE_CHECKING:
    from .models import Thread
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
