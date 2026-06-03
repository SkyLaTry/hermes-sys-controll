"""Agent tools for bidirectional sys-controll messaging."""

from __future__ import annotations

import json
from typing import Any, Dict

from .state import bridge_for_gateway, bridge_for_tui, enqueue_inbox


def _session_key() -> str:
    try:
        from gateway.session_context import get_session_env

        return (get_session_env("HERMES_SESSION_KEY", "") or "").strip()
    except Exception:
        import os

        return (os.getenv("HERMES_SESSION_KEY") or "").strip()


def _tui_session_id() -> str:
    try:
        import tui_gateway.server as gw
        from gateway.session_context import get_session_env

        session_key = (get_session_env("HERMES_SESSION_KEY", "") or "").strip()
        if session_key:
            for sid, sess in gw._sessions.items():
                if str(sess.get("session_key") or "") == session_key:
                    return sid
        live = [s for s, sess in gw._sessions.items() if not sess.get("_finalized")]
        if len(live) == 1:
            return live[0]
    except Exception:
        pass
    return ""


def _tool_json(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, indent=2)


def _gateway_bridge_check(**kwargs: Any) -> bool:
    key = _session_key()
    return bool(key and bridge_for_gateway(key))


def _tui_bridge_check(**kwargs: Any) -> bool:
    sid = _tui_session_id()
    return bool(sid and bridge_for_tui(sid))


def handle_send_cli(args: Dict[str, Any], **kwargs: Any) -> str:
    message = str(args.get("message") or "").strip()
    if not message:
        return _tool_json({"error": "message is required"})
    key = _session_key()
    bridge = bridge_for_gateway(key)
    if not bridge:
        return _tool_json({"error": "No active sys-controll bridge for this channel session"})
    ok = enqueue_inbox(message, source=bridge.get("chat_label") or bridge.get("platform") or "channel")
    if not ok:
        return _tool_json({"error": "Failed to queue message for CLI session"})
    return _tool_json(
        {
            "status": "queued",
            "bridge_id": bridge.get("bridge_id"),
            "target": f"TUI session {bridge.get('tui_session_id')}",
            "message_preview": message[:240],
        }
    )


def handle_send_channel(args: Dict[str, Any], **kwargs: Any) -> str:
    message = str(args.get("message") or "").strip()
    if not message:
        return _tool_json({"error": "message is required"})
    sid = _tui_session_id()
    bridge = bridge_for_tui(sid)
    if not bridge:
        return _tool_json({"error": "No active sys-controll bridge for this TUI session"})
    platform = str(bridge.get("platform") or "").strip()
    chat_id = str(bridge.get("chat_id") or "").strip()
    if not platform or not chat_id:
        return _tool_json({"error": "Bridge is missing platform/chat_id metadata"})
    try:
        from tools.send_message_tool import send_message_tool

        result = send_message_tool(
            {
                "action": "send",
                "target": f"{platform}:{chat_id}",
                "message": message,
            }
        )
        if isinstance(result, str):
            return result
        return _tool_json(result if isinstance(result, dict) else {"result": result})
    except Exception as exc:
        return _tool_json({"error": f"Failed to send to {platform}: {exc}"})


SEND_CLI_SCHEMA = {
    "name": "sys_controll_send_cli",
    "description": (
        "Send a message to the linked Hermes CLI/TUI session through the sys-controll bridge. "
        "Only available when /sys-controll is active and approved on both sides."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "Message text to deliver to the CLI/TUI Hermes agent session.",
            }
        },
        "required": ["message"],
    },
}

SEND_CHANNEL_SCHEMA = {
    "name": "sys_controll_send_channel",
    "description": (
        "Send a reply from the CLI/TUI Hermes session back to the linked external channel "
        "(Telegram, etc.) through the sys-controll bridge."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "Message text to deliver to the external channel session.",
            }
        },
        "required": ["message"],
    },
}


def register_tools(ctx) -> None:
    ctx.register_tool(
        name="sys_controll_send_cli",
        toolset="sys_controll",
        schema=SEND_CLI_SCHEMA,
        handler=handle_send_cli,
        check_fn=_gateway_bridge_check,
        description=SEND_CLI_SCHEMA["description"],
        emoji="🔗",
    )
    ctx.register_tool(
        name="sys_controll_send_channel",
        toolset="sys_controll",
        schema=SEND_CHANNEL_SCHEMA,
        handler=handle_send_channel,
        check_fn=_tui_bridge_check,
        description=SEND_CHANNEL_SCHEMA["description"],
        emoji="📡",
    )
