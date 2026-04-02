"""XeisWorks Studio application entry point."""
import sys


def main() -> None:
    from xw_studio.app import create_application
    app = create_application()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
