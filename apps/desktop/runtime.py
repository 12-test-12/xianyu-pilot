import os
from pathlib import Path
from app.core.instance_lock import SingleInstance


def default_data_dir() -> Path:
    """Resolve only the explicit demo environment; never read the server .env."""
    configured = os.environ.get("XYA_DESKTOP_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "XianyuPilot" / "demo"


class InstanceLock(SingleInstance):
    """Compatibility wrapper for the historical demo's separate data folder."""
    def __init__(self, directory: Path):
        super().__init__(directory, filename="host.lock", description="演示服务")
