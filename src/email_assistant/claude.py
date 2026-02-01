"""Claude API client for Email Assistant."""

import asyncio
from typing import Any, Optional

import anthropic

from .config import get_config
from .models import Thread
from .services.context_service import get_context_service
from .services.query_service import get_query_service
from .services.tool_service import get_tool_service


def format_threads_for_claude(client_email: str, threads: list[Thread], user_email: str) -> str:
    """
    Format email threads for Claude prompt.

    Args:
        client_email: Client's email address
        threads: All threads with the client, chronologically sorted
        user_email: Current user's email address

    Returns:
        Formatted string for Claude prompt
    """
    lines = [f"=== HISTORIA KORESPONDENCJI Z: {client_email} ===\n"]

    for thread in threads:
        # Thread header
        unread_marker = " [UNREAD]" if thread.has_unread else ""
        date_str = thread.last_message_date.strftime("%Y-%m-%d") if thread.last_message_date else "unknown"
        lines.append(f"--- THREAD: {thread.subject}{unread_marker} ({date_str}) ---\n")

        for msg in thread.messages:
            # Message header
            date_time_str = msg.date.strftime("%Y-%m-%d %H:%M")
            unread_msg_marker = " [UNREAD]" if msg.is_unread else ""

            if msg.sender_email.lower() == user_email.lower():
                sender_display = f"{user_email} (me)"
            else:
                sender_display = msg.sender_email

            lines.append(f"[{date_time_str}] From: {sender_display}{unread_msg_marker}")
            lines.append(msg.body)
            lines.append("")

        lines.append("")

    lines.append("=== END OF HISTORY ===\n")
    lines.append("Prepare a response to unread messages.")

    return "\n".join(lines)


