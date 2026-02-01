"""Tool service for executing external API calls via Claude's tool_use."""

import asyncio
import json
import os
import re
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional, Union
from urllib.error import HTTPError, URLError

from ..config import ToolDefinition, ToolsConfig, get_config


def extract_jsonpath(data: Any, path: str) -> Any:
    """Extract data using a simple JSONPath-like syntax.

    Supported patterns:
    - $.field - top-level field
    - $.field.subfield - nested fields
    - $.array[0] - array index
    - $.array[*].field - extract field from all array items
    - $.field1.array[*].field2 - chained extraction

    Args:
        data: The JSON data (dict or list)
        path: JSONPath expression starting with $

    Returns:
        Extracted value, list of values for [*], or None if not found
    """
    if not path.startswith("$"):
        return None

    # Remove leading $. or $
    path = path[1:]
    if path.startswith("."):
        path = path[1:]

    if not path:
        return data

    current = data
    segments = _parse_path_segments(path)

    for segment in segments:
        if current is None:
            return None

        if segment == "*":
            # Wildcard - current must be a list, apply remaining path to each
            if not isinstance(current, list):
                return None
            # This case is handled within _parse_path_segments via [*]
            continue

        if isinstance(segment, int):
            # Array index
            if isinstance(current, list) and 0 <= segment < len(current):
                current = current[segment]
            else:
                return None

        elif isinstance(segment, tuple) and segment[0] == "*":
            # Wildcard array access [*], optionally with remaining field
            if not isinstance(current, list):
                return None
            remaining_field = segment[1] if len(segment) > 1 else None
            if remaining_field:
                current = [
                    item.get(remaining_field) if isinstance(item, dict) else None
                    for item in current
                ]
            else:
                # Just [*] without field - return the list as-is
                pass

        elif isinstance(segment, str):
            # Field access
            if isinstance(current, dict):
                current = current.get(segment)
            else:
                return None

    return current


def _parse_path_segments(path: str) -> list[Union[str, int, tuple]]:
    """Parse a JSONPath into segments.

    Returns list of:
    - str: field name
    - int: array index
    - tuple: ("*",) or ("*", "field") for wildcard array access
    """
    segments = []
    i = 0
    current_field = ""

    while i < len(path):
        char = path[i]

        if char == ".":
            if current_field:
                segments.append(current_field)
                current_field = ""
            i += 1

        elif char == "[":
            if current_field:
                segments.append(current_field)
                current_field = ""

            # Find closing bracket
            end = path.find("]", i)
            if end == -1:
                break

            bracket_content = path[i + 1:end]

            if bracket_content == "*":
                # Check if there's a .field after ]
                remaining = path[end + 1:]
                if remaining.startswith("."):
                    # Find the next field
                    next_dot = remaining.find(".", 1)
                    next_bracket = remaining.find("[", 1)

                    if next_dot == -1 and next_bracket == -1:
                        # Rest is the field name
                        field = remaining[1:]
                        segments.append(("*", field))
                        break
                    elif next_bracket != -1 and (next_dot == -1 or next_bracket < next_dot):
                        field = remaining[1:next_bracket]
                        segments.append(("*", field))
                        i = end + 1 + next_bracket
                        continue
                    else:
                        field = remaining[1:next_dot] if next_dot != -1 else remaining[1:]
                        segments.append(("*", field))
                        i = end + 1 + (next_dot if next_dot != -1 else len(remaining))
                        continue
                else:
                    segments.append(("*",))
            else:
                # Numeric index
                try:
                    segments.append(int(bracket_content))
                except ValueError:
                    # Treat as field name (for ["field"] syntax)
                    segments.append(bracket_content.strip("'\""))

            i = end + 1

        else:
            current_field += char
            i += 1

    if current_field:
        segments.append(current_field)

    return segments


@dataclass
class ToolResult:
    """Result of a tool execution."""

    tool_use_id: str
    tool_name: str
    success: bool
    result: Any = None
    error: Optional[str] = None

    def to_tool_result_block(self) -> dict[str, Any]:
        """Convert to Claude API tool_result format."""
        if self.success:
            content = self.result if isinstance(self.result, str) else json.dumps(
                self.result, ensure_ascii=False, indent=2
            )
        else:
            content = f"Error: {self.error}"

        return {
            "type": "tool_result",
            "tool_use_id": self.tool_use_id,
            "content": content,
        }


