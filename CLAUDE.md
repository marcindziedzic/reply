# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Email Assistant is a terminal-based (TUI) email client for Gmail with AI-powered response generation using Claude. Built with Python 3.11+ and the Textual framework.

## Commands

```bash
# Setup
python run.py --configure        # Run setup wizard (create config.yaml)
python run.py --update-resources # Download team shared resources
python run.py --help             # Show help

# Run
python run.py                    # Run directly
pip install -e .                 # Install in editable mode
email-assistant                  # Run installed version

# Build Windows executable
pyinstaller build.spec
```

No test suite or linter configured.

## Architecture

### Entry Flow
`run.py` (CLI parsing) → `main.py` → `EmailAssistantApp` → `LoadingScreen` → `ClientsScreen`

- `--configure` → runs setup wizard
- `--update-resources` → downloads shared resources from URL
- No args → runs app (requires config.yaml)

### Global Singleton Clients
All major services use the singleton pattern with `get_*_client()` functions:
- `gmail.py` - `GmailClient` for Gmail API operations
- `claude.py` - `ClaudeClient` for AI response generation
- `contacts.py` - `ContactsClient` for Google Contacts API

### Screen Architecture (Textual)
Screens in `src/email_assistant/screens/`:
- `loading.py` - Initialization with progress indicators
- `clients.py` - Main view: unread email threads list
- `thread_detail.py` - Full email thread with history
- `draft.py` - Compose/edit responses with AI generation
- `reminders.py` - Follow-up reminder management

Screens use lazy loading - heavy imports deferred until screen is opened.

### Data Models
`src/email_assistant/models/email.py` contains dataclasses:
- `Thread` - Email conversation (contains Messages)
- `Message` - Individual email
- `Attachment` - File attachment metadata
- `Label` - Gmail label

### Services Layer
`src/email_assistant/services/`:
- `email_parser.py` - Parse email content (HTML/plain text)
- `context_service.py` - AI context files (instructions, tone of voice)
- `query_service.py` - AI prompt templates
- `snippet_service.py` - Reusable text templates
- `shared_resources_service.py` - Download team resources from URL
- `reminder_service.py` - Email follow-up reminders with JSON persistence

### Resource Directories

```
.resources/              # Bundled defaults (shipped with app)
├── context/             # Default AI context
├── queries/             # Default prompt templates
└── snippets/            # Sample snippets

.shared_resources/       # Downloaded team resources (gitignored)
├── context/
├── queries/
└── snippets/

context/                 # Local overrides (optional, user creates)
snippets/                # Local snippets (optional, user creates)
```

**Precedence:**
- Context: Local > Shared > Bundled
- Queries: Shared > Bundled (no local override - team controls prompts)
- Snippets: (Local + Shared) or Bundled (custom snippets void bundled samples)

## Configuration

YAML config at `config.yaml` (see `config.example.yaml`):
- `claude.api_key`, `claude.project_id`, `claude.model`
- `gmail.credentials_file` (OAuth from Google Cloud Console)
- `gmail.forwarding_addresses` - Form submission addresses (treated as separate threads)
- `shared_resources.url` - URL to team resources zip file
- `user.variables` - Custom placeholders for signatures (name, title, phone, etc.)

Setup wizard runs via `python run.py --configure`.

## Key Patterns

- Variable substitution: User variables from config injected into signatures
- Forwarded emails: Special handling for form submission addresses - not grouped into threads
- AI context: Full email thread history sent to Claude for response generation
- Snippets: Markdown files accessed with `/` in draft editor
- Team sharing: Teams share context/queries/snippets via zip URL without forking
