# gemini-seeker

**English** | [中文](README.zh-CN.md)

A lightweight bridge that turns the **Gemini web app** (gemini.google.com, using your own account cookies) into an **OpenAI / Anthropic compatible API**.

- Protocols: OpenAI `/v1/chat/completions` (incl. streaming) + Anthropic `/v1/messages`
- Tool calling: multi-turn `tool_calls` passthrough (standard OpenAI protocol)
- Account pool: reads `accounts.json`, multi-account with hot-switch via web panel (short TTL re-read)
- Session: one persistent `ChatSession`, keeps the last N history turns

> ⚠️ This project works by **reverse-engineering the Gemini web interface**. For **personal study and self-use only**. Respect Google's Terms of Service; do not use commercially or for abuse. Your cookie is your login credential — keep it secret.

## Why use it / What it solves

### Why not the official API?

- The official Gemini API requires **a credit card, paid plan, and specific regions** — a high bar for individual developers.
- The official API has **RPM/RPD quota limits**; free quota is small.
- This project **uses your own web account**, consuming the web-side quota (usually enough for personal daily use).

### Highlights vs. similar projects

| Feature | Description |
|---|---|
| **Dual protocol** | OpenAI `/v1/chat/completions` + Anthropic `/v1/messages`; works with RikkaHub / Cursor / Claude-style clients |
| **Account pool + hot switch** | Multiple accounts in `accounts.json`; switch with one click on the web panel, **no service restart** |
| **Tool-calling bridge** | The web endpoint doesn't understand the `tools` field; this project bridges via prompt + lenient parsing, **supports multi-turn `tool_calls`** |
| **100k prompt truncation** | Prevents overly long client history from stalling the web endpoint (a common pitfall in similar projects) |
| **JSON unwrapping** | Automatically strips the model's `{"content":...}` wrapper so clients receive plain text |
| **Single-file deploy** | Flask + venv, one systemd unit; no database, no extra baggage |

## ⚠️ Disclaimer

- **For study/research only**: this project is for technical research and personal learning; **commercial use is prohibited**.
- **Unofficial**: no affiliation with Google LLC / Alphabet Inc.; not authorized or endorsed by them.
- **May violate ToS**: accessing the Gemini web endpoint with reverse-engineered cookies **may violate Google's Terms of Service**. Any consequences (account restriction, ban, data loss) are **borne by the user**.
- **Use at your own risk**: provided "as is"; the author is not liable for any direct or indirect loss.
- **Recommendation**: prefer the official Gemini API. This project is only a personal fallback when the official API is unavailable.

## How it works

```
Client (OpenAI/Anthropic protocol)
        │
        ▼
   app.py (Flask)          ← parse messages / tools, build prompt
        │
        ▼
  gemini_seeker/session.py  ← gemini_webapi persistent ChatSession + thread lock
        │
        ▼
  gemini_seeker/pool.py     ← read accounts.json for cookies
        │
        ▼
   gemini_webapi  →  gemini.google.com
```

The Gemini web endpoint doesn't accept a native `tools` field, so we use a **prompt bridge**: write the tool definitions into the system prompt and ask the model to output JSON only (`{"tool_calls":[...]}` or `{"content":"..."}`). `parser.py` then leniently parses the model output back into the standard format.

## Project layout

```
gemini-seeker/
├── app.py                  # Flask entry
├── requirements.txt
├── gemini_seeker/
│   ├── __init__.py
│   ├── pool.py             # account pool reader
│   ├── session.py          # client + persistent session + lock
│   ├── prompt.py           # tool-bridge prompt
│   └── parser.py           # lenient model-output parser
├── deploy/
│   ├── gemini-seeker.service
│   └── Caddyfile.example
└── config.example.json     # accounts.json example
```

## Quick start (running in 5 minutes)

> Prerequisite: a Linux server (or local machine) that can reach `gemini.google.com`.

**Step 1. Get your cookies (the crucial step)**

Install the **Cookie-Editor** extension in your browser (Chrome / Edge / Firefox stores), then:

1. Log in to https://gemini.google.com
2. Click the Cookie-Editor icon → **Export as JSON** (do NOT use F12 `document.cookie` — it cannot read `HttpOnly` cookies)
3. From the exported JSON, find these two values:
   - `__Secure-1PSID` (starts with `g.a000...`)
   - `__Secure-1PSIDTS` (starts with `AKEyXz...` or `sidts-...`)

Join them into one line: `__Secure-1PSID=g.a000...; __Secure-1PSIDTS=AKEyXz...`

**Step 2. Install**

