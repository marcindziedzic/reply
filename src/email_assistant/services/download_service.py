"""Download service for fetching files during application startup."""

import asyncio
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError

from ..config import DownloadItem, get_config


@dataclass
class DownloadResult:
    """Result of a single file download."""

    item: DownloadItem
    success: bool
    error: Optional[str] = None
    skipped: bool = False


class DownloadService:
    """Service for downloading files during startup."""

    TIMEOUT = 30  # seconds
    USER_AGENT = "EmailAssistant/1.0"

    def __init__(self):
        """Initialize the download service."""
        self._config = get_config()

    def has_downloads(self) -> bool:
        """Check if there are any files to download."""
        return self._config.downloads.has_downloads()

    def get_items(self) -> list[DownloadItem]:
        """Get list of items to download."""
        return self._config.downloads.items

    def _get_target_path(self, item: DownloadItem) -> Path:
        """Get absolute target path for a download item."""
        target_path = Path(item.target)
        if target_path.is_absolute():
            return target_path
        return Path.cwd() / target_path

    def _download_file_sync(self, item: DownloadItem) -> DownloadResult:
        """Synchronously download a single file.

        Args:
            item: Download item configuration.

        Returns:
            DownloadResult with success/failure status.
        """
        target_path = self._get_target_path(item)

        # Check if file exists and overwrite is disabled
        if not item.overwrite and target_path.exists():
            return DownloadResult(item=item, success=True, skipped=True)

        try:
            # Create parent directory if needed
            target_path.parent.mkdir(parents=True, exist_ok=True)

            # Build request with headers
            request = urllib.request.Request(
                item.url,
                headers={"User-Agent": self.USER_AGENT}
            )

            # Download file
            with urllib.request.urlopen(request, timeout=self.TIMEOUT) as response:
                content = response.read()

            # Write to file
            target_path.write_bytes(content)

            return DownloadResult(item=item, success=True)

        except HTTPError as e:
            return DownloadResult(
                item=item,
                success=False,
                error=f"HTTP {e.code}"
            )
        except URLError as e:
            return DownloadResult(
                item=item,
                success=False,
                error=str(e.reason)
            )
        except TimeoutError:
            return DownloadResult(
                item=item,
                success=False,
                error="Timeout"
            )
        except OSError as e:
            return DownloadResult(
                item=item,
                success=False,
                error=f"Zapis: {e}"
            )
        except Exception as e:
            return DownloadResult(
                item=item,
                success=False,
                error=str(e)
            )

    async def download_file(self, item: DownloadItem) -> DownloadResult:
        """Asynchronously download a single file.

        Args:
            item: Download item configuration.

        Returns:
            DownloadResult with success/failure status.
        """
        return await asyncio.to_thread(self._download_file_sync, item)

    async def download_all(
        self,
        progress_callback: Optional[callable] = None
    ) -> list[DownloadResult]:
        """Download all configured files.

        Args:
            progress_callback: Optional callback(current, total, filename) for progress updates.

        Returns:
            List of DownloadResult for each item.
        """
        items = self.get_items()
        results = []

        for i, item in enumerate(items):
            if progress_callback:
                filename = Path(item.target).name
                progress_callback(i + 1, len(items), filename)

            result = await self.download_file(item)
            results.append(result)

        return results


# Global service instance
_download_service: Optional[DownloadService] = None


def get_download_service() -> DownloadService:
    """Get the global download service instance."""
    global _download_service
    if _download_service is None:
        _download_service = DownloadService()
    return _download_service
