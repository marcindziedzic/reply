"""Google Contacts API client for Email Assistant."""

from dataclasses import dataclass
from typing import Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from .gmail import SCOPES
from .config import get_config


@dataclass
class Contact:
    """Represents a contact from Google Contacts."""

    name: str
    email: str

    @property
    def display_name(self) -> str:
        """Get display name in 'Name <email>' format."""
        if self.name:
            return f"{self.name} <{self.email}>"
        return self.email


class ContactsClient:
    """Google Contacts (People API) client."""

    def __init__(self):
        self._service = None

    def _get_service(self):
        """Get or create People API service."""
        if self._service is not None:
            return self._service

        config = get_config()
        token_path = config.get_token_path()

        if not token_path.exists():
            raise FileNotFoundError(
                "Token file not found. Please authenticate via Gmail first."
            )

        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        if not creds or not creds.valid:
            raise ValueError(
                "Invalid credentials. Please re-authenticate "
                "(delete token.json and restart the app)."
            )

        self._service = build("people", "v1", credentials=creds)
        return self._service

    def search_contacts(self, query: str, limit: int = 10) -> list[Contact]:
        """Search contacts by name or email.

        Args:
            query: Search query string
            limit: Maximum number of results

        Returns:
            List of matching contacts
        """
        if not query or len(query) < 3:
            return []

        try:
            service = self._get_service()

            # Use searchContacts for query-based search
            results = (
                service.people()
                .searchContacts(
                    query=query,
                    readMask="names,emailAddresses",
                    pageSize=limit,
                )
                .execute()
            )

            contacts = []
            for person in results.get("results", []):
                person_data = person.get("person", {})
                emails = person_data.get("emailAddresses", [])
                names = person_data.get("names", [])

                if emails:
                    name = names[0].get("displayName", "") if names else ""
                    for email_entry in emails:
                        email = email_entry.get("value", "")
                        if email:
                            contacts.append(Contact(name=name, email=email))

            return contacts[:limit]

        except Exception:
            # Graceful fallback - return empty list on error
            return []

    def get_frequent_contacts(self, limit: int = 10) -> list[Contact]:
        """Get frequently contacted people.

        Args:
            limit: Maximum number of results

        Returns:
            List of frequent contacts
        """
        try:
            service = self._get_service()

            # List connections (contacts)
            results = (
                service.people()
                .connections()
                .list(
                    resourceName="people/me",
                    pageSize=limit,
                    personFields="names,emailAddresses",
                    sortOrder="LAST_MODIFIED_DESCENDING",
                )
                .execute()
            )

            contacts = []
            for person in results.get("connections", []):
                emails = person.get("emailAddresses", [])
                names = person.get("names", [])

                if emails:
                    name = names[0].get("displayName", "") if names else ""
                    email = emails[0].get("value", "")
                    if email:
                        contacts.append(Contact(name=name, email=email))

            return contacts[:limit]

        except Exception:
            return []


# Global client instance
_contacts_client: Optional[ContactsClient] = None


def get_contacts_client() -> ContactsClient:
    """Get the global Contacts client instance."""
    global _contacts_client
    if _contacts_client is None:
        _contacts_client = ContactsClient()
    return _contacts_client
