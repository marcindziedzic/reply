"""Service for downloading and managing shared team resources."""

import io
import json
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError


@dataclass
class ExportResult:
    """Summary of a resources export."""

    output_path: Path
    # Archive path -> where the file came from ("shared" or "local")
    files: dict[str, str] = field(default_factory=dict)
    # Archive paths left out on purpose (e.g. data downloaded at startup)
    skipped: list[str] = field(default_factory=list)

    def count(self, directory: str, source: Optional[str] = None) -> int:
        """Count packed files in a top-level directory, optionally by source."""
        return sum(
            1 for name, src in self.files.items()
            if name.startswith(directory + "/") and (source is None or src == source)
        )


class SharedResourcesService:
    """Service for downloading and extracting shared resources from a URL.

    Downloads a zip file containing context/, queries/, and snippets/ directories
    and extracts them to .shared_resources/ in the project root.
    """

    SHARED_DIR_NAME = ".shared_resources"
    METADATA_FILE = ".metadata.json"
    RESOURCE_DIRS = ("context", "queries", "snippets")
    # Queries have no local override, so only these are read from the project root
    LOCAL_OVERRIDE_DIRS = ("context", "snippets")
    IGNORED_FILE_NAMES = {".ds_store", "thumbs.db", "desktop.ini"}

    def __init__(self, project_root: Optional[Path] = None):
        """Initialize the service.

        Args:
            project_root: Project root directory. If None, finds it by searching for config.yaml.
        """
        self._project_root = project_root or self._find_project_root()

    def _find_project_root(self) -> Path:
        """Find project root by searching for config.yaml."""
        current = Path.cwd()
        for _ in range(10):
            if (current / "config.yaml").exists():
                return current
            parent = current.parent
            if parent == current:
                break
            current = parent
        return Path.cwd()

    @property
    def project_root(self) -> Path:
        """Get the project root directory."""
        return self._project_root

    @property
    def shared_dir(self) -> Path:
        """Get path to .shared_resources directory."""
        return self._project_root / self.SHARED_DIR_NAME

    @property
    def metadata_path(self) -> Path:
        """Get path to metadata file."""
        return self.shared_dir / self.METADATA_FILE

    def get_metadata(self) -> dict:
        """Load metadata about the last download.

        Returns:
            Dict with 'url', 'downloaded_at', 'etag' keys, or empty dict if not found.
        """
        if not self.metadata_path.exists():
            return {}

        try:
            return json.loads(self.metadata_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_metadata(self, url: str, etag: Optional[str] = None) -> None:
        """Save download metadata."""
        metadata = {
            "url": url,
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "etag": etag,
        }
        self.metadata_path.write_text(
            json.dumps(metadata, indent=2),
            encoding="utf-8"
        )

    def download_and_extract(self, url: str, on_progress: Optional[callable] = None) -> bool:
        """Download zip from URL and extract to .shared_resources/.

        Args:
            url: URL to the zip file.
            on_progress: Optional callback for progress updates. Called with (message: str).

        Returns:
            True if successful, False otherwise.

        Raises:
            URLError: If download fails.
            zipfile.BadZipFile: If downloaded file is not a valid zip.
        """
        def log(msg: str) -> None:
            if on_progress:
                on_progress(msg)
            else:
                print(msg)

        log(f"Downloading from {url}...")

        # Download the zip file
        request = Request(url, headers={"User-Agent": "EmailAssistant/1.0"})

        try:
            with urlopen(request, timeout=60) as response:
                etag = response.headers.get("ETag")
                data = response.read()
        except HTTPError as e:
            log(f"HTTP error {e.code}: {e.reason}")
            raise
        except URLError as e:
            log(f"Download failed: {e.reason}")
            raise

        log(f"Downloaded {len(data)} bytes")

        # Validate it's a zip file
        if not zipfile.is_zipfile(io.BytesIO(data)):
            raise zipfile.BadZipFile("Downloaded file is not a valid zip archive")

        # Clear existing shared resources (except metadata)
        if self.shared_dir.exists():
            log("Clearing existing shared resources...")
            for item in self.shared_dir.iterdir():
                if item.name == self.METADATA_FILE:
                    continue
                if item.is_dir():
                    self._rmtree(item)
                else:
                    item.unlink()
        else:
            self.shared_dir.mkdir(parents=True)

        # Extract zip contents
        log("Extracting...")
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            # Check what's in the zip
            names = zf.namelist()

            # Detect if zip has a single root directory
            root_dirs = set()
            for name in names:
                parts = name.split("/")
                if len(parts) > 1:
                    root_dirs.add(parts[0])

            # If all files are in a single root directory, strip it
            strip_prefix = ""
            if len(root_dirs) == 1:
                single_root = list(root_dirs)[0]
                # Check if this is really a container (not context/queries/snippets)
                if single_root not in ("context", "queries", "snippets"):
                    strip_prefix = single_root + "/"

            extracted_count = 0
            for member in zf.infolist():
                # Skip directories
                if member.is_dir():
                    continue

                # Get target path
                name = member.filename
                if strip_prefix and name.startswith(strip_prefix):
                    name = name[len(strip_prefix):]

                if not name:
                    continue

                # Only extract context/, queries/, snippets/
                if not any(name.startswith(d + "/") or name.startswith(d + "\\")
                          for d in ("context", "queries", "snippets")):
                    continue

                target_path = self.shared_dir / name
                target_path.parent.mkdir(parents=True, exist_ok=True)

                with zf.open(member) as src:
                    target_path.write_bytes(src.read())
                extracted_count += 1

        log(f"Extracted {extracted_count} files")

        # Save metadata
        self._save_metadata(url, etag)
        log("Done!")

        return True

    def _rmtree(self, path: Path) -> None:
        """Recursively remove a directory."""
        for item in path.iterdir():
            if item.is_dir():
                self._rmtree(item)
            else:
                item.unlink()
        path.rmdir()

    def _is_ignored(self, path: Path, root: Path) -> bool:
        """Check if a file should stay out of the export (hidden or OS junk)."""
        if path.name.lower() in self.IGNORED_FILE_NAMES:
            return True
        return any(part.startswith(".") for part in path.relative_to(root).parts)

    def export_to_zip(self, output_path: Path, exclude: Iterable[Path] = ()) -> ExportResult:
        """Pack shared resources and local overrides into a zip.

        The archive has context/, queries/ and snippets/ at its root - the same
        layout download_and_extract() reads - so it can be uploaded to the
        shared_resources URL as is. Files in local ./context/ and ./snippets/
        replace the same paths from .shared_resources/.

        Args:
            output_path: Where to write the zip file.
            exclude: Files to leave out (e.g. data downloaded at startup).

        Returns:
            ExportResult describing packed and skipped files.

        Raises:
            FileNotFoundError: If there are no resource files to export.
        """
        output_path = Path(output_path).resolve()
        excluded = {Path(p).resolve() for p in exclude}
        excluded.add(output_path)

        result = ExportResult(output_path=output_path)
        sources: dict[str, Path] = {}

        # Shared first, then local, so local files win on the same archive path
        layers = [(self.shared_dir, "shared"), (self._project_root, "local")]
        for base, label in layers:
            for directory in self.RESOURCE_DIRS:
                if label == "local" and directory not in self.LOCAL_OVERRIDE_DIRS:
                    continue
                root = base / directory
                if not root.is_dir():
                    continue
                for path in sorted(root.rglob("*")):
                    if not path.is_file() or self._is_ignored(path, root):
                        continue
                    arcname = path.relative_to(base).as_posix()
                    if path.resolve() in excluded:
                        if arcname not in result.skipped:
                            result.skipped.append(arcname)
                        continue
                    sources[arcname] = path
                    result.files[arcname] = label

        if not sources:
            raise FileNotFoundError(
                "No resources to export. Run --update-resources first "
                "or add files to context/ or snippets/."
            )

        # Write to a temp file first so a failed export never leaves a broken zip
        output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = output_path.with_name(output_path.name + ".tmp")
        try:
            with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for arcname in sorted(sources):
                    zf.write(sources[arcname], arcname)
            tmp_path.replace(output_path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

        return result

    def has_shared_resources(self) -> bool:
        """Check if shared resources have been downloaded."""
        return self.shared_dir.exists() and any(
            (self.shared_dir / d).exists()
            for d in ("context", "queries", "snippets")
        )

    def get_shared_context_dir(self) -> Optional[Path]:
        """Get path to shared context directory if it exists."""
        path = self.shared_dir / "context"
        return path if path.exists() else None

    def get_shared_queries_dir(self) -> Optional[Path]:
        """Get path to shared queries directory if it exists."""
        path = self.shared_dir / "queries"
        return path if path.exists() else None

    def get_shared_snippets_dir(self) -> Optional[Path]:
        """Get path to shared snippets directory if it exists."""
        path = self.shared_dir / "snippets"
        return path if path.exists() else None


# Global instance
_shared_resources_service: Optional[SharedResourcesService] = None


def get_shared_resources_service() -> SharedResourcesService:
    """Get the global shared resources service instance."""
    global _shared_resources_service
    if _shared_resources_service is None:
        _shared_resources_service = SharedResourcesService()
    return _shared_resources_service
