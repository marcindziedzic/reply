#!/usr/bin/env python3
"""Run Email Assistant without installation."""

import argparse
import sys
from pathlib import Path

# Add src directory to Python path
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))


def print_help():
    """Print help message."""
    help_text = """
Email Assistant - AI-powered email client for Gmail

Usage:
    python run.py                   Run the application
    python run.py --configure       Run setup wizard (create/update config.yaml)
    python run.py --update-resources  Download shared resources from configured URL
    python run.py --export-resources [PATH]
                                    Pack resources into a zip (default: exports/)
    python run.py --help            Show this help message

Setup (first time):
    1. python run.py --configure    Create config.yaml with API keys
    2. python run.py                Start the application

Shared Resources (for teams):
    Configure shared_resources.url in config.yaml, then run:
    python run.py --update-resources

    The zip file should contain:
    - context/      AI context files (instructions, tone of voice)
    - queries/      Prompt templates
    - snippets/     Reusable text snippets

Editing shared resources:
    1. Edit files in .shared_resources/ (or local context/, snippets/)
    2. python run.py --export-resources
    3. Upload the zip from exports/ to the shared_resources.url location

    The export merges .shared_resources/ with local context/ and snippets/
    (local files win). Files listed under 'downloads' in config.yaml are skipped.
    Note: --update-resources replaces .shared_resources/, so export first.

For more information, see README.md
"""
    print(help_text)


def run_configure():
    """Run the setup wizard."""
    from email_assistant.main import run_setup_wizard
    success = run_setup_wizard()
    return 0 if success else 1


def run_update_resources():
    """Download/update shared resources."""
    from email_assistant.config import config_exists, get_config

    if not config_exists():
        print("Error: config.yaml not found.")
        print("Run 'python run.py --configure' first to create configuration.")
        return 1

    config = get_config()

    # Check if shared_resources.url is configured
    if not hasattr(config, 'shared_resources') or not config.shared_resources.url:
        print("Error: No shared_resources.url configured in config.yaml")
        print()
        print("Add to your config.yaml:")
        print()
        print("shared_resources:")
        print('  url: "https://example.com/team-resources.zip"')
        return 1

    url = config.shared_resources.url
    print(f"Updating shared resources from: {url}")
    print()

    from email_assistant.services.shared_resources_service import get_shared_resources_service

    service = get_shared_resources_service()
    try:
        service.download_and_extract(url)
        print()
        print("Shared resources updated successfully!")
        return 0
    except Exception as e:
        print(f"Error: {e}")
        return 1


def run_export_resources(output: str) -> int:
    """Pack shared resources and local overrides into a zip file."""
    from datetime import datetime

    from email_assistant.config import config_exists, get_config
    from email_assistant.services.shared_resources_service import get_shared_resources_service

    service = get_shared_resources_service()

    # Default: exports/resources-<timestamp>.zip in the project root
    default_name = f"resources-{datetime.now():%Y-%m-%d_%H%M%S}.zip"
    if not output:
        output_path = service.project_root / "exports" / default_name
    else:
        output_path = Path(output)
        if output_path.is_dir() or output.endswith(("/", "\\")):
            output_path = output_path / default_name
        elif output_path.suffix.lower() != ".zip":
            output_path = output_path.with_name(output_path.name + ".zip")

    # Skip files downloaded at startup (config 'downloads') - they have their own source
    exclude = []
    if config_exists():
        for item in get_config().downloads.items:
            target = Path(item.target)
            exclude.append(target if target.is_absolute() else Path.cwd() / target)

    print(f"Exporting resources to: {output_path}")
    print()

    try:
        result = service.export_to_zip(output_path, exclude=exclude)
    except Exception as e:
        print(f"Error: {e}")
        return 1

    for directory in service.RESOURCE_DIRS:
        total = result.count(directory)
        local = result.count(directory, "local")
        note = f" ({local} from local {directory}/)" if local else ""
        print(f"  {directory + ':':<10} {total} files{note}")

    if result.skipped:
        print()
        print("Skipped (downloaded at startup, see 'downloads' in config.yaml):")
        for name in result.skipped:
            print(f"  - {name}")

    size_kb = result.output_path.stat().st_size / 1024
    print()
    print(f"Done: {result.output_path} ({size_kb:.1f} KB)")
    print("Upload this file to the shared_resources.url location to share it with the team.")
    return 0


def run_app():
    """Run the main application."""
    from email_assistant.config import config_exists, get_config

    if not config_exists():
        print("Error: config.yaml not found.")
        print()
        print("Run 'python run.py --configure' to set up the application.")
        return 1

    config = get_config()
    if not config.is_valid():
        print("Error: Incomplete configuration in config.yaml")
        print("Required fields: claude.api_key, claude.project_id")
        print()
        print("Run 'python run.py --configure' to update configuration.")
        return 1

    # Import and run the app
    try:
        from email_assistant.app import EmailAssistantApp

        app = EmailAssistantApp()
        app.run()
        return 0

    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
        return 0

    except Exception as e:
        print(f"\nError: {e}")
        return 1


def main() -> int:
    """Main entry point with argument parsing."""
    parser = argparse.ArgumentParser(
        description="Email Assistant - AI-powered email client for Gmail",
        add_help=False  # We'll handle --help ourselves
    )
    parser.add_argument(
        "--configure",
        action="store_true",
        help="Run setup wizard to create/update config.yaml"
    )
    parser.add_argument(
        "--update-resources",
        action="store_true",
        help="Download shared resources from configured URL"
    )
    parser.add_argument(
        "--export-resources",
        nargs="?",
        const="",
        default=None,
        metavar="PATH",
        help="Pack shared resources and local overrides into a zip"
    )
    parser.add_argument(
        "--help", "-h",
        action="store_true",
        help="Show help message"
    )

    args = parser.parse_args()

    if args.help:
        print_help()
        return 0

    if args.configure:
        return run_configure()

    if args.update_resources:
        return run_update_resources()

    if args.export_resources is not None:
        return run_export_resources(args.export_resources)

    # Default: run the app
    return run_app()


if __name__ == "__main__":
    sys.exit(main())
