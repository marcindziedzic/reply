"""Configuration management for Email Assistant."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml


@dataclass
class DownloadItem:
    """Configuration for a single file to download."""

    url: str
    target: str
    overwrite: bool = True


@dataclass
class DownloadsConfig:
    """Configuration for file downloads during startup."""

    items: list[DownloadItem] = field(default_factory=list)

    def has_downloads(self) -> bool:
        """Check if there are any files to download."""
        return len(self.items) > 0


@dataclass
class SharedResourcesConfig:
    """Configuration for shared team resources.

    Teams can publish a zip file containing context/, queries/, and snippets/
    directories. Users download this via 'python run.py --update-resources'.
    """

    url: str = ""

    def is_configured(self) -> bool:
        """Check if shared resources URL is configured."""
        return bool(self.url)


@dataclass
class ToolDefinition:
    """Configuration for a single tool that Claude can use."""

    name: str
    description: str
    input_schema: dict[str, Any]
    type: str = "http"  # http, custom
    # HTTP-specific settings
    endpoint: str = ""
    method: str = "GET"  # GET, POST, PUT, PATCH, DELETE
    headers: dict[str, str] = field(default_factory=dict)
    query_params: dict[str, str] = field(default_factory=dict)
    body_template: dict[str, Any] = field(default_factory=dict)
    # Use input field as request body (for dynamic JSON from Claude)
    body_from_input: str = ""
    response_template: str = ""
    # JSONPath-like extraction from response (e.g., "$.data[0].name", "$.items[*].id")
    response_extract: str = ""
    # Timeout for this specific tool (overrides global)
    timeout: Optional[int] = None

    def to_claude_tool(self) -> dict[str, Any]:
        """Convert to Claude API tool format."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


@dataclass
class ToolsConfig:
    """Configuration for Claude tool use."""

    enabled: bool = True
    timeout: int = 30
    max_tool_calls: int = 5
    tools: list[ToolDefinition] = field(default_factory=list)
    allow_in_methods: list[str] = field(default_factory=lambda: [
        "generate_response",
        "ask_question",
    ])

    def has_tools(self) -> bool:
        """Check if there are any tools configured."""
        return self.enabled and len(self.tools) > 0

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """Get tool definition by name."""
        for tool in self.tools:
            if tool.name == name:
                return tool
        return None

    def get_claude_tools(self) -> list[dict[str, Any]]:
        """Get all tools in Claude API format."""
        if not self.enabled:
            return []
        return [tool.to_claude_tool() for tool in self.tools]


@dataclass
class UserSettings:
    """User personal information for snippet placeholders.

    Variables are stored as a dynamic dict, allowing any user-defined keys.
    Each key becomes a placeholder like [Key] in snippets.
    """

    variables: dict[str, str] = field(default_factory=dict)

    def get_placeholders(self) -> dict[str, str]:
        """Get placeholder mapping for snippet replacement.

        Converts each variable key to [key] format.
        E.g., {"name": "Marcin"} -> {"[name]": "Marcin"}
        """
        return {
            f"[{key}]": value
            for key, value in self.variables.items()
        }

    def get(self, key: str, default: str = "") -> str:
        """Get a variable value by key."""
        return self.variables.get(key, default)


@dataclass
class ClaudeConfig:
    """Claude API configuration."""

    api_key: str = ""
    project_id: str = ""
    model: str = "claude-sonnet-4-20250514"


@dataclass
class ForwardingAddress:
    """Configuration for a forwarding address."""

    address: str
    default_subject: str = ""


@dataclass
class GmailConfig:
    """Gmail API configuration."""

    credentials_file: str = "credentials.json"
    token_file: str = "token.json"
    max_threads: int = 50
    forwarding_addresses: dict[str, ForwardingAddress] = None  # Addresses that forward emails

    def __post_init__(self):
        if self.forwarding_addresses is None:
            self.forwarding_addresses = {}

    def is_forwarding_address(self, email: str) -> bool:
        """Check if email is a forwarding address."""
        return email.lower() in self.forwarding_addresses

    def get_forwarding_config(self, email: str) -> Optional[ForwardingAddress]:
        """Get forwarding config for an address."""
        return self.forwarding_addresses.get(email.lower())


