"""Sample native connectivity without blocking the Qt event loop."""
from concurrent.futures import Future
import logging
import threading
import time

from app.portable.windows_events import network_connected


class NetworkMonitor:
    def __init__(self, probe=network_connected, interval=2):
        self.probe=probe
        self.interval=interval
        self.future=None
        self.next_check=0
        self.connected=None
        self.closed=False

    def poll(self):
        if self.closed:
            return self.connected
        if self.future is not None and self.future.done():
            try:
                self.connected=bool(self.future.result())
            except Exception:
                logging.getLogger(__name__).warning("Native connectivity check failed")
            self.future=None
            self.next_check=time.monotonic()+self.interval
        if self.future is None and time.monotonic()>=self.next_check:
            self.future=Future()
            # This read-only native call owns no Qt/SQLite resources. A stalled
            # Windows probe must not hold up either GUI shutdown or process exit.
            threading.Thread(target=self._probe,args=(self.future,),name="desktop-network",daemon=True).start()
        return self.connected

    def _probe(self,future):
        if not future.set_running_or_notify_cancel():
            return
        try:
            future.set_result(self.probe())
        except BaseException as exc:
            future.set_exception(exc)

    def close(self):
        self.closed=True
        if self.future is not None:
            self.future.cancel()
