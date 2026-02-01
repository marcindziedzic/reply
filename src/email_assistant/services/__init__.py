"""Services for Email Assistant."""

from .email_parser import EmailParser, get_email_parser

# Note: reminder_service is imported lazily to avoid circular imports
# Use: from email_assistant.services.reminder_service import get_reminder_service

__all__ = [
    "EmailParser",
    "get_email_parser",
]
