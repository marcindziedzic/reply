"""Context service for loading AI context files with caching support.

Precedence: Local > Shared resources > Bundled defaults
"""

import json
from pathlib import Path
from typing import Optional


class ContextService:
    """Service for loading context files for AI prompts.

    Context files are loaded with the following precedence:
    1. ./context/ - Local overrides (highest priority)
    2. ./.shared_resources/context/ - Team shared resources
    3. ./.resources/context/ - Bundled defaults

    Directory structure:
        context/
            instructions.md     <- Core system instructions (always loaded)
            tone_of_voice.md    <- Writing style (always loaded)
            required/           <- Additional always-loaded files (FAQ, etc.)
            optional/           <- Only loaded when requested (large files)
    """

    CORE_FILES = ["instructions.md", "tone_of_voice.md"]

    def __init__(self):
        self._project_root: Optional[Path] = None
        self._cached_required_context: Optional[str] = None

    def _get_project_root(self) -> Path:
        """Find the project root directory."""
        if self._project_root is not None:
            return self._project_root

        current = Path.cwd()
        for _ in range(10):
            if (current / "config.yaml").exists():
                self._project_root = current
                break
            parent = current.parent
            if parent == current:
                break
            current = parent

        if self._project_root is None:
            self._project_root = Path.cwd()

        return self._project_root

    def _get_context_dirs(self) -> list[Path]:
        """Get all context directories in precedence order (local > shared > bundled)."""
        root = self._get_project_root()
        return [
            root / "context",                      # Local (highest priority)
            root / ".shared_resources" / "context", # Shared resources
            root / ".resources" / "context",       # Bundled defaults
        ]

    def _find_file(self, relative_path: str) -> Optional[Path]:
        """Find a file checking all context directories in precedence order.

        Args:
            relative_path: Path relative to context directory (e.g., "instructions.md")

        Returns:
            Path to the file if found, None otherwise
        """
        for context_dir in self._get_context_dirs():
            filepath = context_dir / relative_path
            if filepath.exists():
                return filepath
        return None

    def _merge_directory_files(self, relative_dir: str, extensions: tuple = ("*.md", "*.json", "*.csv")) -> dict[str, Path]:
        """Merge files from a subdirectory across all context directories.

        Files from higher priority directories override lower priority ones.

        Args:
            relative_dir: Subdirectory name (e.g., "required", "optional")
            extensions: File extensions to include

        Returns:
            Dict mapping filename to Path (with precedence applied)
        """
        files = {}

        # Process in reverse order so higher priority overwrites lower
        for context_dir in reversed(self._get_context_dirs()):
            subdir = context_dir / relative_dir
            if not subdir.exists():
                continue

            for ext in extensions:
                for filepath in subdir.glob(ext):
                    files[filepath.name] = filepath

        return files

    def validate(self) -> list[str]:
        """Check for missing core files. Returns list of missing files."""
        missing = []

        for filename in self.CORE_FILES:
            if self._find_file(filename) is None:
                missing.append(filename)

        return missing

    def list_optional_files(self) -> list[str]:
        """List all optional context files.

        Returns:
            List of filenames (e.g., ['products.json', 'prices.csv'])
        """
        files = self._merge_directory_files("optional")
        return sorted(files.keys())

    def has_optional_context(self) -> bool:
        """Check if there are any optional context files."""
        return len(self.list_optional_files()) > 0

    def _load_file_content(self, filepath: Path) -> str:
        """Load a file and format it as a section.

        Args:
            filepath: Path to the file.

        Returns:
            Formatted section string.
        """
        section_name = filepath.stem.replace("_", " ").upper()
        content = filepath.read_text(encoding="utf-8").strip()

        if filepath.suffix == ".json":
            try:
                data = json.loads(content)
                content = json.dumps(data, ensure_ascii=False, indent=2)
            except json.JSONDecodeError:
                pass

        return f"=== {section_name} ===\n{content}"

    def _load_files_from_merged(self, files: dict[str, Path]) -> list[str]:
        """Load content from a dict of merged files.

        Args:
            files: Dict mapping filename to Path

        Returns:
            List of formatted content sections.
        """
        parts = []

        # Sort by filename for consistent ordering
        for filename in sorted(files.keys()):
            filepath = files[filename]
            try:
                parts.append(self._load_file_content(filepath))
            except (OSError, json.JSONDecodeError):
                # Skip files that can't be read
                pass

        return parts

    def get_context(self, optional_files: list[str] | None = None) -> str:
        """
        Load and concatenate context files.

        Args:
            optional_files: List of filenames from optional/ to include.

        Returns:
            Combined context string for system prompt.
        """
        # Load required context (cached)
        if self._cached_required_context is None:
            required_parts = []

            # 1. Load core files in specific order
            for filename in self.CORE_FILES:
                filepath = self._find_file(filename)
                if filepath:
                    section_name = filename.replace(".md", "").replace("_", " ").upper()
                    content = filepath.read_text(encoding="utf-8").strip()
                    required_parts.append(f"=== {section_name} ===\n{content}")

            # 2. Load files from required/ subdirectory (merged from all sources)
            required_files = self._merge_directory_files("required")
            required_parts.extend(self._load_files_from_merged(required_files))

            self._cached_required_context = "\n\n".join(required_parts)

        # Load selected optional files (not cached - selection varies)
        if optional_files:
            optional_available = self._merge_directory_files("optional")
            optional_parts = []

            for filename in optional_files:
                if filename in optional_available:
                    try:
                        optional_parts.append(
                            self._load_file_content(optional_available[filename])
                        )
                    except (OSError, json.JSONDecodeError):
                        pass

            if optional_parts:
                return self._cached_required_context + "\n\n" + "\n\n".join(optional_parts)

        return self._cached_required_context or ""

    def clear_cache(self) -> None:
        """Clear cached context (call after file changes)."""
        self._cached_required_context = None


# Global instance
_context_service: Optional[ContextService] = None


def get_context_service() -> ContextService:
    """Get the global context service instance."""
    global _context_service
    if _context_service is None:
        _context_service = ContextService()
    return _context_service
