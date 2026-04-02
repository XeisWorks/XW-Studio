"""Compile Qt .qrc resource file to Python module."""
import subprocess
import sys
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    qrc = root / "resources" / "resources.qrc"
    out = root / "resources" / "resources_rc.py"

    if not qrc.exists():
        print(f"Resource file not found: {qrc}")
        sys.exit(1)

    subprocess.run(
        ["pyside6-rcc", str(qrc), "-o", str(out)],
        check=True,
    )
    print(f"Compiled {qrc} -> {out}")


if __name__ == "__main__":
    main()