@dataclass
class Config:
    """Main configuration container."""

    claude: ClaudeConfig = field(default_factory=ClaudeConfig)
    gmail: GmailConfig = field(default_factory=GmailConfig)
    user: UserSettings = field(default_factory=UserSettings)
    downloads: DownloadsConfig = field(default_factory=DownloadsConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    shared_resources: SharedResourcesConfig = field(default_factory=SharedResourcesConfig)

    @classmethod
    def _parse_downloads(cls, data: list) -> DownloadsConfig:
        """Parse downloads configuration from config data."""
        items = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and "url" in item and "target" in item:
                    items.append(DownloadItem(
                        url=item["url"],
                        target=item["target"],
                        overwrite=item.get("overwrite", True),
                    ))
        return DownloadsConfig(items=items)

    @classmethod
    def _parse_tools(cls, data: dict) -> ToolsConfig:
        """Parse tools configuration from config data."""
        if not isinstance(data, dict):
            return ToolsConfig()

        tools_list = []
        for tool_data in data.get("tools", []):
            if not isinstance(tool_data, dict):
                continue
            # Require name, description, and input_schema
            if not all(k in tool_data for k in ("name", "description", "input_schema")):
                continue

            tools_list.append(ToolDefinition(
                name=tool_data["name"],
                description=tool_data["description"],
                input_schema=tool_data["input_schema"],
                type=tool_data.get("type", "http"),
                endpoint=tool_data.get("endpoint", ""),
                method=tool_data.get("method", "GET"),
                headers=tool_data.get("headers", {}),
                query_params=tool_data.get("query_params", {}),
                body_template=tool_data.get("body_template", {}),
                body_from_input=tool_data.get("body_from_input", ""),
                response_template=tool_data.get("response_template", ""),
                response_extract=tool_data.get("response_extract", ""),
                timeout=tool_data.get("timeout"),
            ))

        return ToolsConfig(
            enabled=data.get("enabled", True),
            timeout=data.get("timeout", 30),
            max_tool_calls=data.get("max_tool_calls", 5),
            tools=tools_list,
            allow_in_methods=data.get("allow_in_methods", [
                "generate_response",
                "ask_question",
            ]),
        )

    @classmethod
    def _parse_forwarding_addresses(cls, data: dict) -> dict[str, ForwardingAddress]:
        """Parse forwarding addresses from config data."""
        result = {}
        if isinstance(data, dict):
            for addr, config in data.items():
                addr_lower = addr.lower()
                if isinstance(config, dict):
                    result[addr_lower] = ForwardingAddress(
                        address=addr_lower,
                        default_subject=config.get("default_subject", ""),
                    )
                else:
                    # Simple format without config
                    result[addr_lower] = ForwardingAddress(address=addr_lower)
        elif isinstance(data, list):
            # Backwards compatibility with old list format
            for addr in data:
                addr_lower = addr.lower()
                result[addr_lower] = ForwardingAddress(address=addr_lower)
        return result

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Config":
        """Load configuration from YAML file."""
        if path is None:
            path = get_config_path()

        if not path.exists():
            return cls()

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        claude_data = data.get("claude", {})
        gmail_data = data.get("gmail", {})
        user_data = data.get("user", {})
        downloads_data = data.get("downloads", [])
        tools_data = data.get("tools", {})
        shared_resources_data = data.get("shared_resources", {})

        return cls(
            claude=ClaudeConfig(
                api_key=claude_data.get("api_key", ""),
                project_id=claude_data.get("project_id", ""),
                model=claude_data.get("model", "claude-sonnet-4-20250514"),
            ),
            gmail=GmailConfig(
                credentials_file=gmail_data.get("credentials_file", "credentials.json"),
                token_file=gmail_data.get("token_file", "token.json"),
                max_threads=gmail_data.get("max_threads", 50),
                forwarding_addresses=cls._parse_forwarding_addresses(
                    gmail_data.get("forwarding_addresses", {})
                ),
            ),
            user=UserSettings(
                variables={k: str(v) for k, v in user_data.items() if v}
            ),
            downloads=cls._parse_downloads(downloads_data),
            tools=cls._parse_tools(tools_data),
            shared_resources=SharedResourcesConfig(
                url=shared_resources_data.get("url", "") if isinstance(shared_resources_data, dict) else "",
            ),
        )

    def save(self, path: Optional[Path] = None) -> None:
        """Save configuration to YAML file."""
        if path is None:
            path = get_config_path()

        data = {
            "claude": {
                "api_key": self.claude.api_key,
                "project_id": self.claude.project_id,
                "model": self.claude.model,
            },
            "gmail": {
                "credentials_file": self.gmail.credentials_file,
                "token_file": self.gmail.token_file,
                "max_threads": self.gmail.max_threads,
                "forwarding_addresses": {
                    addr: {"default_subject": cfg.default_subject}
                    for addr, cfg in self.gmail.forwarding_addresses.items()
                },
            },
            "user": self.user.variables,
        }

        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

    def is_valid(self) -> bool:
        """Check if configuration is complete and valid."""
        return bool(self.claude.api_key and self.claude.project_id)

    def get_credentials_path(self) -> Path:
        """Get absolute path to credentials file."""
        cred_path = Path(self.gmail.credentials_file)
        if cred_path.is_absolute():
            return cred_path
        return get_config_dir() / cred_path

    def get_token_path(self) -> Path:
        """Get absolute path to token file."""
        token_path = Path(self.gmail.token_file)
        if token_path.is_absolute():
            return token_path
        return get_config_dir() / token_path


def get_config_dir() -> Path:
    """Get the configuration directory path."""
    # Use the current working directory for config files
    return Path.cwd()


def get_config_path() -> Path:
    """Get the configuration file path."""
    return get_config_dir() / "config.yaml"


def config_exists() -> bool:
    """Check if configuration file exists."""
    return get_config_path().exists()


# Global config instance
_config: Optional[Config] = None


def get_config() -> Config:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = Config.load()
    return _config


def reload_config() -> Config:
    """Reload the configuration from disk."""
    global _config
    _config = Config.load()
    return _config