```bash
git clone https://github.com/ymf2317-tech/gemini-seeker.git
cd gemini-seeker
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

**Step 3. Write the account pool**

```bash
mkdir -p /root/gemini-panel
cat > /root/gemini-panel/accounts.json <<'EOF'
{
  "A": {
    "name": "my account",
    "cookies": "__Secure-1PSID=<paste Step 1 value>; __Secure-1PSIDTS=<paste Step 1 value>",
    "auth_user": ""
  }
}
EOF
```

**Step 4. Run**

```bash
.venv/bin/python app.py
```

If you see `* Running on http://0.0.0.0:4983`, it's up.

**Step 5. Verify**

```bash
curl -s localhost:4983/health
# {"ok":true,...} means OK

curl -s -X POST localhost:4983/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gemini","messages":[{"role":"user","content":"hello"}]}'
```

**Step 6. Connect a client**

Put `http://<your-server-ip>:4983` into RikkaHub / any OpenAI client (see "Client setup" below).

> For production, use systemd + Caddy reverse proxy (HTTPS). Templates are in `deploy/`.

## Installation

### 1. Dependencies

```bash
git clone https://github.com/ymf2317-tech/gemini-seeker.git /root/gemini-seeker
cd /root/gemini-seeker
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

`requirements.txt`:

```
flask>=3.0
requests>=2.31
gemini-webapi>=2.1.1
```

### 2. Account pool `accounts.json`

Placed in the project root (default path `/root/gemini-panel/accounts.json`, changeable via env var `GEMINI_POOL_PATH`).

```json
{
  "A": {
    "name": "account A",
    "cookies": "__Secure-1PSID=g.a000...; __Secure-1PSIDTS=sidts...",
    "auth_user": ""
  },
  "B": {
    "name": "account B",
    "cookies": "__Secure-1PSID=g.a000...; __Secure-1PSIDTS=sidts...",
    "auth_user": ""
  }
}
```

**How to get cookies**: log in to gemini.google.com in a browser → F12 → Application → Cookies → copy the `__Secure-1PSID` and `__Secure-1PSIDTS` values, joined as `key=value; key=value`.

> Cookies expire. Once the log shows `Account status: UNAUTHENTICATED`, responses become extremely slow (the library falls back to a degraded path). Re-login and update the cookie.

### 3. Environment variables

| Variable | Default | Description |
|---|---|---|
| `GEMINI_SEEKER_API_KEY` | empty | Client auth key; empty means no auth |
| `GEMINI_SEEKER_HISTORY_TURNS` | 3 | Number of recent history turns to keep |
| `GEMINI_POOL_PATH` | `/root/gemini-panel/accounts.json` | Account pool path |
| `GEMINI_POOL_DEFAULT` | `A` | Which account to use by default |
| `GEMINI_POOL_TTL` | 3 | Account pool cache TTL (seconds) |

### 4. Run

```bash
.venv/bin/python app.py        # listens on 0.0.0.0:4983
```

Or use systemd directly (see `deploy/`).

## Client setup (RikkaHub / any OpenAI client)

| Field | Value |
|---|---|
| Base URL | `https://your-domain.example` (replace with your own domain) |
| API path | `/v1/chat/completions` |
| API Key | the `GEMINI_SEEKER_API_KEY` you set |
| Model name | anything (ignored by the service, e.g. `gemini-3.8-flash`) |

> Note the path must include `/v1`. Some clients already include `/v1` in the Base URL; in that case the path is `/chat/completions`.

Anthropic protocol endpoint: `/v1/messages`.

## Endpoints

- `GET /health` — health check, returns current account/session state
- `POST /v1/chat/completions` — OpenAI protocol (supports `stream`)
- `POST /v1/messages` — Anthropic protocol

## Known behavior

- **Cookie expiry → very slow**: the library falls back to a degraded path, each request may take tens of seconds. Refreshing the cookie restores it.
- **Concurrency**: only one request enters the session at a time (lock); extra concurrent client requests queue up.
- **usage field**: token counts are 0 (not implemented); does not affect functionality.

## License

**GNU Affero General Public License v3.0 (AGPL-3.0)** — see [LICENSE](LICENSE).

> Why AGPL: this project depends on `gemini-webapi` (AGPL-3.0). AGPL is viral, so the whole project is released under AGPL-3.0.
>
> Third-party sources:
> - [`gemini-webapi`](https://github.com/HanaokaYuzu/Gemini-API) (AGPL-3.0)
> - Part of `parser.py`'s parsing approach is adapted from [`AmanCode22/deeperseeker`](https://github.com/AmanCode22/deeperseeker) (MIT)
