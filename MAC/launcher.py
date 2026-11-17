"""macOS entry point; both architectures use the maintained client source."""
from pathlib import Path
import sys

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "client_source"))

from app import main

if __name__ == "__main__":
    main()
