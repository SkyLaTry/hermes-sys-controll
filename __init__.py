"""Sys-controll plugin: bridge external channels to an active Hermes TUI session."""

from __future__ import annotations

import logging

from .command import handle_sys_controll
from .state import disconnect_bridge, get_active_bridge
from .tools import register_tools
from .tui_bridge import apply_tui_bridge
from .tui_overlay import apply_tui_overlay

logger = logging.getLogger(__name__)


def _on_session_finalize(session_id: str = "", **kwargs) -> None:
    if not session_id:
        return
    active = get_active_bridge()
    if not active:
        return
    if str(active.get("gateway_session_id") or "") == str(session_id):
        disconnect_bridge(gateway_session_id=str(session_id))
        logger.info("sys-controll bridge cleared (gateway session finalized: %s)", session_id)


def _on_session_reset(session_id: str = "", platform: str = "", **kwargs) -> None:
    active = get_active_bridge()
    if not active:
        return
    plat = (platform or "").strip().lower()
    if plat == "tui":
        key = str(session_id or "")
        if key in {
            str(active.get("tui_session_key") or ""),
            str(active.get("tui_session_id") or ""),
        }:
            disconnect_bridge(tui_session_id=str(active.get("tui_session_id") or ""))
            logger.info("sys-controll bridge cleared (TUI session reset)")
        return
    disconnect_bridge(gateway_session_key=str(active.get("gateway_session_key") or ""))
    logger.info("sys-controll bridge cleared (gateway session reset)")


def register(ctx) -> None:
    apply_tui_bridge()
    apply_tui_overlay()
    register_tools(ctx)
    ctx.register_command(
        "sys-controll",
        handler=handle_sys_controll,
        description="Bridge external channel sessions to your active Hermes TUI (dual consent).",
        args_hint="on|off|status",
    )
    ctx.register_hook("on_session_finalize", _on_session_finalize)
    ctx.register_hook("on_session_reset", _on_session_reset)
