"""Email parsing and formatting utilities."""

import base64
import html
import re
from datetime import datetime
from typing import Optional

import html2text

from ..models import Attachment, Message


class EmailParser:
    """Handles email parsing and text extraction."""

    def __init__(self):
        self._html_converter = self._create_html_converter()

    def _create_html_converter(self) -> html2text.HTML2Text:
        """Create configured HTML to text converter."""
        converter = html2text.HTML2Text()
        converter.ignore_links = False
        converter.ignore_images = True
        converter.ignore_emphasis = True  # Keep bold/italic for Markdown rendering
        converter.ignore_tables = True  # Keep tables for Markdown rendering
        converter.body_width = 0  # No wrapping, let Textual handle it
        converter.unicode_snob = True
        return converter

    def html_to_markdown(self, html_content: str) -> str:
        """Convert HTML to Markdown for rendering.

        Args:
            html_content: Raw HTML string.

        Returns:
            Markdown-formatted text suitable for Textual's Markdown widget.
        """
        text = self._html_converter.handle(html_content)

        # Minimal cleanup - preserve markdown formatting
        # Collapse multiple blank lines into max 2
        text = re.sub(r'\n{3,}', '\n\n', text)

        return text.strip()

    def extract_body(self, payload: dict, prefer_html: bool = True) -> str:
        """Extract text body from message payload.

        Args:
            payload: The message payload from Gmail API.
            prefer_html: If True, prefer HTML content converted to text.

        Returns:
            The message body as plain text.
        """
        plain_body = ""
        html_body = ""

        if "body" in payload and payload["body"].get("data"):
            mime_type = payload.get("mimeType", "")
            content = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
            if mime_type == "text/html":
                html_body = content
            else:
                plain_body = content
        elif "parts" in payload:
            for part in payload["parts"]:
                mime_type = part.get("mimeType", "")
                if mime_type == "text/plain" and not plain_body:
                    if part.get("body", {}).get("data"):
                        plain_body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
                elif mime_type == "text/html" and not html_body:
                    if part.get("body", {}).get("data"):
                        html_body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
                elif mime_type.startswith("multipart/"):
                    nested_body = self.extract_body(part, prefer_html)
                    if nested_body:
                        return nested_body

        # Choose which body to use
        if prefer_html and html_body:
            body = self.html_to_markdown(html_body)
        elif plain_body:
            body = plain_body
        elif html_body:
            body = self.html_to_markdown(html_body)
        else:
            body = ""

        # Decode any remaining HTML entities
        if body:
            body = html.unescape(body)

        return body.strip()

    def extract_attachments(self, payload: dict, message_id: str) -> list[Attachment]:
        """Extract attachment metadata from message payload.

        Args:
            payload: The message payload from Gmail API.
            message_id: The message ID for reference.

        Returns:
            List of Attachment objects.
        """
        attachments: list[Attachment] = []
        self._extract_attachments_recursive(payload, message_id, attachments)
        return attachments

    def _extract_attachments_recursive(
        self, payload: dict, message_id: str, attachments: list[Attachment]
    ) -> None:
        """Recursively extract attachments from MIME parts."""
        # Check if this part is an attachment
        filename = payload.get("filename", "")
        body = payload.get("body", {})
        attachment_id = body.get("attachmentId")

        if filename and attachment_id:
            attachments.append(
                Attachment(
                    filename=filename,
                    mime_type=payload.get("mimeType", "application/octet-stream"),
                    size=body.get("size", 0),
                    attachment_id=attachment_id,
                    message_id=message_id,
                )
            )

        # Recurse into parts
        if "parts" in payload:
            for part in payload["parts"]:
                self._extract_attachments_recursive(part, message_id, attachments)

    def parse_email_address(self, from_header: str) -> tuple[str, str]:
        """Parse email header into name and email address.

        Args:
            from_header: The From or other email header value.

        Returns:
            Tuple of (name, email_address).
        """
        header = from_header.strip()

        # Try to extract email from angle brackets: "Name <email@example.com>"
        bracket_match = re.search(r'<([^>]+@[^>]+)>', header)
        if bracket_match:
            email = bracket_match.group(1).strip()
            name_part = header[:bracket_match.start()].strip().strip('"').strip()
            return name_part if name_part else email, email

        # Try to find a plain email address
        email_match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', header)
        if email_match:
            email = email_match.group(0)
            return email, email

        return header, header

    def parse_message(self, msg_data: dict, user_email: str) -> Message:
        """Parse Gmail API message data into Message object.

        Args:
            msg_data: Raw message data from Gmail API.
            user_email: Current user's email address.

        Returns:
            Parsed Message object.
        """
        headers = {h["name"].lower(): h["value"] for h in msg_data["payload"].get("headers", [])}

        from_header = headers.get("from", "")
        sender_name, sender_email = self.parse_email_address(from_header)

        # Get Reply-To header if present
        reply_to_header = headers.get("reply-to", "").strip()
        if reply_to_header:
            if "<" in reply_to_header and ">" in reply_to_header:
                start = reply_to_header.index("<") + 1
                end = reply_to_header.index(">")
                reply_to_email = reply_to_header[start:end].strip()
            else:
                reply_to_email = reply_to_header
        else:
            reply_to_email = ""

        # Get message body
        body = self.extract_body(msg_data["payload"])

        # Extract attachments
        attachments = self.extract_attachments(msg_data["payload"], msg_data["id"])

        # Parse date
        internal_date = int(msg_data.get("internalDate", 0))
        date = datetime.fromtimestamp(internal_date / 1000)

        # Check if unread
        labels = msg_data.get("labelIds", [])
        is_unread = "UNREAD" in labels

        # Get Message-ID header for threading
        message_id = headers.get("message-id", "")

        return Message(
            id=msg_data["id"],
            thread_id=msg_data["threadId"],
            sender=sender_name,
            sender_email=sender_email.lower(),
            recipient=headers.get("to", ""),
            subject=headers.get("subject", "(no subject)"),
            body=body,
            date=date,
            is_unread=is_unread,
            reply_to=reply_to_email.lower() if reply_to_email else "",
            message_id=message_id,
            attachments=attachments,
        )

    @staticmethod
    def strip_quoted_lines(body: str) -> str:
        """Remove quoted lines (starting with >) from message body.

        Args:
            body: The message body text.

        Returns:
            Body with quoted lines removed.
        """
        lines = body.split('\n')
        result = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('>'):
                continue
            if stripped.endswith('wrote:') or stripped.endswith('napisal(a):'):
                continue
            result.append(line)

        while result and not result[-1].strip():
            result.pop()

        return '\n'.join(result)


# Global parser instance
_email_parser: Optional[EmailParser] = None


def get_email_parser() -> EmailParser:
    """Get the global email parser instance."""
    global _email_parser
    if _email_parser is None:
        _email_parser = EmailParser()
    return _email_parser
