# hermes-sys-controll

**Bridge mobile & chat channels to your desktop Hermes TUI** — with explicit approval on both sides.

**Author:** [SkyLaTry](https://github.com/SkyLaTry) · **Hermes:** 0.15.1+ · **Version:** 1.2.2 · **Repo:** [SkyLaTry/hermes-sys-controll](https://github.com/SkyLaTry/hermes-sys-controll)

Part of the [SkyLaTry Hermes plugin set](https://github.com/SkyLaTry/hermes-essentials/blob/main/PLUGINS.md).

---

## What it does

`sys-controll` connects an **external Hermes channel** (Telegram, Discord, Slack, …) to the **Hermes TUI session running on your machine**. Messages flow both ways through a controlled bridge — nothing relays until you approve it in the TUI overlay.

Typical setup: Hermes gateway + TUI on your PC, Telegram on your phone. You stay in the terminal; remote messages land in the same agent context after you consent.

**Requires [hermes-essentials](https://github.com/SkyLaTry/hermes-essentials)** for channel routing and TUI list-picker integration.

---

## Use cases

| Scenario | How it helps |
|----------|----------------|
| **Phone → desktop agent** | Ask Hermes from Telegram while your main session, tools, and files live in the local TUI. |
| **Hands-busy / away from keyboard** | Send a quick prompt from a mobile channel; read the reply on whichever surface you have open. |
| **Shared household bot** | One gateway on a home PC; you approve when a bridged channel should talk to *your* active TUI (not silently hijack it). |
| **Cross-surface debugging** | Reproduce a Telegram conversation in the TUI where you have logs, skills, and full slash commands. |
| **Focused terminal workflow** | Keep coding in the TUI; bridge only when you explicitly run `/sys-controll on` and approve. |

The bridge **auto-disconnects** on `/new`, session end, or `/sys-controll off` — so a remote channel cannot permanently bind your desktop session.

---

## Quick start

```bash
# Hermes (once)
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash

# This plugin (installs essentials if missing)
curl -fsSL https://raw.githubusercontent.com/SkyLaTry/hermes-sys-controll/main/install.sh | bash
hermes gateway restart
```

**Alternative (Hermes CLI):**

```bash
hermes plugins install SkyLaTry/hermes-essentials --enable
hermes plugins install SkyLaTry/hermes-sys-controll --enable
hermes gateway restart
```

```yaml
plugins:
  enabled:
    - hermes-essentials
    - sys-controll
```

---

## Workflow

1. Start the local TUI: `hermes chat --tui`
2. From Telegram (or another channel): `/sys-controll on`
3. **Approve** the bridge in the TUI overlay (primary TUI wins if several are open)
4. Chat on either side — messages relay through the bridge
5. Disconnect with `/sys-controll off` or start a new session

When bridged, each side gets tools to send messages to the other session.

---

## Commands

| Command | Description |
|---------|-------------|
| `/sys-controll` | Status for this channel |
| `/sys-controll on` | Request bridge (approval required in TUI) |
| `/sys-controll off` | Disconnect bridge |

---

## Requirements

- [Hermes Agent](https://github.com/NousResearch/hermes-agent) **0.15.1+**
- [hermes-essentials](https://github.com/SkyLaTry/hermes-essentials) — routing + TUI integration
- **Local TUI running** for approval UI
- Gateway on the **same machine** as the TUI (typical home / workstation setup)

---

## Related SkyLaTry plugins

See [PLUGINS.md](PLUGINS.md) for the full index and install one-liners.

| Plugin | Repository |
|--------|------------|
| Hermes Essentials | [hermes-essentials](https://github.com/SkyLaTry/hermes-essentials) |
| Screen Awareness | [hermes-screen-awareness](https://github.com/SkyLaTry/hermes-screen-awareness) |
| **Sys Controll** *(this repo)* | [hermes-sys-controll](https://github.com/SkyLaTry/hermes-sys-controll) |
| Lemonade LLM Image | [hermes-lemonade-llm-image-support](https://github.com/SkyLaTry/hermes-lemonade-llm-image-support) |
| Image Local Tools | [hermes-image-local-tools](https://github.com/SkyLaTry/hermes-image-local-tools) |

---
> **Experimental:** This plugin is still in an early, experimental phase. Behavior and configuration may change between releases. If you hit bugs or something doesn’t work as expected, please [open an issue](https://github.com/SkyLaTry/hermes-sys-controll/issues) on this repository — feedback and reports help a lot.
---

## License

SkyLaTry Shared Source License — see [LICENSE](LICENSE) and [LICENSING.md](LICENSING.md).
