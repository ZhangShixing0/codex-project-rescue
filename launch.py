"""Source launcher; the packaged executable uses the same entry point."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from codex_rescue.gui import main

if __name__ == "__main__":
    main()
