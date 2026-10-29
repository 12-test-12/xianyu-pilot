import os
from pathlib import Path


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


class InstanceLock:
    """OS-owned lock releases after a crash; a stale PID file is never trusted."""
    def __init__(self, directory: Path):
        self.path = directory / "host.lock"
        self.file = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                if self.path.stat().st_size == 0:
                    self.file.write(b"\0")
                    self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            raise RuntimeError("本数据目录已有演示服务运行，请使用原窗口或先停止它") from exc
        return self

    def __exit__(self, *_):
        if self.file:
            self.file.close()
