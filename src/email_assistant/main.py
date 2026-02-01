"""Entry point for Email Assistant."""

import sys

from .config import Config, get_config_path


def run_setup_wizard() -> bool:
    """
    Run first-time setup wizard.

    Returns:
        True if setup completed successfully, False otherwise.
    """
    print("\n" + "=" * 60)
    print("  Email Assistant - Setup Wizard")
    print("=" * 60 + "\n")

    config = Config()

    # Claude API key
    print("1. Claude API Configuration")
    print("-" * 40)
    api_key = input("   Enter Claude API key (sk-ant-...): ").strip()
    if not api_key:
        print("   [ERROR] API key is required!")
        return False
    config.claude.api_key = api_key

    # Claude Project ID
    project_id = input("   Enter Claude Project ID (proj_...): ").strip()
    if not project_id:
        print("   [NOTE] No Project ID provided - will work without project.")
    config.claude.project_id = project_id

    print()

    # Gmail credentials
    print("2. Gmail Configuration")
    print("-" * 40)

    default_creds = "credentials.json"
    creds_input = input(f"   Path to credentials.json [{default_creds}]: ").strip()
    if creds_input:
        config.gmail.credentials_file = creds_input

    # Check if credentials file exists
    creds_path = config.get_credentials_path()
    if not creds_path.exists():
        print(f"\n   [NOTE] File {creds_path} does not exist!")
        print("   Download OAuth credentials from Google Cloud Console:")
        print("   1. Go to https://console.cloud.google.com/apis/credentials")
        print("   2. Create a project or select existing one")
        print("   3. Create OAuth Client ID (Desktop app)")
        print("   4. Download JSON and save as credentials.json")
        print()
        input("   Press Enter when file is ready...")

        if not creds_path.exists():
            print(f"   [ERROR] File {creds_path} still not found")
            return False

    print()

    # Save config
    print("3. Saving Configuration")
    print("-" * 40)

    try:
        config.save()
        print(f"   Saved: {get_config_path()}")
    except Exception as e:
        print(f"   [ERROR] Failed to save: {e}")
        return False

    print()
    print("=" * 60)
    print("  Configuration complete!")
    print()
    print("  Next steps:")
    print("  - Run 'python run.py' to start the application")
    print("  - On first run you will be prompted to sign in to Gmail")
    print()
    print("  For teams using shared resources:")
    print("  - Add shared_resources.url to config.yaml")
    print("  - Run 'python run.py --update-resources'")
    print("=" * 60 + "\n")

    return True


def main() -> int:
    """Main entry point - runs the app directly."""
    from .config import config_exists, get_config

    if not config_exists():
        print("Error: config.yaml not found.")
        print("Run 'python run.py --configure' to set up the application.")
        return 1

    config = get_config()
    if not config.is_valid():
        print("Error: Incomplete configuration in config.yaml")
        print("Run 'python run.py --configure' to update configuration.")
        return 1

    try:
        from .app import EmailAssistantApp

        app = EmailAssistantApp()
        app.run()
        return 0

    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
        return 0

    except Exception as e:
        print(f"\n[ERROR] {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
