"""Shared sys-controll bridge state (gateway + TUI processes)."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional


def _load_platform_util():
    root = Path(__file__).resolve().parent
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        f"_{root.name}_plugin_bootstrap",
        root / "plugin_bootstrap.py",
    )
    assert spec and spec.loader
    bootstrap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bootstrap)
    return bootstrap.load_vendored("platform_util", plugin_root=root)


_xplat = _load_platform_util()

STATE_DIR = Path.home() / ".hermes" / "sys-controll"
STATE_FILE = STATE_DIR / "state.json"
LOCK_FILE = STATE_DIR / "state.lock"
HEARTBEAT_STALE_SECONDS = 20
REQUEST_TIMEOUT_SECONDS = 300

_lock = threading.Lock()


@contextmanager
def _file_lock() -> Iterator[None]:
    """Cross-process exclusive lock (gateway + TUI share state.json)."""
    with _xplat.file_lock(LOCK_FILE):
        yield


def _empty_state() -> Dict[str, Any]:
    return {"tui": {}, "pending": None, "active": None, "inbox": [], "outbox": []}


def _read_unlocked() -> Dict[str, Any]:
    if not STATE_FILE.is_file():
        return _empty_state()
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return _empty_state()
        data.setdefault("tui", {})
        data.setdefault("inbox", [])
        data.setdefault("outbox", [])
        return data
    except Exception:
        return _empty_state()


def _write_unlocked(data: Dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, STATE_FILE)


def read_state() -> Dict[str, Any]:
    with _lock, _file_lock():
        return _read_unlocked()


def write_state(data: Dict[str, Any]) -> None:
    with _lock, _file_lock():
        _write_unlocked(data)


def update_state(mutator) -> Dict[str, Any]:
    with _lock, _file_lock():
        data = _read_unlocked()
        mutator(data)
        _write_unlocked(data)
        return data


def tui_is_active(max_age: float = HEARTBEAT_STALE_SECONDS) -> bool:
    tui = read_state().get("tui") or {}
    if not isinstance(tui, dict):
        return False
    try:
        last = float(tui.get("last_heartbeat") or 0)
    except (TypeError, ValueError):
        return False
    return bool(tui.get("session_id")) and (time.time() - last) <= max_age


def touch_tui_heartbeat(*, session_id: str, session_key: str = "", session_title: str = "") -> None:
    now = time.time()

    def _mut(data: Dict[str, Any]) -> None:
        data["tui"] = {
            "session_id": session_id,
            "session_key": session_key,
            "session_title": session_title,
            "pid": os.getpid(),
            "last_heartbeat": now,
        }

    update_state(_mut)


def clear_tui_heartbeat(session_id: str = "") -> None:
    def _mut(data: Dict[str, Any]) -> None:
        tui = data.get("tui")
        if not isinstance(tui, dict):
            return
        if session_id and str(tui.get("session_id") or "") != session_id:
            return
        data["tui"] = {}

    update_state(_mut)


def create_pending_request(*, gateway_session_key: str, gateway_session_id: str, platform: str, chat_id: str, chat_label: str) -> str:
    request_id = uuid.uuid4().hex[:12]
    now = time.time()

    def _mut(data: Dict[str, Any]) -> None:
        data["pending"] = {
            "request_id": request_id,
            "gateway_session_key": gateway_session_key,
            "gateway_session_id": gateway_session_id,
            "platform": platform,
            "chat_id": chat_id,
            "chat_label": chat_label,
            "external_confirmed": True,
            "tui_decision": None,
            "created_at": now,
            "expires_at": now + REQUEST_TIMEOUT_SECONDS,
        }

    update_state(_mut)
    return request_id


def set_pending_decision(request_id: str, decision: str) -> bool:
    changed = False

    def _mut(data: Dict[str, Any]) -> None:
        nonlocal changed
        pending = data.get("pending")
        if not isinstance(pending, dict):
            return
        if str(pending.get("request_id") or "") != request_id:
            return
        pending["tui_decision"] = decision
        changed = True

    update_state(_mut)
    return changed


def get_pending_request() -> Optional[Dict[str, Any]]:
    pending = read_state().get("pending")
    if not isinstance(pending, dict):
        return None
    try:
        expires = float(pending.get("expires_at") or 0)
    except (TypeError, ValueError):
        expires = 0
    if expires and time.time() > expires:
        clear_pending("expired")
        return None
    return pending


def clear_pending(reason: str = "") -> None:
    def _mut(data: Dict[str, Any]) -> None:
        data["pending"] = None

    update_state(_mut)


def _invalidate_tool_cache() -> None:
    try:
        from tools.registry import invalidate_check_fn_cache

        invalidate_check_fn_cache()
    except Exception:
        pass


def activate_bridge(pending: Dict[str, Any], tui_session_id: str, tui_session_key: str = "") -> str:
    bridge_id = uuid.uuid4().hex[:12]
    now = time.time()
    activated = ""

    def _mut(data: Dict[str, Any]) -> None:
        nonlocal activated
        if isinstance(data.get("active"), dict):
            return
        current_pending = data.get("pending")
        if not isinstance(current_pending, dict):
            return
        if str(current_pending.get("request_id") or "") != str(pending.get("request_id") or ""):
            return
        data["active"] = {
            "bridge_id": bridge_id,
            "gateway_session_key": pending.get("gateway_session_key", ""),
            "gateway_session_id": pending.get("gateway_session_id", ""),
            "platform": pending.get("platform", ""),
            "chat_id": pending.get("chat_id", ""),
            "chat_label": pending.get("chat_label", ""),
            "tui_session_id": tui_session_id,
            "tui_session_key": tui_session_key,
            "connected_at": now,
        }
        data["pending"] = None
        data["inbox"] = []
        data["outbox"] = []
        activated = bridge_id

    update_state(_mut)
    if activated:
        _invalidate_tool_cache()
    return activated


def disconnect_bridge(*, gateway_session_key: str = "", gateway_session_id: str = "", tui_session_id: str = "") -> bool:
    removed = False

    def _mut(data: Dict[str, Any]) -> None:
        nonlocal removed
        active = data.get("active")
        if not isinstance(active, dict):
            return
        if gateway_session_key and active.get("gateway_session_key") != gateway_session_key:
            return
        if gateway_session_id and active.get("gateway_session_id") != gateway_session_id:
            return
        if tui_session_id and active.get("tui_session_id") != tui_session_id:
            return
        data["active"] = None
        data["inbox"] = []
        data["outbox"] = []
        data["pending"] = None
        removed = True

    update_state(_mut)
    if removed:
        _invalidate_tool_cache()
    return removed


def get_active_bridge() -> Optional[Dict[str, Any]]:
    active = read_state().get("active")
    return active if isinstance(active, dict) else None


def bridge_for_gateway(gateway_session_key: str) -> Optional[Dict[str, Any]]:
    active = get_active_bridge()
    if not active:
        return None
    if active.get("gateway_session_key") == gateway_session_key:
        return active
    return None


def bridge_for_tui(tui_session_id: str) -> Optional[Dict[str, Any]]:
    active = get_active_bridge()
    if not active:
        return None
    if active.get("tui_session_id") == tui_session_id:
        return active
    return None


def enqueue_inbox(message: str, *, source: str = "") -> bool:
    text = (message or "").strip()
    if not text:
        return False

    def _mut(data: Dict[str, Any]) -> None:
        if not isinstance(data.get("active"), dict):
            return
        inbox = data.setdefault("inbox", [])
        if not isinstance(inbox, list):
            inbox = []
            data["inbox"] = inbox
        inbox.append({"id": uuid.uuid4().hex[:10], "text": text, "source": source, "ts": time.time()})

    update_state(_mut)
    return bool(get_active_bridge())


def prepend_inbox(message: str, *, source: str = "") -> bool:
    """Re-queue a message at the front of the inbox (e.g. while TUI agent is busy)."""
    text = (message or "").strip()
    if not text:
        return False

    def _mut(data: Dict[str, Any]) -> None:
        if not isinstance(data.get("active"), dict):
            return
        inbox = data.setdefault("inbox", [])
        if not isinstance(inbox, list):
            inbox = []
            data["inbox"] = inbox
        inbox.insert(
            0,
            {"id": uuid.uuid4().hex[:10], "text": text, "source": source, "ts": time.time()},
        )

    update_state(_mut)
    return bool(get_active_bridge())


def pop_inbox(limit: int = 10) -> List[Dict[str, Any]]:
    popped: List[Dict[str, Any]] = []

    def _mut(data: Dict[str, Any]) -> None:
        inbox = data.get("inbox")
        if not isinstance(inbox, list) or not inbox:
            return
        batch = inbox[:limit]
        data["inbox"] = inbox[limit:]
        popped.extend(batch)

    update_state(_mut)
    return popped
