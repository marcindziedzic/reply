"""Email data models."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Attachment:
    """Represents an email attachment."""

    filename: str
    mime_type: str
    size: int
    attachment_id: str
    message_id: str


@dataclass
class Message:
    """Represents an email message."""

    id: str
    thread_id: str
    sender: str
    sender_email: str
    recipient: str
    subject: str
    body: str
    date: datetime
    is_unread: bool
    reply_to: str = ""
    message_id: str = ""
    attachments: list[Attachment] = field(default_factory=list)


@dataclass
class Thread:
    """Represents an email thread."""

    id: str
    subject: str
    messages: list[Message] = field(default_factory=list)
    has_unread: bool = False
    last_message_date: Optional[datetime] = None
    # Metadata fields for list display (lazy loading optimization)
    sender_name: Optional[str] = None
    sender_email: Optional[str] = None
    message_count: int = 0
    messages_loaded: bool = False

    def get_reply_recipient(self, user_email: str) -> str:
        """Get the email address to reply to in this thread.

        Logic:
        1. Find the first message from someone other than the user
        2. Use reply_to header if present, otherwise sender_email
        3. Fallback to recipient field from last message (ping scenario)
        """
        for msg in self.messages:
            if msg.sender_email.lower() != user_email.lower():
                return msg.reply_to if msg.reply_to else msg.sender_email

        # Fallback: no other sender found (e.g., pinging someone who didn't reply)
        if self.messages:
            return self.messages[-1].recipient

        return ""


@dataclass
class Label:
    """Represents a Gmail label."""

    id: str
    name: str
