"""Regression tests for Render/TiDB resilience without live database access."""
import ast
from pathlib import Path
import sys
import types

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _function(relative_path, name, namespace):
    path = ROOT / relative_path
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    node = next(
        n for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == name
    )
    node.decorator_list = []
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[name]


class _EndWorker(Exception):
    pass


class _Clock:
    def __init__(self):
        self.now = 0.0

    def sleep(self, duration):
        self.now += duration

    def monotonic(self):
        return self.now


class _Event:
    def __init__(self, clock, max_waits, *, dirty=False):
        self.clock = clock
        self.max_waits = max_waits
        self.waits = 0
        self.dirty = dirty

    def wait(self, timeout):
        self.waits += 1
        if self.waits > self.max_waits:
            raise _EndWorker()
        if not self.dirty:
            self.clock.sleep(timeout)

    def is_set(self):
        return self.dirty

    def clear(self):
        self.dirty = False

    def set(self):
        self.dirty = True


def test_background_does_not_reread_unchanged_divergent_standby(monkeypatch):
    clock = _Clock()
    event = _Event(clock, max_waits=1)
    calls = []
    verifier = types.ModuleType("services.order_sync_integrity")
    verifier.verify_once = lambda: {"verified": False}
    monkeypatch.setitem(sys.modules, verifier.__name__, verifier)
    ns = {
        "time": clock,
        "cloud_mirror_dirty_event": lambda: event,
        "_mirror_version": lambda target: 22 if target == "TIDB1" else 21,
        "reconcile_once": lambda: calls.append(clock.now),
    }
    worker = _function("services/order_tidb_cloud_reconcile.py", "_worker", ns)
    with pytest.raises(_EndWorker):
        worker()
    # The source and standby versions are different, but a successful scan
    # cannot delete preserved standby-only records. A timer alone is no reason
    # to repeat that expensive scan.
    assert len(calls) == 1


def test_timeout_retry_uses_exponential_backoff(monkeypatch):
    clock = _Clock()
    event = _Event(clock, max_waits=36)
    calls = []

    def fail():
        calls.append(clock.now)
        raise TimeoutError("TiDB read timed out")

    ns = {
        "time": clock,
        "cloud_mirror_dirty_event": lambda: event,
        "reconcile_once": fail,
        "_mirror_version": lambda target: 1,
    }
    worker = _function("services/order_tidb_cloud_reconcile.py", "_worker", ns)
    with pytest.raises(_EndWorker):
        worker()
    assert len(calls) >= 3
    assert calls[1] - calls[0] >= 300
    assert calls[2] - calls[1] >= 600


def test_mobile_head_uses_fast_share_interceptor(monkeypatch):
    fast = types.ModuleType("services.order_public_share_fast")
    fast._filter_space = lambda space, share: None
    monkeypatch.setitem(sys.modules, fast.__name__, fast)
    ns = {
        "request": types.SimpleNamespace(method="HEAD", path="/share/m1_testtoken"),
        "_load_page_data": lambda token: (None, None, "SHARE_NOT_FOUND"),
    }
    route = _function(
        "services/order_public_share_multi_b2_page.py",
        "_order_public_share_multi_b2_page",
        ns,
    )
    assert route() == "SHARE_NOT_FOUND"
