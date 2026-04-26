# Morning Briefing Agent

An AI agent that checks your Gmail, Google Calendar, and Slack, then synthesizes a prioritized morning briefing using an agentic loop (Strands + OpenRouter).

---

## Three Milestones

| Milestone | Command | What it proves |
|-----------|---------|----------------|
| 1. Model connects | `python test_model.py` | OpenRouter responds with a greeting |
| 2. Tools work | See isolation commands below | Real data returns from each API |
| 3. Full agent runs | `python agent.py` | Model calls tools + synthesizes a briefing |

---

## Setup

### 1. Clone and create virtual environment

Requires **Python 3.10 or newer**. On macOS the binary is `python3` (not `python`); inside an activated venv, both names work.

```bash
git clone <your-repo-url>
cd morning-briefing-agent
python3 -m venv .venv
source .venv/bin/activate   # Mac/Linux
# .venv\Scripts\activate    # Windows
```

If your `python3` is older than 3.10 (check with `python3 --version`), install a newer one — easiest is [`uv`](https://github.com/astral-sh/uv):

```bash
pip3 install --user uv
uv venv --python 3.12 .venv     # auto-downloads Python 3.12
source .venv/bin/activate
```

### 2. Install dependencies

If you used the standard `python3 -m venv` path:

```bash
pip install 'strands-agents[litellm]' python-dotenv \
    google-auth google-auth-httplib2 google-auth-oauthlib \
    google-api-python-client slack-sdk
```

If you used the `uv venv` path, use `uv pip` instead — `uv venv` doesn't bundle pip:

```bash
uv pip install 'strands-agents[litellm]' python-dotenv \
    google-auth google-auth-httplib2 google-auth-oauthlib \
    google-api-python-client slack-sdk
```

### 3. Create your .env file

```bash
cp .env.example .env
```

Then open `.env` and fill in your keys.

---

## Getting Your API Keys

### OpenRouter (LLM gateway — free)
1. Go to https://openrouter.ai and sign up
2. Click **Get API key** on the homepage
3. Click **Create** — name it `morning-briefing-agent`
4. Copy the key (starts with `sk-or-`) into `.env` as `OPENROUTER_API_KEY`

### Google (Gmail + Calendar)
1. Go to https://console.cloud.google.com
2. Create a new project named `morning-briefing-agent`
3. Go to **APIs & Services → Library** and enable:
   - Gmail API
   - Google Calendar API
4. Go to **APIs & Services → OAuth consent screen**
   - Choose **External** → Create
   - Fill in app name and emails, save and continue through all screens
5. Go to **APIs & Services → Credentials**
   - Click **+ Create Credentials → OAuth client ID**
   - Application type: **Desktop app**
   - Download the JSON → rename it `credentials.json` → place in this folder

On first run, a browser window will open for Google login. After you approve, `token.json` is saved automatically and you won't be asked again.

### Slack
1. Go to https://api.slack.com/apps
2. Click **Create New App → From scratch**
3. Name it `Morning Briefing Agent`, select your workspace
4. Go to **OAuth & Permissions → User Token Scopes** (not Bot Token Scopes)
5. Add these four scopes: `channels:read`, `channels:history`, `groups:read`, `groups:history`
6. Click **Install to Workspace → Allow**
7. Copy the **User OAuth Token** (starts with `xoxp-`) into `.env` as `SLACK_BOT_TOKEN`

---

## Running the Agent

### Milestone 1 — Verify model connection
```bash
python test_model.py
```
Expected: a one-sentence greeting from the model.

### Milestone 2 — Test each tool in isolation
```bash
python -c "from agent import check_gmail; print(check_gmail(hours_back=24))"
python -c "from agent import check_calendar; print(check_calendar(hours_ahead=24))"
python -c "from agent import check_slack; print(check_slack(hours_back=24))"
```
Expected: JSON with real data from each API.

### Milestone 3 — Run the full agent
```bash
python agent.py
```
Expected: A structured briefing with these sections:
- **URGENT** — time-sensitive emails and imminent events
- **UPCOMING EVENTS** — today's calendar
- **SLACK HIGHLIGHTS** — threads that need your attention
- **OTHER EMAILS** — lower-priority inbox items
- **SUGGESTED ACTIONS** — 3–5 prioritized next steps

---

## Common Errors

| Error | Fix |
|-------|-----|
| `No endpoints found that support tool use` | Confirm `model_id` is `openrouter/openrouter/free` |
| `429 Too Many Requests` | Wait 1 minute and retry |
| `Invalid configuration parameters: ['api_base', 'api_key']` and a 401 from OpenRouter | In `strands-agents ≥ 1.x`, pass `api_key` and `api_base` inside `client_args={...}`, not as top-level kwargs |
| `Invalid configuration parameters: ['max_tokens']` | Move `max_tokens` inside `params={}` |
| `command not found: pip` inside an activated venv | You used `uv venv` (which omits pip). Use `uv pip install ...` instead, or run `python -m ensurepip --upgrade` once |
| `command not found: python` | macOS only ships `python3`. Use `python3 -m venv .venv`; inside the venv, `python` works |
| `Missing credentials.json` | Download from Google Cloud Console, rename, and place in project root |
| `Slack: no channels found` | Re-add scopes under **User Token Scopes** (not Bot Token Scopes) and reinstall |

---

## Stack

| Component | Role |
|-----------|------|
| [Strands](https://github.com/strands-agents/sdk-python) | Agent framework — manages the tool-calling loop |
| LiteLLM | Middleware — translates between Strands and OpenRouter |
| OpenRouter | LLM gateway — free open-source models with tool calling |
| `openrouter/free` | Model router — auto-selects a capable free model |
| `check_gmail` | Tool — reads unread Gmail |
| `check_calendar` | Tool — reads upcoming Calendar events |
| `check_slack` | Tool — reads recent Slack messages |

---

## Project Structure

```
morning-briefing-agent/
├── agent.py            # Main agent with all three tools
├── test_model.py       # Milestone 1 connection test
├── .env                # Your secrets (never commit)
├── .env.example        # Template — safe to commit
├── .gitignore          # Keeps .env, token.json, credentials.json out of git
├── credentials.json    # Google OAuth client (never commit — in .gitignore)
├── token.json          # Auto-generated after first Google login (never commit)
└── README.md           # This file
```