class ToolService:
    """Service for executing tools called by Claude."""

    def __init__(self):
        """Initialize the tool service."""
        self._config = get_config()

    @property
    def tools_config(self) -> ToolsConfig:
        """Get tools configuration."""
        return self._config.tools

    def has_tools(self) -> bool:
        """Check if tools are configured and enabled."""
        return self.tools_config.has_tools()

    def get_claude_tools(self) -> list[dict[str, Any]]:
        """Get tools in Claude API format."""
        return self.tools_config.get_claude_tools()

    def is_method_allowed(self, method_name: str) -> bool:
        """Check if tool use is allowed for a given method."""
        return method_name in self.tools_config.allow_in_methods

    def _interpolate_string(self, template: str, inputs: dict[str, Any]) -> str:
        """Replace {key} placeholders with values from inputs."""
        result = template
        # Replace {key} patterns
        for key, value in inputs.items():
            result = result.replace(f"{{{key}}}", str(value))
        # Replace ${ENV_VAR} patterns with environment variables
        env_pattern = re.compile(r'\$\{([A-Z_][A-Z0-9_]*)\}')
        for match in env_pattern.finditer(result):
            env_var = match.group(1)
            env_value = os.environ.get(env_var, "")
            result = result.replace(match.group(0), env_value)
        return result

    def _interpolate_dict(self, template: dict, inputs: dict[str, Any]) -> dict:
        """Recursively interpolate a dict template."""
        result = {}
        for key, value in template.items():
            if isinstance(value, str):
                result[key] = self._interpolate_string(value, inputs)
            elif isinstance(value, dict):
                result[key] = self._interpolate_dict(value, inputs)
            elif isinstance(value, list):
                result[key] = [
                    self._interpolate_string(v, inputs) if isinstance(v, str) else v
                    for v in value
                ]
            else:
                result[key] = value
        return result

    def _execute_http_tool_sync(
        self,
        tool: ToolDefinition,
        inputs: dict[str, Any],
    ) -> tuple[bool, Any]:
        """Synchronously execute an HTTP tool.

        Returns:
            Tuple of (success, result_or_error)
        """
        timeout = tool.timeout or self.tools_config.timeout

        # Build URL with path parameters
        url = self._interpolate_string(tool.endpoint, inputs)

        # Add query parameters if configured
        if tool.query_params:
            query = self._interpolate_dict(tool.query_params, inputs)
            query_string = "&".join(f"{k}={v}" for k, v in query.items() if v)
            if query_string:
                url = f"{url}?{query_string}"

        # Build headers
        headers = {"User-Agent": "EmailAssistant/1.0"}
        if tool.headers:
            for key, value in tool.headers.items():
                headers[key] = self._interpolate_string(value, inputs)

        # Build request body for POST, PUT, PATCH
        body = None
        method = tool.method.upper()
        if method in ("POST", "PUT", "PATCH"):
            body_data = None

            # Option 1: body_from_input - use input field as entire body
            if tool.body_from_input and tool.body_from_input in inputs:
                body_data = inputs[tool.body_from_input]
            # Option 2: body_template - static template with placeholders
            elif tool.body_template:
                body_data = self._interpolate_dict(tool.body_template, inputs)

            if body_data is not None:
                body = json.dumps(body_data).encode("utf-8")
                if "Content-Type" not in headers:
                    headers["Content-Type"] = "application/json"

        try:
            request = urllib.request.Request(
                url,
                data=body,
                headers=headers,
                method=tool.method.upper(),
            )

            with urllib.request.urlopen(request, timeout=timeout) as response:
                content = response.read().decode("utf-8")

                # Try to parse as JSON
                try:
                    result = json.loads(content)
                except json.JSONDecodeError:
                    result = content

                # Apply JSONPath extraction if configured
                if tool.response_extract:
                    extracted = extract_jsonpath(result, tool.response_extract)
                    if extracted is not None:
                        result = extracted

                # Apply response template if configured
                if tool.response_template and isinstance(result, dict):
                    formatted = self._interpolate_string(tool.response_template, result)
                    return True, formatted

                return True, result

        except HTTPError as e:
            return False, f"HTTP {e.code}: {e.reason}"
        except URLError as e:
            return False, f"Connection error: {e.reason}"
        except TimeoutError:
            return False, f"Timeout after {timeout}s"
        except Exception as e:
            return False, str(e)

    async def execute_tool(
        self,
        tool_use_id: str,
        tool_name: str,
        inputs: dict[str, Any],
    ) -> ToolResult:
        """Execute a tool asynchronously.

        Args:
            tool_use_id: The ID from Claude's tool_use block
            tool_name: Name of the tool to execute
            inputs: Input parameters from Claude

        Returns:
            ToolResult with execution outcome
        """
        tool = self.tools_config.get_tool(tool_name)
        if not tool:
            return ToolResult(
                tool_use_id=tool_use_id,
                tool_name=tool_name,
                success=False,
                error=f"Unknown tool: {tool_name}",
            )

        if tool.type == "http":
            success, result = await asyncio.to_thread(
                self._execute_http_tool_sync, tool, inputs
            )
            return ToolResult(
                tool_use_id=tool_use_id,
                tool_name=tool_name,
                success=success,
                result=result if success else None,
                error=result if not success else None,
            )
        else:
            return ToolResult(
                tool_use_id=tool_use_id,
                tool_name=tool_name,
                success=False,
                error=f"Unsupported tool type: {tool.type}",
            )

    async def execute_tools(
        self,
        tool_uses: list[dict[str, Any]],
    ) -> list[ToolResult]:
        """Execute multiple tools in parallel.

        Args:
            tool_uses: List of tool_use blocks from Claude's response

        Returns:
            List of ToolResult for each tool
        """
        tasks = [
            self.execute_tool(
                tool_use_id=tu["id"],
                tool_name=tu["name"],
                inputs=tu.get("input", {}),
            )
            for tu in tool_uses
        ]
        return await asyncio.gather(*tasks)


# Global service instance
_tool_service: Optional[ToolService] = None


def get_tool_service() -> ToolService:
    """Get the global tool service instance."""
    global _tool_service
    if _tool_service is None:
        _tool_service = ToolService()
    return _tool_service
