"""TUI-side watchdog: heartbeat, approval popup, inbox delivery."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from .state import (
    bridge_for_tui,
    clear_pending,
    disconnect_bridge,
    get_active_bridge,
    get_pending_request,
    pop_inbox,
    prepend_inbox,
    set_pending_decision,
    touch_tui_heartbeat,
)

logger = logging.getLogger(__name__)

_WATCHER_STARTED = False
_WATCHER_LOCK = threading.Lock()
_HANDLING_REQUEST = threading.Event()
_PROMPTED_SIDS: Dict[str, set[str]] = {}


def release_approval_prompt(request_id: str = "") -> None:
    _HANDLING_REQUEST.clear()
    key = (request_id or "").strip()
    if key:
        _prompted_sids.pop(key, None)
    else:
        _prompted_sids.clear()


def apply_tui_bridge() -> None:
    global _WATCHER_STARTED
    with _WATCHER_LOCK:
        if _WATCHER_STARTED:
            return
        try:
            import tui_gateway.server as gw  # noqa: F401
        except Exception:
            logger.debug("sys-controll: tui_gateway unavailable")
            return
        thread = threading.Thread(target=_watch_loop, name="sys-controll-tui", daemon=True)
        thread.start()
        _WATCHER_STARTED = True
        logger.info("sys-controll TUI bridge watcher started")


def _active_tui_sessions() -> List[tuple[str, Dict[str, Any]]]:
    try:
        import tui_gateway.server as gw

        return [
            (sid, sess)
            for sid, sess in list(gw._sessions.items())
            if isinstance(sess, dict) and not sess.get("_finalized")
        ]
    except Exception:
        return []


def _session_by_id(session_id: str) -> Optional[tuple[str, Dict[str, Any]]]:
    sid = (session_id or "").strip()
    if not sid:
        return None
    for item_sid, sess in _active_tui_sessions():
        if item_sid == sid:
            return item_sid, sess
    return None


def _primary_session() -> Optional[tuple[str, Dict[str, Any]]]:
    live = _active_tui_sessions()
    if not live:
        return None
    if len(live) == 1:
        return live[0]
    # Prefer the most recently active session.
    live.sort(key=lambda item: float(item[1].get("last_active") or item[1].get("created_at") or 0), reverse=True)
    return live[0]


def _session_title(session: Dict[str, Any], sid: str) -> str:
    title = str(session.get("pending_title") or "").strip()
    if title:
        return title
    try:
        import tui_gateway.server as gw

        key = str(session.get("session_key") or sid)
        db = gw._get_db()
        if db is not None:
            title = str(db.get_session_title(key) or "").strip()
            if title:
                return title
    except Exception:
        pass
    return f"TUI session {sid}"


def _watch_loop() -> None:
    while True:
        try:
            _tick()
        except Exception as exc:
            logger.debug("sys-controll watcher tick failed: %s", exc)
        time.sleep(2.0)


def _tick() -> None:
    live = _active_tui_sessions()
    if not live:
        active = get_active_bridge()
        if active:
            disconnect_bridge(tui_session_id=str(active.get("tui_session_id") or ""))
        return

    live_map = dict(live)
    primary = _primary_session()
    if primary:
        sid, session = primary
        session_key = str(session.get("session_key") or "")
        touch_tui_heartbeat(
            session_id=sid,
            session_key=session_key,
            session_title=_session_title(session, sid),
        )

    active = get_active_bridge()
    if active:
        linked_sid = str(active.get("tui_session_id") or "")
        if linked_sid in live_map:
            _deliver_inbox(linked_sid, live_map[linked_sid], active)
        else:
            disconnect_bridge(
                tui_session_id=linked_sid,
                gateway_session_key=str(active.get("gateway_session_key") or ""),
            )
        return

    pending = get_pending_request()
    if not pending or pending.get("tui_decision"):
        return
    request_id = str(pending.get("request_id") or "")
    primary = _primary_session()
    if not primary:
        return
    sid, session = primary
    _prompt_for_approval(sid, session, pending, request_id)


def _prompt_for_approval(
    sid: str,
    session: Dict[str, Any],
    pending: Dict[str, Any],
    request_id: str,
) -> None:
    if pending.get("tui_decision"):
        return
    prompted = _PROMPTED_SIDS.setdefault(request_id, set())
    if sid in prompted:
        return
    try:
        import tui_gateway.server as gw
        from .tui_overlay import remember_approval_context

        remember_approval_context(sid, session, pending)
        gw._emit(
            "sys_controll.request",
            sid,
            {
                "request_id": request_id,
                "chat_label": str(pending.get("chat_label") or pending.get("platform") or "external channel"),
                "platform": str(pending.get("platform") or "unknown"),
                "chat_id": str(pending.get("chat_id") or ""),
            },
        )
        prompted.add(sid)
        logger.info(
            "sys-controll approval picker opened on TUI %s for %s",
            sid,
            pending.get("chat_label") or pending.get("platform"),
        )
    except Exception as exc:
        logger.warning("sys-controll approval prompt failed for %s: %s", sid, exc)


def _deliver_inbox(sid: str, session: Dict[str, Any], active: Dict[str, Any]) -> None:
    messages = pop_inbox(limit=5)
    if not messages:
        return
    source_label = str(active.get("chat_label") or active.get("platform") or "external")
    for idx, item in enumerate(messages):
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        payload = f"[sys-controll · {source_label}]\n{text}"
        if _inject_prompt(sid, session, payload):
            continue
        for rest in reversed(messages[idx:]):
            rest_text = str(rest.get("text") or "").strip()
            if rest_text:
                prepend_inbox(
                    rest_text,
                    source=str(rest.get("source") or "requeued"),
                )
        try:
            import tui_gateway.server as gw

            gw._emit(
                "status.update",
                sid,
                {
                    "kind": "info",
                    "text": "sys-controll: message(s) queued — will deliver when the agent is idle.",
                },
            )
        except Exception:
            pass
        break


def _inject_prompt(sid: str, session: Dict[str, Any], text: str) -> bool:
    """Inject into TUI session. Returns False if agent is busy (caller should re-queue)."""
    try:
        import tui_gateway.server as gw

        with session["history_lock"]:
            if session.get("running"):
                return False
            session["running"] = True
            session["last_active"] = time.time()
            gw._start_inflight_turn(session, text)
        rid = f"sysctrl_{uuid.uuid4().hex[:8]}"
        gw._start_agent_build(sid, session)

        def _run() -> None:
            err = gw._wait_agent(session, rid)
            if err:
                with session["history_lock"]:
                    session["running"] = False
                    gw._clear_inflight_turn(session)
                return
            gw._run_prompt_submit(rid, sid, session, text)

        threading.Thread(target=_run, daemon=True).start()
        return True
    except Exception as exc:
        logger.warning("sys-controll inbox inject failed: %s", exc)
        try:
            with session["history_lock"]:
                session["running"] = False
        except Exception:
            pass
        return False
