"""PyInstaller runs user hooks before Qt's bundled runtime hooks."""
import sys
from app.portable.bootstrap import configure_environment
from app.core.portable_runtime import startup_error
try:
    configure_environment(software_rendering="--software-rendering" in sys.argv or "--webengine-check" in sys.argv)
except (OSError,ValueError) as exc:
    startup_error(exc)

