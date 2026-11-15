"""Root Streamlit Cloud entry point for the Lebanon Gasoline 95 Monitor."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lebanon_fuel.dashboard.app import main

if __name__ == "__main__":
    main()