class ClaudeClient:
    """Claude API client for generating email responses."""

    def __init__(self):
        self._client: Optional[anthropic.Anthropic] = None

    def _get_client(self) -> anthropic.Anthropic:
        """Get or create Anthropic client."""
        if self._client is None:
            config = get_config()
            if not config.claude.api_key:
                raise ValueError("Claude API key not configured")

            # Build client kwargs
            client_kwargs = {"api_key": config.claude.api_key}

            # Add project header if configured
            if config.claude.project_id:
                client_kwargs["default_headers"] = {
                    "anthropic-project": config.claude.project_id
                }

            self._client = anthropic.Anthropic(**client_kwargs)
        return self._client

    def _build_cached_system_parts(
        self,
        task_prompt: Optional[str] = None,
        optional_context_files: list[str] | None = None,
    ) -> list[dict]:
        """
        Build system prompt parts with prompt caching.

        Structure:
        1. [CACHED] Context from files (instructions, tone_of_voice, etc.)
        2. [CACHED] User data (rarely changes)
        3. [NOT CACHED] Task-specific prompt (varies per request)

        Args:
            task_prompt: Optional task-specific prompt to append (not cached).
            optional_context_files: List of optional context filenames to include.

        Returns:
            List of system prompt parts for the API call.
        """
        config = get_config()
        context_service = get_context_service()
        context = context_service.get_context(optional_files=optional_context_files)

        system_parts = []

        # Part 1: Context from files (CACHED)
        # This is the main benefit - all context files loaded once and cached
        if context:
            system_parts.append({
                "type": "text",
                "text": context,
                "cache_control": {"type": "ephemeral"}
            })

        # Part 2: User data for signatures (CACHED together with context)
        if config.user.variables:
            user_info = "=== DANE UZYTKOWNIKA (do podpisu) ===\n"
            user_info += "\n".join(
                f"{key}: {value}"
                for key, value in config.user.variables.items()
                if value
            )
            system_parts.append({
                "type": "text",
                "text": user_info,
                "cache_control": {"type": "ephemeral"}
            })

        # Part 3: Task-specific prompt (NOT cached - changes per request type)
        if task_prompt:
            system_parts.append({
                "type": "text",
                "text": task_prompt
            })

        return system_parts

    def _call_with_tools(
        self,
        method_name: str,
        system_parts: list[dict],
        user_message: str,
        max_tokens: int = 4096,
    ) -> str:
        """
        Call Claude API with tool support and handle tool execution loop.

        Args:
            method_name: Name of the calling method (for permission check)
            system_parts: System prompt parts
            user_message: User message content
            max_tokens: Maximum tokens for response

        Returns:
            Final text response after tool execution
        """
        config = get_config()
        client = self._get_client()
        tool_service = get_tool_service()

        # Check if tools should be used for this method
        use_tools = (
            tool_service.has_tools() and
            tool_service.is_method_allowed(method_name)
        )

        tools = tool_service.get_claude_tools() if use_tools else None
        max_iterations = tool_service.tools_config.max_tool_calls if use_tools else 1

        messages = [{"role": "user", "content": user_message}]

        for iteration in range(max_iterations + 1):
            # Build API call kwargs
            api_kwargs: dict[str, Any] = {
                "model": config.claude.model,
                "max_tokens": max_tokens,
                "system": system_parts,
                "messages": messages,
            }

            # Add tools only on first iteration or if we have tools
            if tools and iteration == 0:
                api_kwargs["tools"] = tools

            response = client.messages.create(**api_kwargs)

            # Check for tool use in response
            tool_uses = [
                block for block in response.content
                if block.type == "tool_use"
            ]

            if not tool_uses:
                # No tool use - extract text response
                for block in response.content:
                    if block.type == "text":
                        return block.text
                return ""

            # Execute tools asynchronously
            tool_use_dicts = [
                {"id": tu.id, "name": tu.name, "input": tu.input}
                for tu in tool_uses
            ]

            # Run tool execution in event loop
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # If already in async context, create a new task
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(
                            asyncio.run,
                            tool_service.execute_tools(tool_use_dicts)
                        )
                        results = future.result()
                else:
                    results = loop.run_until_complete(
                        tool_service.execute_tools(tool_use_dicts)
                    )
            except RuntimeError:
                # No event loop - create one
                results = asyncio.run(tool_service.execute_tools(tool_use_dicts))

            # Build tool results for next iteration
            tool_results = [result.to_tool_result_block() for result in results]

            # Add assistant response and tool results to messages
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

        # Max iterations reached - return whatever we have
        return ""

    def generate_response(
        self,
        client_email: str,
        threads: list[Thread],
        user_email: str,
        hints: Optional[str] = None,
        optional_context_files: list[str] | None = None,
        previous_response: Optional[str] = None,
        original_hints: Optional[str] = None,
    ) -> str:
        """
        Generate email response using Claude.

        Args:
            client_email: Client's email address
            threads: All threads with the client (chronologically sorted)
            user_email: Current user's email address
            hints: Optional additional instructions from user
            optional_context_files: List of optional context filenames to include
            previous_response: Previously generated response (for regeneration)
            original_hints: Original hints used for first generation (for regeneration)

        Returns:
            Generated email response text
        """
        query_service = get_query_service()

        # Use regeneration prompt if previous response is provided
        is_regeneration = previous_response is not None
        if is_regeneration:
            task_prompt = query_service.get_query("regenerate_system")
        else:
            task_prompt = query_service.get_query("response_system")

        # Build system prompt with caching
        system_parts = self._build_cached_system_parts(task_prompt, optional_context_files)

        # Format the email history
        email_history = format_threads_for_claude(client_email, threads, user_email)

        # Build the user message
        user_message = email_history

        if is_regeneration:
            # For regeneration, include previous response and hints context
            user_message += f"\n\n=== POPRZEDNIO WYGENEROWANA ODPOWIEDZ ===\n{previous_response}\n=== KONIEC POPRZEDNIEJ ODPOWIEDZI ==="

            if original_hints:
                user_message += f"\n\nOryginalne wskazowki: {original_hints}"

            if hints:
                user_message += f"\n\nNowe wskazowki do poprawy: {hints}"
            else:
                user_message += "\n\nPlease improve the response while maintaining its general character, but improving the style and content."
        else:
            # Original generation
            if hints:
                user_message += f"\n\nAdditional hints: {hints}"

        # Call Claude API with tool support
        return self._call_with_tools(
            method_name="generate_response",
            system_parts=system_parts,
            user_message=user_message,
            max_tokens=4096,
        )

    def generate_new_message(
        self,
        recipient_email: str,
        subject: str,
        context: str,
        user_email: str,
    ) -> str:
        """
        Generate a new email message (not a reply) using Claude.

        Args:
            recipient_email: Recipient's email address
            subject: Email subject
            context: User-provided context/instructions for the message
            user_email: Current user's email address

        Returns:
            Generated email message text
        """
        config = get_config()
        client = self._get_client()
        query_service = get_query_service()

        # Build system prompt with caching (context + user data)
        system_parts = self._build_cached_system_parts()

        # Build the user message with task details
        prompt = query_service.get_query(
            "new_message",
            recipient_email=recipient_email,
            subject=subject,
            context=context,
        )

        response = client.messages.create(
            model=config.claude.model,
            max_tokens=4096,
            system=system_parts,
            messages=[
                {"role": "user", "content": prompt}
            ],
        )

        if response.content and len(response.content) > 0:
            return response.content[0].text

        return ""

    def extract_essence(self, message_body: str) -> str:
        """
        Extract essential content from an email, removing bloatware.

        Args:
            message_body: The raw email message body.

        Returns:
            Cleaned message with only essential content.
        """
        config = get_config()
        client = self._get_client()
        query_service = get_query_service()

        prompt = query_service.get_query("extract_essence", message_body=message_body)

        response = client.messages.create(
            model=config.claude.model,
            max_tokens=1024,
            messages=[
                {"role": "user", "content": prompt}
            ],
        )

        if response.content and len(response.content) > 0:
            return response.content[0].text

        return message_body

    def ask_question(
        self,
        question: str,
        thread: Thread,
        user_email: str,
    ) -> str:
        """
        Ask a question about an email thread.

        Args:
            question: The question to ask about the thread.
            thread: The email thread to analyze.
            user_email: Current user's email address.

        Returns:
            AI response to the question.
        """
        query_service = get_query_service()

        # Build system prompt with caching (includes company context for answering questions)
        task_prompt = query_service.get_query("ask_question_system") if self._query_exists("ask_question_system") else None
        system_parts = self._build_cached_system_parts(task_prompt)

        # Format thread history
        thread_history = self._format_thread_for_question(thread, user_email)

        prompt = query_service.get_query(
            "ask_question",
            thread_history=thread_history,
            question=question,
        )

        # Call Claude API with tool support
        result = self._call_with_tools(
            method_name="ask_question",
            system_parts=system_parts,
            user_message=prompt,
            max_tokens=2048,
        )

        if result:
            return result

        return "Failed to get a response."

    def _query_exists(self, name: str) -> bool:
        """Check if a query template exists."""
        query_service = get_query_service()
        try:
            query_service.get_query(name)
            return True
        except FileNotFoundError:
            return False

    def _format_thread_for_question(self, thread: Thread, user_email: str) -> str:
        """Format a single thread for question context."""
        lines = [f"Temat: {thread.subject}\n"]

        for msg in thread.messages:
            date_time_str = msg.date.strftime("%Y-%m-%d %H:%M")

            if msg.sender_email.lower() == user_email.lower():
                sender_display = f"{user_email} (ja)"
            else:
                sender_display = msg.sender_email

            lines.append(f"[{date_time_str}] Od: {sender_display}")
            lines.append(msg.body)
            lines.append("")

        return "\n".join(lines)

    def generate_timeline_summary(self, thread: Thread, user_email: str) -> str:
        """
        Generate a timeline summary of all messages in a thread.

        Args:
            thread: The email thread to summarize.
            user_email: Current user's email address.

        Returns:
            Timeline summary of all messages.
        """
        config = get_config()
        client = self._get_client()
        query_service = get_query_service()

        # Format thread history
        thread_history = self._format_thread_for_question(thread, user_email)

        prompt = query_service.get_query("timeline_summary", thread_history=thread_history)

        response = client.messages.create(
            model=config.claude.model,
            max_tokens=2048,
            messages=[
                {"role": "user", "content": prompt}
            ],
        )

        if response.content and len(response.content) > 0:
            return response.content[0].text

        return "Failed to generate summary."

    def generate_key_agreements(self, thread: Thread, user_email: str) -> str:
        """
        Generate key agreements/decisions summary from all messages in a thread.

        Args:
            thread: The email thread to analyze.
            user_email: Current user's email address.

        Returns:
            Summary of key agreements and decisions.
        """
        config = get_config()
        client = self._get_client()
        query_service = get_query_service()

        # Format thread history
        thread_history = self._format_thread_for_question(thread, user_email)

        prompt = query_service.get_query("key_agreements", thread_history=thread_history)

        response = client.messages.create(
            model=config.claude.model,
            max_tokens=2048,
            messages=[
                {"role": "user", "content": prompt}
            ],
        )

        if response.content and len(response.content) > 0:
            return response.content[0].text

        return "Failed to extract agreements."


# Global client instance
_claude_client: Optional[ClaudeClient] = None


def get_claude_client() -> ClaudeClient:
    """Get the global Claude client instance."""
    global _claude_client
    if _claude_client is None:
        _claude_client = ClaudeClient()
    return _claude_client
