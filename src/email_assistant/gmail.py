"""Gmail API client for Email Assistant."""

import base64
import mimetypes
import re
from datetime import datetime
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email import encoders
from pathlib import Path
from typing import Optional

import markdown

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from .config import get_config
from .models import Label, Message, Thread
from .services.email_parser import get_email_parser

# Gmail API scopes
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/contacts.readonly",
]


class GmailClient:
    """Gmail API client."""

    def __init__(self):
        self._service = None
        self._user_email: Optional[str] = None
        self._signature_html: Optional[str] = None
        self._parser = get_email_parser()

    def _get_service(self):
        """Get or create Gmail API service."""
        if self._service is not None:
            return self._service

        config = get_config()
        creds = None

        token_path = config.get_token_path()
        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                credentials_path = config.get_credentials_path()
                if not credentials_path.exists():
                    raise FileNotFoundError(
                        f"Credentials file not found: {credentials_path}\n"
                        "Please download OAuth credentials from Google Cloud Console."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(credentials_path), SCOPES
                )
                creds = flow.run_local_server(port=0)

            with open(token_path, "w") as token:
                token.write(creds.to_json())

        self._service = build("gmail", "v1", credentials=creds)
        return self._service

    def get_user_email(self) -> str:
        """Get the email address of the authenticated user."""
        if self._user_email is not None:
            return self._user_email

        service = self._get_service()
        profile = service.users().getProfile(userId="me").execute()
        self._user_email = profile.get("emailAddress", "")
        return self._user_email

    def get_signature_html(self) -> str:
        """Get the user's Gmail signature as HTML."""
        if self._signature_html is not None:
            return self._signature_html

        service = self._get_service()
        user_email = self.get_user_email()

        try:
            send_as = (
                service.users()
                .settings()
                .sendAs()
                .get(userId="me", sendAsEmail=user_email)
                .execute()
            )
            self._signature_html = send_as.get("signature", "")
        except Exception:
            self._signature_html = ""

        return self._signature_html

    def _markdown_to_html(self, text: str) -> str:
        """Convert markdown text to HTML."""
        # Convert markdown to HTML
        html_content = markdown.markdown(
            text,
            extensions=["nl2br", "sane_lists"],
        )

        # Wrap in basic HTML structure with Gmail's default styling
        html = f"""<div style="font-family: Arial, Helvetica, sans-serif; font-size: small; color: rgb(34, 34, 34);">
{html_content}
</div>"""

        return html

    def _create_html_message(
        self,
        recipient: str,
        subject: str,
        body_markdown: str,
        in_reply_to: Optional[str] = None,
        references: Optional[str] = None,
        attachments: Optional[list[tuple[str, bytes]]] = None,
        inline_images: Optional[dict[str, tuple[str, bytes]]] = None,
    ) -> MIMEMultipart:
        """Create a multipart email with HTML body and signature.

        Args:
            recipient: Email recipient address.
            subject: Email subject.
            body_markdown: Email body in markdown format.
            in_reply_to: Optional Message-ID to reply to.
            references: Optional References header.
            attachments: Optional list of (filename, content_bytes) tuples.
            inline_images: Optional dict of {cid: (filename, content_bytes)} for inline images.
        """
        # Convert markdown to HTML
        body_html = self._markdown_to_html(body_markdown)

        # Get signature
        signature = self.get_signature_html()
        if signature:
            body_html += f'<br><br><div class="gmail_signature">{signature}</div>'

        # Plain text version (strip HTML for fallback)
        plain_text = body_markdown
        if signature:
            # Convert signature HTML to plain text (basic)
            sig_text = re.sub(r"<[^>]+>", "", signature)
            sig_text = re.sub(r"\s+", " ", sig_text).strip()
            if sig_text:
                plain_text += f"\n\n--\n{sig_text}"

        # Create text parts
        part_plain = MIMEText(plain_text, "plain", "utf-8")
        part_html = MIMEText(body_html, "html", "utf-8")

        # Create alternative part for text/html
        msg_alternative = MIMEMultipart("alternative")
        msg_alternative.attach(part_plain)
        msg_alternative.attach(part_html)

        # Build message structure based on inline images and attachments
        # Structure with inline images:
        #   multipart/mixed (if attachments)
        #   └── multipart/related
        #       ├── multipart/alternative
        #       │   ├── text/plain
        #       │   └── text/html
        #       └── image/... (inline images with Content-ID)
        #   └── attachments...

        if inline_images:
            # Wrap alternative in related for inline images
            msg_related = MIMEMultipart("related")
            msg_related.attach(msg_alternative)

            # Add inline images
            for cid, (filename, content) in inline_images.items():
                mime_type, _ = mimetypes.guess_type(filename)
                if mime_type is None:
                    mime_type = "image/png"

                main_type, sub_type = mime_type.split("/", 1)

                img_part = MIMEBase(main_type, sub_type)
                img_part.set_payload(content)
                encoders.encode_base64(img_part)
                img_part.add_header("Content-ID", f"<{cid}>")
                img_part.add_header(
                    "Content-Disposition",
                    "inline",
                    filename=filename,
                )
                msg_related.attach(img_part)

            content_part = msg_related
        else:
            content_part = msg_alternative

        # If we have attachments, wrap in mixed multipart
        if attachments:
            message = MIMEMultipart("mixed")
            message.attach(content_part)

            for filename, content in attachments:
                # Guess MIME type
                mime_type, _ = mimetypes.guess_type(filename)
                if mime_type is None:
                    mime_type = "application/octet-stream"

                main_type, sub_type = mime_type.split("/", 1)

                part = MIMEBase(main_type, sub_type)
                part.set_payload(content)
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    "attachment",
                    filename=filename,
                )
                message.attach(part)
        else:
            # No attachments - use content_part directly
            message = content_part

        message["to"] = recipient
        message["subject"] = subject

        if in_reply_to:
            message["In-Reply-To"] = in_reply_to
        if references:
            message["References"] = references

        return message

    def get_unread_threads(self) -> list[Thread]:
        """Get threads with unread messages (metadata only for fast loading)."""
        service = self._get_service()
        config = get_config()

        results = (
            service.users()
            .threads()
            .list(userId="me", q="is:unread in:inbox", maxResults=config.gmail.max_threads)
            .execute()
        )

        threads_data = results.get("threads", [])
        threads = []

        for thread_data in threads_data:
            thread = self.get_thread_metadata(thread_data["id"])
            if thread:
                threads.append(thread)

        return threads

    def search_threads(self, query: str, max_results: int = 50) -> list[Thread]:
        """Search for threads using Gmail query syntax.

        Args:
            query: Gmail search query (e.g., "from:user@example.com")
            max_results: Maximum number of threads to return.

        Returns:
            List of matching threads (metadata only).
        """
        service = self._get_service()

        results = (
            service.users()
            .threads()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )

        threads_data = results.get("threads", [])
        threads = []

        for thread_data in threads_data:
            thread = self.get_thread_metadata(thread_data["id"])
            if thread:
                threads.append(thread)

        return threads

    def get_thread(self, thread_id: str) -> Optional[Thread]:
        """Get a full thread with all messages."""
        service = self._get_service()
        user_email = self.get_user_email()

        try:
            thread_data = (
                service.users()
                .threads()
                .get(userId="me", id=thread_id, format="full")
                .execute()
            )
        except Exception:
            return None

        messages = []
        has_unread = False
        subject = "(no subject)"
        sender_name = None
        sender_email = None

        for msg_data in thread_data.get("messages", []):
            msg = self._parser.parse_message(msg_data, user_email)
            messages.append(msg)
            if msg.is_unread:
                has_unread = True
            if msg.subject and subject == "(no subject)":
                subject = msg.subject
            # Extract sender from first non-user message
            if sender_email is None and msg.sender_email.lower() != user_email.lower():
                sender_name = msg.sender
                sender_email = msg.sender_email

        if not messages:
            return None

        messages.sort(key=lambda m: m.date)

        return Thread(
            id=thread_id,
            subject=subject,
            messages=messages,
            has_unread=has_unread,
            last_message_date=messages[-1].date if messages else None,
            sender_name=sender_name,
            sender_email=sender_email,
            message_count=len(messages),
            messages_loaded=True,
        )

    def get_thread_metadata(self, thread_id: str) -> Optional[Thread]:
        """Get thread metadata without full message content (for list display)."""
        service = self._get_service()
        user_email = self.get_user_email()

        try:
            thread_data = (
                service.users()
                .threads()
                .get(userId="me", id=thread_id, format="metadata")
                .execute()
            )
        except Exception:
            return None

        messages_data = thread_data.get("messages", [])
        if not messages_data:
            return None

        has_unread = False
        subject = "(no subject)"
        sender_name = None
        sender_email = None
        last_message_date = None

        for msg_data in messages_data:
            # Check for unread
            label_ids = msg_data.get("labelIds", [])
            if "UNREAD" in label_ids:
                has_unread = True

            # Parse headers
            headers = {
                h["name"].lower(): h["value"]
                for h in msg_data.get("payload", {}).get("headers", [])
            }

            # Get subject
            if subject == "(no subject)" and headers.get("subject"):
                subject = headers["subject"]

            # Get sender from first non-user message
            if sender_email is None:
                from_header = headers.get("from", "")
                parsed_name, parsed_email = self._parser.parse_email_address(from_header)
                if parsed_email.lower() != user_email.lower():
                    sender_name = parsed_name
                    sender_email = parsed_email

            # Get date from last message
            internal_date = msg_data.get("internalDate")
            if internal_date:
                last_message_date = datetime.fromtimestamp(int(internal_date) / 1000)

        return Thread(
            id=thread_id,
            subject=subject,
            messages=[],  # Empty - will be loaded on demand
            has_unread=has_unread,
            last_message_date=last_message_date,
            sender_name=sender_name,
            sender_email=sender_email,
            message_count=len(messages_data),
            messages_loaded=False,
        )

    def get_user_labels(self) -> list[Label]:
        """Get user-created labels (excluding system labels)."""
        service = self._get_service()
        results = service.users().labels().list(userId="me").execute()
        labels = []

        for label_data in results.get("labels", []):
            if label_data.get("type") == "user":
                labels.append(Label(
                    id=label_data["id"],
                    name=label_data["name"],
                ))

        labels.sort(key=lambda l: l.name.lower())
        return labels

    def mark_as_read(
        self,
        thread_ids: list[str],
        label_id: Optional[str] = None,
        archive: bool = True,
    ) -> None:
        """Mark threads as read, optionally add a label, and archive.

        Also removes any reminder labels (Reminders/*) from the threads.
        """
        service = self._get_service()

        # Get all user labels to map IDs to names
        all_labels = self.get_user_labels()
        id_to_label = {label.id: label for label in all_labels}

        for thread_id in thread_ids:
            remove_labels = ["UNREAD"]
            if archive:
                remove_labels.append("INBOX")

            # Find and remove reminder labels
            thread_label_ids = self.get_thread_labels(thread_id)
            for tid in thread_label_ids:
                label = id_to_label.get(tid)
                if label and label.name.startswith("Reminders/"):
                    remove_labels.append(tid)

            modify_request = {"removeLabelIds": remove_labels}
            if label_id:
                modify_request["addLabelIds"] = [label_id]

            service.users().threads().modify(
                userId="me",
                id=thread_id,
                body=modify_request,
            ).execute()

    def trash_thread(self, thread_id: str) -> None:
        """Move a thread to trash."""
        service = self._get_service()
        service.users().threads().trash(userId="me", id=thread_id).execute()

    def create_draft(
        self,
        thread_id: str,
        message_body: str,
        attachments: Optional[list[tuple[str, bytes]]] = None,
        inline_images: Optional[dict[str, tuple[str, bytes]]] = None,
    ) -> dict:
        """Create a draft reply to a thread (HTML with signature).

        Args:
            thread_id: The thread ID to reply to.
            message_body: The message body in markdown format.
            attachments: Optional list of (filename, content_bytes) tuples.
            inline_images: Optional dict of {cid: (filename, content_bytes)} for inline images.
        """
        service = self._get_service()
        user_email = self.get_user_email()

        thread = self.get_thread(thread_id)
        if not thread or not thread.messages:
            raise ValueError(f"Thread not found: {thread_id}")

        last_message = thread.messages[-1]
        recipient = thread.get_reply_recipient(user_email)

        subject = last_message.subject
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        # Create HTML message with signature
        message = self._create_html_message(
            recipient=recipient,
            subject=subject,
            body_markdown=message_body,
            in_reply_to=last_message.message_id,
            references=last_message.message_id,
            attachments=attachments,
            inline_images=inline_images,
        )

        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

        draft = (
            service.users()
            .drafts()
            .create(
                userId="me",
                body={
                    "message": {
                        "raw": raw_message,
                        "threadId": thread_id,
                    }
                },
            )
            .execute()
        )

        return draft

    def create_new_draft(
        self,
        recipient: str,
        subject: str,
        message_body: str,
        attachments: Optional[list[tuple[str, bytes]]] = None,
        inline_images: Optional[dict[str, tuple[str, bytes]]] = None,
    ) -> dict:
        """Create a new draft (not a reply to existing thread, HTML with signature).

        Args:
            recipient: Email recipient address.
            subject: Email subject.
            message_body: The message body in markdown format.
            attachments: Optional list of (filename, content_bytes) tuples.
            inline_images: Optional dict of {cid: (filename, content_bytes)} for inline images.
        """
        service = self._get_service()

        # Create HTML message with signature
        message = self._create_html_message(
            recipient=recipient,
            subject=subject,
            body_markdown=message_body,
            attachments=attachments,
            inline_images=inline_images,
        )

        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

        draft = (
            service.users()
            .drafts()
            .create(
                userId="me",
                body={
                    "message": {
                        "raw": raw_message,
                    }
                },
            )
            .execute()
        )

        return draft

    def send_reply(
        self,
        thread_id: str,
        message_body: str,
        attachments: Optional[list[tuple[str, bytes]]] = None,
        inline_images: Optional[dict[str, tuple[str, bytes]]] = None,
    ) -> dict:
        """Send a reply to a thread immediately (HTML with signature).

        Args:
            thread_id: The thread ID to reply to.
            message_body: The message body in markdown format.
            attachments: Optional list of (filename, content_bytes) tuples.
            inline_images: Optional dict of {cid: (filename, content_bytes)} for inline images.
        """
        service = self._get_service()
        user_email = self.get_user_email()

        thread = self.get_thread(thread_id)
        if not thread or not thread.messages:
            raise ValueError(f"Thread not found: {thread_id}")

        last_message = thread.messages[-1]
        recipient = thread.get_reply_recipient(user_email)

        subject = last_message.subject
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        # Create HTML message with signature
        message = self._create_html_message(
            recipient=recipient,
            subject=subject,
            body_markdown=message_body,
            in_reply_to=last_message.message_id,
            references=last_message.message_id,
            attachments=attachments,
            inline_images=inline_images,
        )

        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

        sent = (
            service.users()
            .messages()
            .send(
                userId="me",
                body={
                    "raw": raw_message,
                    "threadId": thread_id,
                },
            )
            .execute()
        )

        return sent

    def send_new_message(
        self,
        recipient: str,
        subject: str,
        message_body: str,
        attachments: Optional[list[tuple[str, bytes]]] = None,
        inline_images: Optional[dict[str, tuple[str, bytes]]] = None,
    ) -> dict:
        """Send a new message immediately (HTML with signature).

        Args:
            recipient: Email recipient address.
            subject: Email subject.
            message_body: The message body in markdown format.
            attachments: Optional list of (filename, content_bytes) tuples.
            inline_images: Optional dict of {cid: (filename, content_bytes)} for inline images.
        """
        service = self._get_service()

        # Create HTML message with signature
        message = self._create_html_message(
            recipient=recipient,
            subject=subject,
            body_markdown=message_body,
            attachments=attachments,
            inline_images=inline_images,
        )

        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

        sent = (
            service.users()
            .messages()
            .send(
                userId="me",
                body={
                    "raw": raw_message,
                },
            )
            .execute()
        )

        return sent

    # ----- Label Management Methods -----

    def create_label(self, name: str) -> Label:
        """Create a new Gmail label."""
        service = self._get_service()

        label_body = {
            "name": name,
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show",
        }

        result = service.users().labels().create(userId="me", body=label_body).execute()

        return Label(id=result["id"], name=result["name"])

    def get_label_by_name(self, name: str) -> Optional[Label]:
        """Get a label by its name, or None if not found."""
        labels = self.get_user_labels()
        for label in labels:
            if label.name == name:
                return label
        return None

    def get_or_create_label(self, name: str) -> Label:
        """Get an existing label or create it if it doesn't exist."""
        label = self.get_label_by_name(name)
        if label:
            return label
        return self.create_label(name)

    def delete_label(self, label_id: str) -> None:
        """Delete a Gmail label."""
        service = self._get_service()
        service.users().labels().delete(userId="me", id=label_id).execute()

    def add_labels_to_thread(self, thread_id: str, label_ids: list[str]) -> None:
        """Add labels to a thread."""
        if not label_ids:
            return

        service = self._get_service()
        service.users().threads().modify(
            userId="me",
            id=thread_id,
            body={"addLabelIds": label_ids},
        ).execute()

    def remove_labels_from_thread(self, thread_id: str, label_ids: list[str]) -> None:
        """Remove labels from a thread."""
        if not label_ids:
            return

        service = self._get_service()
        service.users().threads().modify(
            userId="me",
            id=thread_id,
            body={"removeLabelIds": label_ids},
        ).execute()

    def get_threads_with_label(self, label_id: str) -> list[Thread]:
        """Get all threads with a specific label (metadata only for fast loading)."""
        service = self._get_service()
        config = get_config()

        results = (
            service.users()
            .threads()
            .list(userId="me", labelIds=[label_id], maxResults=config.gmail.max_threads)
            .execute()
        )

        threads_data = results.get("threads", [])
        threads = []

        for thread_data in threads_data:
            thread = self.get_thread_metadata(thread_data["id"])
            if thread:
                threads.append(thread)

        return threads

    def get_thread_labels(self, thread_id: str) -> list[str]:
        """Get the label IDs for a specific thread."""
        service = self._get_service()

        try:
            thread_data = (
                service.users()
                .threads()
                .get(userId="me", id=thread_id, format="minimal")
                .execute()
            )

            # Labels are on messages in the thread
            label_ids = set()
            for msg in thread_data.get("messages", []):
                for label_id in msg.get("labelIds", []):
                    label_ids.add(label_id)

            return list(label_ids)
        except Exception:
            return []

    def download_attachment(self, message_id: str, attachment_id: str) -> bytes:
        """Download attachment content.

        Args:
            message_id: The message ID containing the attachment.
            attachment_id: The attachment ID from Gmail API.

        Returns:
            The attachment content as bytes.
        """
        service = self._get_service()

        attachment = (
            service.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=message_id, id=attachment_id)
            .execute()
        )

        data = attachment.get("data", "")
        return base64.urlsafe_b64decode(data)


# Global client instance
_gmail_client: Optional[GmailClient] = None


def get_gmail_client() -> GmailClient:
    """Get the global Gmail client instance."""
    global _gmail_client
    if _gmail_client is None:
        _gmail_client = GmailClient()
    return _gmail_client
