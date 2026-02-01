"""Loading screen with progress bar for application initialization."""

from textual import work
from textual.app import ComposeResult
from textual.containers import Center, Middle, Vertical
from textual.screen import Screen
from textual.widgets import Label, ProgressBar, Static

from ..config import get_config
from ..services.download_service import get_download_service


class LoadingScreen(Screen):
    """Splash screen with progress bar shown during initialization."""

    CSS = """
    LoadingScreen {
        background: $surface;
    }

    #loading-container {
        width: 60;
        height: auto;
        padding: 2 4;
        border: thick $primary;
        background: $surface;
    }

    #app-title {
        text-align: center;
        text-style: bold;
        color: $text;
        margin-bottom: 1;
    }

    #app-subtitle {
        text-align: center;
        color: $text-muted;
        margin-bottom: 2;
    }

    #progress-bar {
        width: 100%;
        margin: 1 0;
    }

    #status-label {
        text-align: center;
        color: $text-muted;
        margin-top: 1;
    }

    #step-label {
        text-align: center;
        color: $primary;
        text-style: italic;
        margin-top: 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._download_service = get_download_service()
        self._has_downloads = self._download_service.has_downloads()
        self.total_steps = 7 if self._has_downloads else 6
        self.current_step = 0
        self._download_errors: list[str] = []

    def compose(self) -> ComposeResult:
        """Compose the loading screen."""
        with Middle():
            with Center():
                with Vertical(id="loading-container"):
                    yield Static("Email Assistant", id="app-title")
                    yield Static("v0.1", id="app-subtitle")
                    yield ProgressBar(total=self.total_steps, show_eta=False, id="progress-bar")
                    yield Label("Initializing...", id="status-label")
                    yield Label("", id="step-label")

    def on_mount(self) -> None:
        """Start initialization when screen is mounted."""
        self._run_initialization()

    def _update_progress(self, step: int, status: str, detail: str = "") -> None:
        """Update the progress bar and labels."""
        self.current_step = step
        progress_bar = self.query_one("#progress-bar", ProgressBar)
        status_label = self.query_one("#status-label", Label)
        step_label = self.query_one("#step-label", Label)

        progress_bar.update(progress=step)
        status_label.update(status)
        step_label.update(detail)
        self.refresh()  # Force UI repaint

    @work(exclusive=True)
    async def _run_initialization(self) -> None:
        """Run all initialization steps with progress updates."""
        import asyncio
        from pathlib import Path

        # Give UI time to render before starting heavy work
        await asyncio.sleep(0.05)

        # Track current step (offset by 1 if downloads are enabled)
        step_offset = 1 if self._has_downloads else 0

        try:
            # Step 1 (optional): Download files
            if self._has_downloads:
                self._update_progress(1, "Downloading files...", "")
                await asyncio.sleep(0.05)  # Let UI update

                items = self._download_service.get_items()
                for i, item in enumerate(items):
                    filename = Path(item.target).name
                    self._update_progress(
                        1,
                        "Downloading files...",
                        f"({i + 1}/{len(items)}) {filename}"
                    )
                    result = await self._download_service.download_file(item)
                    if not result.success and not result.skipped:
                        self._download_errors.append(
                            f"Download error: {filename}: {result.error}"
                        )

            # Step 2 (or 1): Connect to Gmail API
            self._update_progress(1 + step_offset, "Connecting to Gmail API...", "Loading libraries")
            await asyncio.sleep(0.05)  # Let UI update

            from ..gmail import get_gmail_client
            gmail = get_gmail_client()

            # Step 3 (or 2): Get user profile
            self._update_progress(2 + step_offset, "Fetching profile...", "Signing in")
            await asyncio.sleep(0.05)  # Let UI update
            user_email = gmail.get_user_email()
            self.app.title = f"Email Assistant v0.1 - {user_email}"

            # Step 4 (or 3): Initialize reminder labels
            self._update_progress(3 + step_offset, "Initializing reminders...", "Creating labels")
            await asyncio.sleep(0.05)  # Let UI update
            from ..services.reminder_service import get_reminder_service
            service = get_reminder_service()
            service.ensure_base_labels_exist()

            # Step 5 (or 4): Cleanup old reminders (once per day)
            moved_count = 0
            if service.should_run_cleanup():
                self._update_progress(4 + step_offset, "Cleaning up...", "Archiving old reminders")
                await asyncio.sleep(0.05)  # Let UI update
                moved_count = service.cleanup_old_labels()

            # Step 6 (or 5): Check for replied reminders
            self._update_progress(5 + step_offset, "Checking replies...", "Removing outdated reminders")
            await asyncio.sleep(0.05)  # Let UI update
            removed_count = service.check_and_remove_replied_reminders()

            # Step 7 (or 6): Load threads
            self._update_progress(6 + step_offset, "Loading threads...", "Fetching unread messages")
            await asyncio.sleep(0.05)  # Let UI update
            threads = gmail.get_unread_threads()

            # Done - switch to main screen
            self._update_progress(self.total_steps, "Done!", "")

            # Small delay to show "Gotowe!" before switching
            await asyncio.sleep(0.3)

            # Pass data to main screen and switch
            from .clients import ClientsScreen
            main_screen = ClientsScreen()
            main_screen.threads = threads
            main_screen.user_email = user_email
            main_screen._threads_preloaded = True

            # Store notification data
            notifications = []
            if moved_count > 0:
                notifications.append(f"Marked {moved_count} reminders as overdue")
            if removed_count > 0:
                notifications.append(f"Removed {removed_count} reminders (client replied)")

            # Add download errors (max 3)
            for error in self._download_errors[:3]:
                notifications.append(error)

            # Switch screen and show notifications
            self.app.switch_screen(main_screen)

            for msg in notifications:
                self.app.notify(msg)

        except Exception as e:
            self._update_progress(self.current_step, f"Error: {e}", "")
            # Wait a bit then try to continue anyway
            await asyncio.sleep(2)

            from .clients import ClientsScreen
            self.app.switch_screen(ClientsScreen())
