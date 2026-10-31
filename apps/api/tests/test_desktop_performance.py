"""Regression coverage for work that must never block or flood the GUI loop."""
import asyncio
import threading
import time
from types import SimpleNamespace

import pytest

from app.portable.backend import DesktopBackend
from app.portable.network_monitor import NetworkMonitor
from app.services.delivery_gate import DeliveryGate


def test_slow_network_probe_never_blocks_poll_or_queues_duplicate_work():
    started, release = threading.Event(), threading.Event()
    calls = []

    def slow_probe():
        calls.append(1)
        started.set()
        release.wait(5)
        return True

    monitor = NetworkMonitor(probe=slow_probe, interval=60)
    try:
        assert monitor.poll() is None
        assert started.wait(2)
        future = monitor.future
        for _ in range(100):
            assert monitor.poll() is None
            assert monitor.future is future
        assert calls == [1]
        release.set()
        future.result(timeout=2)
        assert monitor.poll() is True
        assert monitor.future is None
        monitor.poll()
        assert calls == [1]
    finally:
        release.set()
        monitor.close()
    assert monitor.poll() is True


def test_failed_network_probe_preserves_last_known_state():
    monitor = NetworkMonitor(probe=lambda: True, interval=0)
    try:
        monitor.poll()
        monitor.future.result(timeout=2)
        assert monitor.poll() is True
        monitor.future.result(timeout=2)
        monitor.probe = lambda: (_ for _ in ()).throw(OSError("probe unavailable"))
        monitor.poll()
        try:
            monitor.future.result(timeout=2)
        except OSError:
            pass
        assert monitor.poll() is True
    finally:
        monitor.close()


@pytest.mark.asyncio
async def test_repeated_gui_ticks_share_an_inflight_resume():
    release = asyncio.Event()
    calls = []

    class Runtime:
        monitor = SimpleNamespace(gate=DeliveryGate())

        async def resume(self, reason, *, expected_revision):
            calls.append(reason)
            await release.wait()
            self.monitor.gate.clear(reason, expected_revision=expected_revision)

        async def desktop_status(self):
            return {"state": "offline"}

    backend = DesktopBackend(SimpleNamespace(), None, None, platform_runtime=Runtime())
    backend.app = SimpleNamespace(state=SimpleNamespace(ready=True))
    backend.loop = asyncio.get_running_loop()
    try:
        for _ in range(20):
            backend.poll()
            await asyncio.sleep(0)
        assert calls == ["host_starting"]
        backend.pause("manual")
        assert backend.poll()["state"] == "paused"
    finally:
        release.set()
        await asyncio.sleep(.01)


@pytest.mark.asyncio
async def test_status_polling_is_throttled_but_pause_is_immediate(monkeypatch):
    calls = []
    backend = DesktopBackend(SimpleNamespace(), None, None)
    backend.gate.clear("host_starting")
    backend.app = SimpleNamespace(state=SimpleNamespace(ready=True))
    backend.loop = asyncio.get_running_loop()
    clock = [time.monotonic()]
    monkeypatch.setattr("app.portable.backend.time", SimpleNamespace(monotonic=lambda: clock[0]))

    async def status():
        calls.append(1)
        return {"state": "offline"}

    backend._status = status
    for _ in range(20):
        backend.poll()
        await asyncio.sleep(0)
    assert len(calls) == 1
    backend.pause("manual")
    assert backend.poll()["state"] == "paused"
    clock[0] += 2
    backend.poll()
    await asyncio.sleep(.01)
    assert len(calls) == 2
