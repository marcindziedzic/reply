# Email Assistant

A terminal-based (TUI) email client for Gmail with AI-powered response generation using Claude. Built with Python 3.11+ and the [Textual](https://textual.textualize.io/) framework.

![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

## Why Email Assistant?

Using AI for email today means copying threads into chat interfaces, losing context between sessions, and starting fresh every time. Email Assistant takes a different approach: it brings AI directly into your email workflow with persistent, local context that makes responses genuinely useful.

### Context That Persists

The biggest limitation with using Claude for email is losing context between sessions. Email Assistant solves this with a local context management system. You define knowledge about your business, clients, products, and communication preferences in markdown files that Claude references for every response. The AI actually "knows" your relationship history, pricing structures, and how you communicate—without you re-explaining it each time.

### Privacy by Design

All context stays on your machine. Sensitive business information—client details, pricing, internal processes—never needs to live in a third-party system. Teams can build rich context libraries without worrying about data leakage. Your knowledge base is yours.

### Tool Use at the Console

Claude isn't limited to text generation. Configure HTTP tools that let Claude fetch external data during response generation—check order status in your CRM, look up current pricing, verify inventory. The AI becomes an orchestrator that can pull live information into responses, not just write text in isolation.

### Templates + Intelligence

Templates alone are rigid; AI alone lacks consistency. Email Assistant combines them: snippets provide repeatable structure (greetings, signatures, standard responses), while Claude adapts the content intelligently based on context. You get the reliability of templates with the flexibility of AI.

### Team Sharing Without Forking

Teams share context, prompts, and snippets via a simple zip file hosted anywhere (S3, GitHub releases, company CDN). Team members download updates with a single command. No repository forks, no manual syncing—everyone stays aligned on communication standards while keeping the codebase clean.

## Who Is This For?

Email Assistant adapts to any role where email volume meets the need for consistent, informed responses.

### Sales Representatives

Context files contain product specs, pricing tiers, competitor comparisons, and objection handling guides. When a prospect asks about enterprise pricing, Claude pulls from your actual rate card. Configure a tool to check inventory or delivery estimates in real-time, so responses include accurate availability without tab-switching.

```yaml
# Example: Check product availability during response
tools:
  tools:
    - name: check_inventory
      type: http
      description: "Check product stock levels"
      endpoint: "https://api.warehouse.com/stock/{sku}"
```

### HR & Recruiting Teams

Maintain a `hiring_faq.md` with benefits, interview process, visa policies, and company culture. Every candidate gets consistent, accurate information. Add a calendar tool to check interviewer availability and propose times—Claude drafts the response and schedules the call in one step.

```yaml
# Example: Find available interview slots
tools:
  tools:
    - name: get_calendar_slots
      type: http
      description: "Get available slots for interviews"
      endpoint: "https://api.calendly.com/available-times"
      method: GET
      headers:
        Authorization: "Bearer ${CALENDLY_API_KEY}"
```

*"Hi Sarah, thanks for your application! Based on your experience, we'd love to move forward with a technical interview. I have openings on Tuesday at 2pm or Thursday at 10am—would either work for you? Our interview process typically takes 2-3 weeks, and yes, we do sponsor H1-B visas for the right candidates."*

All sourced from context files, availability checked via API, tone consistent with your employer brand.

### Product Owners & Project Managers

Context includes project timelines, sprint goals, stakeholder preferences, and decision logs. When a stakeholder asks for a status update, Claude knows the current sprint focus and recent blockers. A Jira tool can pull actual ticket status, so updates reflect reality rather than your memory of yesterday's standup.

### Customer Support Teams

Build a knowledge base in context files: troubleshooting guides, known issues, refund policies, escalation procedures. Every support rep gives the same accurate answer. Add tools to check order status, verify subscriptions, or create support tickets—Claude handles the lookup and drafts the response.

### Executives & Managers

Keep context light: communication preferences, direct reports, recurring meeting agendas. The value is in consistent delegation patterns and quick responses that maintain your voice. Snippets handle common responses ("Let's discuss in our 1:1", "Please loop in [name] for approval").

### Consultants & Agencies

Each client gets a context file: their industry, pain points, project history, key contacts. Switch between clients without mentally context-switching—Claude adapts tone and references appropriately. Snippets standardize proposals and status update formats while AI personalizes the content.

## Features

- **Gmail Integration** - View unread emails, threads, and attachments
- **AI-Powered Responses** - Generate contextual email responses using Claude
- **Snippet System** - Quick-insert reusable text templates
- **Reminder System** - Set follow-up reminders for email threads
- **Customizable Context** - Provide Claude with company-specific knowledge and tone guidelines
- **Team Sharing** - Share context, prompts, and snippets across your team without forking
- **Tool Integration** - Optional HTTP API tools for Claude to fetch external data
- **Keyboard-Driven** - Fast, efficient workflow with comprehensive keyboard shortcuts

## Screenshots

*Coming soon*

## Quick Start

### Prerequisites

- Python 3.11 or higher
- Gmail account with API access
- Claude API key from [Anthropic Console](https://console.anthropic.com/)

### Installation

```bash
# Clone the repository
git clone https://github.com/marcindziedzic/email-assistant.git
cd email-assistant

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -e .
```

### Setup

1. **Set up Gmail API credentials**
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Create a new project or select an existing one
   - Enable the Gmail API and Google People API
   - Create OAuth 2.0 credentials (Desktop application)
   - Download the credentials JSON file and save it as `credentials.json` in the project root

2. **Run the setup wizard**
   ```bash
   python run.py --configure
   ```
   This will prompt you for:
   - Claude API key
   - Claude Project ID (optional but recommended)
   - Path to Gmail credentials file

3. **Run the application**
   ```bash
   python run.py
   ```
   On first run, you'll be prompted to authorize Gmail access in your browser.

## Command Line Options

```bash
python run.py                    # Run the application
python run.py --configure        # Run setup wizard (create/update config.yaml)
python run.py --update-resources # Download shared resources from configured URL
python run.py --help             # Show help message
```

## Configuration

The `config.yaml` file contains all configuration options:

```yaml
claude:
  api_key: sk-ant-...           # Your Claude API key
  project_id: proj_...          # Optional: Claude Project ID
  model: claude-sonnet-4-20250514

gmail:
  credentials_file: credentials.json
  token_file: token.json
  max_threads: 50
  forwarding_addresses:         # Emails from these are treated as separate threads
    - noreply@formspree.io

shared_resources:               # Optional: Team shared resources
  url: "https://example.com/team-resources.zip"

user:
  variables:                    # Variables for email signatures
    name: "Your Name"
    company: "Your Company"
```

See `config.example.yaml` for all available options including tools configuration.

## Shared Resources (For Teams)

Teams can share context, prompts, and snippets without everyone forking the repository.

### How It Works

1. **Team admin** creates a zip file with shared resources
2. **Team members** configure the URL in their `config.yaml`
3. **Download** with `python run.py --update-resources`

### Zip File Structure

```
team-resources.zip
├── context/
│   ├── instructions.md      # AI instructions (required)
│   ├── tone_of_voice.md     # Writing style guidelines
│   └── required/
│       └── company_faq.md   # Always-included context
├── queries/
│   ├── response_system.txt  # Main response prompt
│   ├── new_message.txt      # New email prompt
│   └── ...                  # Other prompt templates
└── snippets/
    ├── Greetings/
    │   └── formal.md
    └── Closings/
        └── standard.md
```

### Precedence Rules

| Resource | Precedence | Notes |
|----------|------------|-------|
| **Context** | Local > Shared > Bundled | Users can override team context |
| **Queries** | Shared > Bundled | Team controls AI prompts |
| **Snippets** | (Local + Shared) or Bundled | Custom snippets void bundled samples |

- **Bundled defaults** (`.resources/`) - Built-in, works out of the box
- **Shared resources** (`.shared_resources/`) - Downloaded from team URL
- **Local overrides** (`context/`, `snippets/`) - User customizations

### Setting Up for Your Team

1. Create a zip file with the structure above
2. Host it on a web server (GitHub releases, S3, company CDN, etc.)
3. Share the URL with your team

Team members add to their `config.yaml`:
```yaml
shared_resources:
  url: "https://your-server.com/team-resources.zip"
```

Then run:
```bash
python run.py --update-resources
```

## Usage

### Keyboard Shortcuts

#### Thread List (Main Screen)
| Key | Action |
|-----|--------|
| `Enter` | Open selected thread |
| `r` | Refresh inbox |
| `q` | Quit application |
| `↑/↓` | Navigate threads |
| `Page Up/Down` | Scroll page |

#### Thread Detail
| Key | Action |
|-----|--------|
| `r` | Reply to thread |
| `n` | New email to sender |
| `a` | Archive thread |
| `d` | Delete thread |
| `p` | Set reminder (ping) |
| `s` | Download attachments |
| `Escape` | Back to list |

#### Draft Editor
| Key | Action |
|-----|--------|
| `/` | Open snippet picker |
| `Ctrl+Enter` | Send email |
| `Ctrl+G` | Generate AI response |
| `Ctrl+R` | Regenerate response |
| `Ctrl+E` | Extract thread essence |
| `Ctrl+Q` | Ask question about thread |
| `Escape` | Cancel/close |

### Context System

The `context/` directory contains files that provide Claude with knowledge for generating responses. Supports `.md`, `.json`, and `.csv` files.

```
context/
├── instructions.md      # Main AI instructions (always loaded)
├── tone_of_voice.md     # Communication style (always loaded)
├── required/            # Subdirectory for additional always-loaded files
│   ├── faq.md
│   └── company_info.md
└── optional/            # Subdirectory for large/selectable files
    ├── products.csv
    └── pricing.json
```

**How it works:**
- `instructions.md` and `tone_of_voice.md` in root are always loaded
- `required/` subdirectory - all files here are always included in prompts
- `optional/` subdirectory - files can be toggled per-response (useful for large data files)

### Snippets

The `snippets/` directory contains reusable text templates. Use subdirectories to organize snippets into categories:

```
snippets/
├── 1. Greetings/        # Subdirectories become categories
│   ├── formal.md
│   └── friendly.md
├── 2. Closings/
│   ├── formal.md
│   └── friendly.md
└── 3. Common Responses/
    └── acknowledgment.md
```

**Tips:**
- Prefix folders with numbers (e.g., `1. Greetings/`) to control sort order
- Press `/` in the draft editor to open the snippet picker
- Snippets are grouped by their parent folder in the picker

**Variable placeholders** (replaced automatically):
- `[name]` - Your name from config
- `[company]` - Your company from config
- `[phone]` - Your phone from config
- Any key from `user.variables` in config.yaml

## Development

### Project Structure

```
email-assistant/
├── src/email_assistant/
│   ├── main.py              # Entry point, setup wizard
│   ├── screens/             # Textual screens
│   │   ├── loading.py       # Initialization screen
│   │   ├── clients.py       # Thread list (main view)
│   │   ├── thread_detail.py # Email thread view
│   │   ├── draft.py         # Compose/edit screen
│   │   ├── reminders.py     # Reminder management
│   │   ├── dialogs.py       # Modal dialogs
│   │   └── widgets.py       # Reusable widgets
│   ├── services/
│   │   ├── gmail.py         # Gmail API client
│   │   ├── claude.py        # Claude API client
│   │   ├── contacts.py      # Google Contacts API
│   │   ├── context_service.py
│   │   ├── query_service.py
│   │   ├── snippet_service.py
│   │   ├── shared_resources_service.py
│   │   └── reminder_service.py
│   └── models/
│       └── email.py         # Data models
├── .resources/              # Bundled defaults (shipped with app)
│   ├── context/
│   ├── queries/
│   └── snippets/
├── context/                 # Local context overrides
├── snippets/                # Local snippets
├── config.example.yaml
├── run.py
└── pyproject.toml
```

### Running from Source

```bash
# Direct execution
python run.py

# Install in editable mode
pip install -e .
email-assistant
```

### Building Windows Executable

```bash
pip install pyinstaller
pyinstaller build.spec
```

The executable will be in `dist/`.

## Privacy & Security

- **Credentials are local** - OAuth tokens and API keys stay on your machine
- **No data collection** - The app doesn't phone home or collect analytics
- **Git-ignored secrets** - `config.yaml`, `credentials.json`, and `token.json` are in `.gitignore`

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

MIT License - see [LICENSE](LICENSE) for details.

## Acknowledgments

- [Textual](https://textual.textualize.io/) - Terminal UI framework
- [Anthropic](https://www.anthropic.com/) - Claude AI
- [Google APIs](https://developers.google.com/gmail/api) - Gmail integration
