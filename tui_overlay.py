"""ModelPicker-style sys-controll approval overlay for the Hermes TUI."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict

from .state import (
    activate_bridge,
    clear_pending,
    get_pending_request,
    set_pending_decision,
)
from . import tui_bridge

logger = logging.getLogger(__name__)

_PATCHED = False
_TUI_CUSTOM = Path.home() / ".hermes" / "tui-custom"
_PATCHED_ENTRY = _TUI_CUSTOM / "dist" / "entry.js"
_MARKER = "/* hermes-sys-controll-patch */"

# Session context while the approval picker is open (sid -> {session, pending}).
_APPROVAL_CTX: Dict[str, Dict[str, Any]] = {}


def reapply_entry_js_if_needed() -> None:
    """Re-apply sys-controll JS after hermes-essentials rebuilds entry.js."""
    if not _PATCHED_ENTRY.is_file():
        return
    try:
        text = _PATCHED_ENTRY.read_text(encoding="utf-8")
    except OSError:
        return
    if _MARKER in text:
        return
    logger.info("sys-controll: re-applying TUI overlay patch after entry.js rebuild")
    _patch_entry_js()


def apply_tui_overlay() -> None:
    global _PATCHED
    os.environ.setdefault("HERMES_TUI_DIR", str(_TUI_CUSTOM))
    _wrap_list_picker_rpc()
    needs_js_patch = (
        not _PATCHED_ENTRY.is_file()
        or _MARKER not in _PATCHED_ENTRY.read_text(encoding="utf-8")
    )
    if needs_js_patch:
        _patch_entry_js()
    _PATCHED = True
    logger.info("sys-controll TUI overlay applied")


def remember_approval_context(sid: str, session: dict, pending: dict) -> None:
    _APPROVAL_CTX[sid] = {"session": session, "pending": dict(pending)}


def clear_approval_context(sid: str = "") -> None:
    if sid:
        _APPROVAL_CTX.pop(sid, None)
    else:
        _APPROVAL_CTX.clear()


def _wrap_list_picker_rpc() -> None:
    try:
        import tui_gateway.server as gw
    except Exception:
        logger.debug("sys-controll: tui_gateway unavailable for picker wrap")
        return
    if getattr(gw, "_sys_controll_picker_patched", False):
        return
    orig_options = gw._methods.get("hermes.list_picker.options")
    orig_select = gw._methods.get("hermes.list_picker.select")
    if not orig_options or not orig_select:
        try:
            from hermes_plugins.hermes_essentials.tts.tui_list_picker import _register_gateway_methods

            _register_gateway_methods()
            orig_options = gw._methods.get("hermes.list_picker.options")
            orig_select = gw._methods.get("hermes.list_picker.select")
        except Exception as exc:
            logger.debug("sys-controll: could not bootstrap list picker RPC: %s", exc)
    if not orig_options or not orig_select:
        logger.warning("sys-controll: hermes.list_picker RPC missing; overlay inactive")
        return

    def options(rid, params: dict):
        if str(params.get("kind") or "").strip() == "sys_controll":
            return _rpc_options(rid, params)
        return orig_options(rid, params)

    def select(rid, params: dict):
        if str(params.get("kind") or "").strip() == "sys_controll":
            return _rpc_select(rid, params)
        return orig_select(rid, params)

    gw._methods["hermes.list_picker.options"] = options
    gw._methods["hermes.list_picker.select"] = select
    gw._sys_controll_picker_patched = True


def _extra_request_id(params: dict) -> str:
    extra = params.get("extra")
    if isinstance(extra, dict):
        return str(extra.get("request_id") or "").strip()
    return ""


def _rpc_options(rid, params: dict) -> dict:
    from tui_gateway.server import _err, _ok

    request_id = _extra_request_id(params)
    pending = get_pending_request()
    if not pending or str(pending.get("request_id") or "") != request_id:
        return _ok(
            rid,
            {
                "title": "System Control",
                "hint": "No pending request (expired or already handled)",
                "items": [{"value": "__cancel__", "label": "Close", "meta": ""}],
                "selected": 0,
            },
        )
    chat_label = str(pending.get("chat_label") or pending.get("platform") or "external channel")
    platform = str(pending.get("platform") or "unknown")
    chat_id = str(pending.get("chat_id") or "?")
    return _ok(
        rid,
        {
            "title": "System Control Request",
            "hint": (
                f"Channel: {platform} · {chat_label} · "
                "bridge ends when either session resets"
            ),
            "items": [
                {
                    "value": "accept",
                    "label": "Accept — grant system control",
                    "meta": f"chat {chat_id}",
                },
                {
                    "value": "deny",
                    "label": "Deny — refuse request",
                    "meta": "external session stays separate",
                },
                {"value": "__cancel__", "label": "Cancel", "meta": ""},
            ],
            "selected": 1,
        },
    )


def _rpc_select(rid, params: dict) -> dict:
    from tui_gateway.server import _err, _ok

    sid = str(params.get("session_id") or "").strip()
    value = str(params.get("value") or "").strip().lower()
    request_id = _extra_request_id(params)
    try:
        pending = get_pending_request()
        if not pending or str(pending.get("request_id") or "") != request_id:
            clear_approval_context(sid)
            tui_bridge.release_approval_prompt(request_id)
            return _ok(rid, {"message": "System control request expired or already handled."})

        ctx = _APPROVAL_CTX.pop(sid, None)
        session = (ctx or {}).get("session") if isinstance(ctx, dict) else None

        if value in {"__cancel__", "deny", ""}:
            set_pending_decision(request_id, "deny")
            clear_pending("denied")
            tui_bridge.release_approval_prompt(request_id)
            label = str(pending.get("chat_label") or pending.get("platform") or "external")
            return _ok(rid, {"message": f"System control denied for {label}."})

        if value != "accept":
            tui_bridge.release_approval_prompt(request_id)
            return _err(rid, 4002, f"unknown choice: {value!r}")

        set_pending_decision(request_id, "accept")
        session_key = ""
        if isinstance(session, dict):
            session_key = str(session.get("session_key") or "")
        bridge_id = activate_bridge(pending, sid, session_key)
        tui_bridge.release_approval_prompt(request_id)
        label = str(pending.get("chat_label") or pending.get("platform") or "external")
        if not bridge_id:
            return _ok(
                rid,
                {"message": f"System control request already handled on another TUI session."},
            )
        return _ok(
            rid,
            {
                "message": (
                    f"System control ACTIVE for {label}. "
                    "Use sys_controll_send_channel to reply to the external session."
                )
            },
        )
    except Exception as exc:
        tui_bridge.release_approval_prompt(request_id)
        clear_approval_context(sid)
        return _err(rid, 5001, str(exc))


def _patch_entry_js() -> None:
    if not _PATCHED_ENTRY.is_file():
        logger.warning("sys-controll: patched entry.js not found at %s", _PATCHED_ENTRY)
        return
    text = _PATCHED_ENTRY.read_text(encoding="utf-8")
    if _MARKER in text:
        return

    event_case = f"""      {_MARKER}
      case "sys_controll.request":
        patchOverlayState({{
          listPicker: {{
            kind: "sys_controll",
            sessionId: ev.session_id || sid,
            extra: {{ request_id: ev.payload.request_id }}
          }}
        }});
        setStatus("system control approval needed");
        return;"""

    anchor = '      case "clarify.request":'
    if anchor not in text:
        logger.warning("sys-controll: could not find clarify.request anchor in entry.js")
        return
    text = text.replace(anchor, event_case + "\n" + anchor, 1)

    old_cancel = "        onCancel: () => patchOverlayState({ listPicker: null }),"
    new_cancel = """        onCancel: () => {
          const lp = overlay.listPicker;
          if (lp?.kind === "sys_controll" && lp.extra?.request_id) {
            gw2.request("hermes.list_picker.select", {
              kind: "sys_controll",
              session_id: lp.sessionId,
              value: "deny",
              extra: lp.extra
            }).catch(() => {});
          }
          patchOverlayState({ listPicker: null });
        },"""
    if old_cancel not in text:
        logger.warning("sys-controll: could not patch listPicker onCancel")
    else:
        text = text.replace(old_cancel, new_cancel, 1)

    _PATCHED_ENTRY.write_text(text, encoding="utf-8")
    logger.info("sys-controll overlay patched into %s", _PATCHED_ENTRY)
