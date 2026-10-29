"""Portable runtime paths anchored to the program, never the working directory."""
from pathlib import Path
import sys


API_DIR = Path(__file__).resolve().parents[2]
SOURCE_ROOT = API_DIR.parent.parent if API_DIR.parent.name.casefold() == "apps" else API_DIR


def program_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return SOURCE_ROOT


def data_directory() -> Path:
    return program_root() / "data"
