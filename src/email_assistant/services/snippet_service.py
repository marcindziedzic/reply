"""Snippet service for managing reusable text snippets.

Precedence: (Local + Shared) or Bundled
- If any snippets exist in ./snippets/ or .shared_resources/snippets/, merge those (local wins conflicts)
- Otherwise use .resources/snippets/ bundled samples
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class Snippet:
    """Represents a text snippet."""

    title: str
    content: str
    category: str
    file_path: Path
    relative_path: str  # e.g., "oferty/gwarancja.md"


class SnippetService:
    """Service for managing snippets.

    Snippets are loaded with special precedence:
    - If ANY snippets exist in ./snippets/ or .shared_resources/snippets/,
      those are merged (local wins on conflicts) and bundled samples are ignored
    - If NO custom snippets exist, bundled samples from .resources/snippets/ are used

    This ensures bundled samples don't clutter the list once real snippets are added.
    """

    def __init__(self, project_root: Optional[Path] = None):
        """Initialize the snippet service.

        Args:
            project_root: Project root directory. If None, finds it by searching for config.yaml.
        """
        self._project_root = project_root or self._find_project_root()
        self._snippets: list[Snippet] = []
        self._last_mtime: float = 0.0

    def _find_project_root(self) -> Path:
        """Find project root by searching for config.yaml."""
        current = Path(__file__).parent
        while current != current.parent:
            if (current / "config.yaml").exists():
                return current
            current = current.parent
        return Path.cwd()

    @property
    def snippets_dir(self) -> Path:
        """Get the local snippets directory path."""
        return self._project_root / "snippets"

    @property
    def shared_snippets_dir(self) -> Path:
        """Get the shared snippets directory path."""
        return self._project_root / ".shared_resources" / "snippets"

    @property
    def bundled_snippets_dir(self) -> Path:
        """Get the bundled snippets directory path."""
        return self._project_root / ".resources" / "snippets"

    def _get_dir_mtime(self, directory: Path) -> float:
        """Get the most recent modification time of any .md file in directory."""
        if not directory.exists():
            return 0.0

        max_mtime = 0.0
        for root, _dirs, files in os.walk(directory):
            for filename in files:
                if filename.endswith(".md"):
                    filepath = Path(root) / filename
                    try:
                        mtime = filepath.stat().st_mtime
                        max_mtime = max(max_mtime, mtime)
                    except OSError:
                        pass
        return max_mtime

    def _get_all_mtime(self) -> float:
        """Get the most recent modification time across all snippet directories."""
        return max(
            self._get_dir_mtime(self.snippets_dir),
            self._get_dir_mtime(self.shared_snippets_dir),
            self._get_dir_mtime(self.bundled_snippets_dir),
        )

    def _should_reload(self) -> bool:
        """Check if snippets should be reloaded (files changed)."""
        current_mtime = self._get_all_mtime()
        return current_mtime > self._last_mtime

    def _has_custom_snippets(self) -> bool:
        """Check if any custom snippets exist in local or shared directories."""
        for directory in [self.snippets_dir, self.shared_snippets_dir]:
            if not directory.exists():
                continue
            for root, _dirs, files in os.walk(directory):
                for filename in files:
                    if filename.endswith(".md") and filename.lower() not in ("readme.md", "compose.md"):
                        return True
        return False

    def _parse_snippet_file(self, file_path: Path, base_dir: Path) -> Optional[Snippet]:
        """Parse a snippet file and return a Snippet object.

        Args:
            file_path: Path to the .md file.
            base_dir: Base directory for calculating relative path.

        Returns:
            Snippet object or None if file is empty/invalid.
        """
        try:
            text = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

        text = text.strip()
        if not text:
            return None

        lines = text.split("\n")
        if not lines:
            return None

        # First line is the title
        title_line = lines[0].strip()
        # Remove leading '#' and spaces
        if title_line.startswith("#"):
            title = title_line.lstrip("#").strip()
        else:
            title = title_line

        # If no title found, use filename
        if not title:
            title = file_path.stem

        # Content is everything after the first line
        if len(lines) > 1:
            # Skip empty lines after title
            content_lines = lines[1:]
            while content_lines and not content_lines[0].strip():
                content_lines = content_lines[1:]
            content = "\n".join(content_lines)
        else:
            content = ""

        # Skip if no content
        if not content.strip():
            return None

        # Get relative path and category
        try:
            relative = file_path.relative_to(base_dir)
            relative_path = str(relative).replace("\\", "/")
        except ValueError:
            relative_path = file_path.name

        # Category is the parent directory name(s)
        if relative.parent != Path("."):
            category = str(relative.parent).replace("\\", "/")
        else:
            category = ""

        return Snippet(
            title=title,
            content=content,
            category=category,
            file_path=file_path,
            relative_path=relative_path,
        )

    def _load_snippets_from_dir(self, directory: Path) -> dict[str, Snippet]:
        """Load all snippets from a directory.

        Args:
            directory: Directory to scan for snippets.

        Returns:
            Dict mapping relative_path to Snippet.
        """
        snippets = {}

        if not directory.exists():
            return snippets

        for root, _dirs, files in os.walk(directory):
            root_path = Path(root)
            for filename in files:
                if not filename.endswith(".md"):
                    continue
                # Skip README.md and Compose.md
                if filename.lower() in ("readme.md", "compose.md"):
                    continue

                file_path = root_path / filename
                snippet = self._parse_snippet_file(file_path, directory)
                if snippet:
                    snippets[snippet.relative_path] = snippet

        return snippets

    def load_snippets(self, force: bool = False) -> list[Snippet]:
        """Load snippets from the appropriate directories.

        Precedence:
        - If custom snippets exist (local or shared): merge local + shared (local wins)
        - Otherwise: use bundled samples

        Args:
            force: If True, reload even if files haven't changed.

        Returns:
            List of Snippet objects.
        """
        if not force and not self._should_reload() and self._snippets:
            return self._snippets

        # Check if we have any custom snippets
        if self._has_custom_snippets():
            # Load shared first (lower priority)
            merged_snippets = self._load_snippets_from_dir(self.shared_snippets_dir)

            # Load local (higher priority - overwrites shared)
            local_snippets = self._load_snippets_from_dir(self.snippets_dir)
            merged_snippets.update(local_snippets)

            self._snippets = list(merged_snippets.values())
        else:
            # No custom snippets - use bundled samples
            bundled = self._load_snippets_from_dir(self.bundled_snippets_dir)
            self._snippets = list(bundled.values())

        # Sort by category, then by title
        self._snippets.sort(key=lambda s: (s.category.lower(), s.title.lower()))

        self._last_mtime = self._get_all_mtime()
        return self._snippets

    def get_snippets(self) -> list[Snippet]:
        """Get all snippets (loading if needed).

        Returns:
            List of Snippet objects.
        """
        return self.load_snippets()

    def get_categories(self) -> list[str]:
        """Get all unique categories.

        Returns:
            List of category names, sorted alphabetically.
        """
        snippets = self.get_snippets()
        categories = sorted(set(s.category for s in snippets if s.category))
        return categories

    def get_snippets_by_category(self) -> dict[str, list[Snippet]]:
        """Get snippets grouped by category.

        Returns:
            Dictionary mapping category names to lists of snippets.
            Empty category ("") contains uncategorized snippets.
        """
        snippets = self.get_snippets()
        by_category: dict[str, list[Snippet]] = {}

        for snippet in snippets:
            category = snippet.category or ""
            if category not in by_category:
                by_category[category] = []
            by_category[category].append(snippet)

        return by_category

    def search_snippets(self, query: str) -> list[Snippet]:
        """Search snippets by title, category, or filename.

        Args:
            query: Search query (case-insensitive).

        Returns:
            List of matching Snippet objects.
        """
        if not query:
            return self.get_snippets()

        query_lower = query.lower()
        snippets = self.get_snippets()

        results = []
        for snippet in snippets:
            # Search in title, category, and filename
            if (
                query_lower in snippet.title.lower()
                or query_lower in snippet.category.lower()
                or query_lower in snippet.file_path.stem.lower()
            ):
                results.append(snippet)

        return results

    def refresh(self) -> list[Snippet]:
        """Force refresh snippets from disk.

        Returns:
            List of Snippet objects.
        """
        return self.load_snippets(force=True)

    def get_compose_content(self) -> str:
        """Load content from Compose.md snippet.

        Checks local, shared, then bundled directories.

        Returns:
            Content of Compose.md (without header), or empty string if not found.
        """
        for directory in [self.snippets_dir, self.shared_snippets_dir, self.bundled_snippets_dir]:
            # Try common case variations (filesystem may be case-sensitive)
            compose_path = None
            for filename in ["COMPOSE.md", "Compose.md", "compose.md"]:
                candidate = directory / filename
                if candidate.exists():
                    compose_path = candidate
                    break
            if compose_path is None:
                continue

            try:
                text = compose_path.read_text(encoding="utf-8").strip()
                lines = text.split("\n")
                if not lines:
                    continue

                # Skip header line if present
                if lines[0].strip().startswith("#"):
                    lines = lines[1:]

                # Skip empty lines at start
                while lines and not lines[0].strip():
                    lines = lines[1:]

                return "\n".join(lines)
            except (OSError, UnicodeDecodeError):
                continue

        return ""


# Global service instance
_snippet_service: Optional[SnippetService] = None


def get_snippet_service() -> SnippetService:
    """Get the global snippet service instance."""
    global _snippet_service
    if _snippet_service is None:
        _snippet_service = SnippetService()
    return _snippet_service
