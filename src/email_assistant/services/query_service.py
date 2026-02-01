"""Query service for loading AI prompt templates from files.

Precedence: Shared resources > Bundled defaults
(No local override - team controls prompts via shared resources)
"""

from pathlib import Path
from typing import Optional


class QueryService:
    """Service for loading and formatting AI query templates.

    Query templates are loaded with the following precedence:
    1. .shared_resources/queries/ - Team shared resources (highest priority)
    2. .resources/queries/ - Bundled defaults

    Local ./queries/ directory is NOT checked - teams control prompts
    via shared resources to ensure consistent AI behavior.
    """

    def __init__(self):
        self._project_root: Optional[Path] = None
        self._cache: dict[str, str] = {}

    def _get_project_root(self) -> Path:
        """Find and cache the project root path."""
        if self._project_root is not None:
            return self._project_root

        # Find project root (where config.yaml is)
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

    def _get_query_path(self, name: str) -> Path:
        """Find query file path with precedence: shared > bundled.

        Args:
            name: Query template name (without .txt extension)

        Returns:
            Path to the query file

        Raises:
            FileNotFoundError: If query not found in any location
        """
        root = self._get_project_root()
        filename = f"{name}.txt"

        # 1. Check shared resources (team override) - highest priority
        shared_path = root / ".shared_resources" / "queries" / filename
        if shared_path.exists():
            return shared_path

        # 2. Check bundled defaults
        bundled_path = root / ".resources" / "queries" / filename
        if bundled_path.exists():
            return bundled_path

        raise FileNotFoundError(
            f"Query template not found: {name}\n"
            f"Searched in:\n"
            f"  - {root / '.shared_resources' / 'queries'}\n"
            f"  - {root / '.resources' / 'queries'}"
        )

    def _load_query(self, name: str) -> str:
        """Load a query template from file."""
        if name in self._cache:
            return self._cache[name]

        query_path = self._get_query_path(name)
        content = query_path.read_text(encoding="utf-8").strip()
        self._cache[name] = content
        return content

    def get_query(self, name: str, **kwargs) -> str:
        """
        Load a query template and format it with provided variables.

        Args:
            name: Query template name (without .txt extension)
            **kwargs: Variables to substitute in the template

        Returns:
            Formatted query string
        """
        template = self._load_query(name)

        if kwargs:
            template = template.format(**kwargs)

        return template

    def clear_cache(self) -> None:
        """Clear the query template cache."""
        self._cache = {}

    def list_queries(self) -> list[str]:
        """List all available query templates.

        Returns:
            List of query names (without .txt extension)
        """
        root = self._get_project_root()
        queries = set()

        # Check bundled first (so we know what's available by default)
        bundled_dir = root / ".resources" / "queries"
        if bundled_dir.exists():
            for f in bundled_dir.glob("*.txt"):
                queries.add(f.stem)

        # Check shared (these override bundled)
        shared_dir = root / ".shared_resources" / "queries"
        if shared_dir.exists():
            for f in shared_dir.glob("*.txt"):
                queries.add(f.stem)

        return sorted(queries)


# Global service instance
_query_service: Optional[QueryService] = None


def get_query_service() -> QueryService:
    """Get the global query service instance."""
    global _query_service
    if _query_service is None:
        _query_service = QueryService()
    return _query_service
