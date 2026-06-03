"""Slash command handler for /sys-controll."""

from __future__ import annotations

import time

from .state import (
    bridge_for_gateway,
    clear_pending,
    create_pending_request,
    disconnect_bridge,
    get_active_bridge,
    get_pending_request,
    tui_is_active,
)

_HELP = """\
System control bridge — link an external channel session to your active Hermes TUI

  /sys-controll              — show bridge status
  /sys-controll on           — request bridge (external channel; requires TUI approval)
  /sys-controll off          — disconnect bridge immediately

When active, each side gets tools to send messages to the other session.
The bridge auto-disables when either session ends or /new is used.

Gateway: run /sys-controll on from Telegram/Discord/Slack, then approve in a local TUI.
"""


def _session_context() -> tuple[str, str, str, str]:
    platform = ""
    chat_id = ""
    session_key = ""
    session_id = ""
    try:
        from hermes_plugins.hermes_essentials.routing.channel_routing import (
            get_current_platform_key,
            get_current_chat_id,
            get_current_session_key,
        )

        platform = get_current_platform_key()
        chat_id = get_current_chat_id()
        session_key = get_current_session_key()
    except Exception:
        pass
    try:
        from gateway.session_context import get_session_env

        if not platform:
            platform = (get_session_env("HERMES_SESSION_PLATFORM", "") or "").strip().lower()
        if not chat_id:
            chat_id = (get_session_env("HERMES_SESSION_CHAT_ID", "") or "").strip()
        if not session_key:
            session_key = (get_session_env("HERMES_SESSION_KEY", "") or "").strip()
        session_id = (get_session_env("HERMES_SESSION_ID", "") or "").strip()
    except Exception:
        session_id = ""
    if not platform:
        import os

        platform = (os.getenv("HERMES_SESSION_PLATFORM") or os.getenv("HERMES_SESSION_SOURCE") or "cli").strip().lower()
        chat_id = chat_id or (os.getenv("HERMES_SESSION_CHAT_ID") or "").strip()
        session_key = session_key or (os.getenv("HERMES_SESSION_KEY") or "").strip()
        session_id = session_id or (os.getenv("HERMES_SESSION_ID") or "").strip()
    return platform, chat_id, session_key, session_id


def _chat_label(platform: str, chat_id: str) -> str:
    label = f"{platform or 'unknown'}"
    if chat_id:
        label += f" · chat {chat_id}"
    try:
        from gateway.session_context import get_session_env

        user = (get_session_env("HERMES_SESSION_USER_ID", "") or "").strip()
        if user:
            label += f" · user {user}"
    except Exception:
        pass
    return label


def _is_external_platform(platform: str) -> bool:
    return platform not in {"", "cli", "local", "tui", "terminal"}


def _pending_status(pending: dict) -> str:
    try:
        remaining = max(0, int(float(pending.get("expires_at") or 0) - time.time()))
    except (TypeError, ValueError):
        remaining = 0
    decision = pending.get("tui_decision")
    if decision == "deny":
        clear_pending("denied")
        return "System control request denied by the TUI user.\n\n" + _HELP
    if decision == "accept":
        active = get_active_bridge()
        if active:
            return (
                "System control bridge ACTIVE.\n"
                f"  Channel: {active.get('chat_label', '?')}\n"
                f"  TUI session: {active.get('tui_session_id', '?')}\n\n"
                + _HELP
            )
    if remaining <= 0:
        clear_pending("timeout")
        return "Timed out waiting for TUI approval. Retry /sys-controll on.\n\n" + _HELP
    return (
        "System control request pending TUI approval.\n"
        f"  Channel: {pending.get('chat_label', '?')}\n"
        f"  Time left: {remaining}s\n"
        "Check your Hermes TUI for the Accept/Deny popup.\n\n"
        + _HELP
    )


def _status_text() -> str:
    active = get_active_bridge()
    pending = get_pending_request()
    tui_up = tui_is_active()
    lines = ["System control bridge status:", f"  TUI session active: {'yes' if tui_up else 'no'}"]
    if pending and not pending.get("tui_decision"):
        try:
            remaining = max(0, int(float(pending.get("expires_at") or 0) - time.time()))
        except (TypeError, ValueError):
            remaining = 0
        lines.append(f"  Pending approval: {pending.get('chat_label', '?')} (expires in {remaining}s)")
    elif pending and pending.get("tui_decision") == "deny":
        lines.append("  Last request: denied by TUI user")
    if active:
        lines.extend(
            [
                "  Bridge: ACTIVE",
                f"  Channel: {active.get('chat_label', active.get('platform', '?'))}",
                f"  TUI session: {active.get('tui_session_id', '?')}",
                f"  Bridge id: {active.get('bridge_id', '?')}",
            ]
        )
    else:
        lines.append("  Bridge: inactive")
    lines.append("")
    lines.append(_HELP.strip())
    return "\n".join(lines)


def _request_bridge() -> str:
    platform, chat_id, session_key, session_id = _session_context()
    if not _is_external_platform(platform):
        return (
            "System control requests must be sent from an external channel (Telegram, Discord, etc.).\n"
            "On the CLI/TUI use /sys-controll status or /sys-controll off.\n\n"
            + _HELP
        )
    if not session_key:
        return "Could not resolve gateway session key for this chat.\n\n" + _HELP

    existing = bridge_for_gateway(session_key)
    if existing:
        return (
            "System control bridge is already active for this chat.\n"
            f"  TUI session: {existing.get('tui_session_id', '?')}\n"
            "Use /sys-controll off to disconnect.\n\n"
            + _HELP
        )

    if not tui_is_active():
        return (
            "No active Hermes TUI session detected.\n"
            "Start `hermes chat --tui` on your machine first, then retry /sys-controll on.\n\n"
            + _HELP
        )

    pending = get_pending_request()
    if pending:
        if pending.get("gateway_session_key") == session_key:
            return _pending_status(pending)
        clear_pending("superseded")

    chat_label = _chat_label(platform, chat_id)
    create_pending_request(
        gateway_session_key=session_key,
        gateway_session_id=session_id,
        platform=platform,
        chat_id=chat_id,
        chat_label=chat_label,
    )
    return (
        "System control request sent to your Hermes TUI.\n"
        f"  Channel: {chat_label}\n"
        "Waiting for Accept/Deny in the TUI popup (up to 5 minutes).\n"
        "Run /sys-controll status to check again.\n\n"
        + _HELP
    )


def _disconnect() -> str:
    platform, _chat_id, session_key, _session_id = _session_context()
    active = get_active_bridge()
    if not active:
        clear_pending("manual")
        return "System control bridge is not active.\n\n" + _HELP

    if _is_external_platform(platform):
        if active.get("gateway_session_key") != session_key:
            return "This chat is not the active bridged session.\n\n" + _HELP
    disconnect_bridge(gateway_session_key=active.get("gateway_session_key", ""))
    return "System control bridge disconnected.\n\n" + _HELP


def handle_sys_controll(raw_args: str) -> str:
    arg = (raw_args or "").strip().lower()
    if not arg or arg in {"status", "help", "?"}:
        return _status_text()
    if arg in {"on", "enable", "start", "connect", "yes"}:
        return _request_bridge()
    if arg in {"off", "disable", "stop", "disconnect", "no", "revoke"}:
        return _disconnect()
    return f"Unknown argument: {raw_args!r}\n\n" + _HELP
