"""
Morning Briefing Agent
======================
Checks Gmail, Google Calendar, and Slack, then synthesizes a
prioritized briefing using an agentic loop (Strands + OpenRouter).

Usage:
    python agent.py

Milestones:
    1. test_model.py — model connects
    2. Test each tool in isolation (see bottom of this file)
    3. python agent.py — full end-to-end briefing
"""

import os
import json
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

# ── Strands ──────────────────────────────────────────────────────────────────
from strands import Agent, tool
from strands.models.litellm import LiteLLMModel

# ── Google ────────────────────────────────────────────────────────────────────
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# ── Slack ─────────────────────────────────────────────────────────────────────
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]

TOKEN_PATH = "token.json"
CREDS_PATH = "credentials.json"

# ─────────────────────────────────────────────────────────────────────────────
# Google OAuth helper
# ─────────────────────────────────────────────────────────────────────────────

# Module-level cache so concurrent tool calls share one set of credentials
# (and one OAuth flow) instead of each spinning up their own local server.
_cached_creds: Credentials | None = None


def get_google_credentials() -> Credentials:
    """
    Returns valid Google OAuth credentials.
    - Returns the in-memory cached creds if already loaded this session.
    - Otherwise loads from token.json, refreshes if expired, or runs the
      browser OAuth flow once (and saves token.json for next time).
    """
    global _cached_creds

    if _cached_creds and _cached_creds.valid:
        return _cached_creds

    creds = None

    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDS_PATH):
                raise FileNotFoundError(
                    f"'{CREDS_PATH}' not found.\n"
                    "Download it from Google Cloud Console:\n"
                    "  APIs & Services → Credentials → OAuth 2.0 Client IDs → Download JSON\n"
                    "Rename the file to 'credentials.json' and place it in this folder."
                )
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_PATH, "w") as token_file:
            token_file.write(creds.to_json())

    _cached_creds = creds
    return creds


# ─────────────────────────────────────────────────────────────────────────────
# Tool 1 — Gmail
# ─────────────────────────────────────────────────────────────────────────────

@tool
def check_gmail(hours_back: int = 12) -> str:
    """
    Fetches unread emails from Gmail from the last N hours.

    Args:
        hours_back: How many hours back to look (default 12).

    Returns:
        A JSON string of emails, each with sender, subject, date, and snippet.
    """
    creds = get_google_credentials()
    service = build("gmail", "v1", credentials=creds)

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    # Gmail query syntax — epoch seconds
    after_ts = int(cutoff.timestamp())
    query = f"is:unread after:{after_ts}"

    results = service.users().messages().list(
        userId="me", q=query, maxResults=20
    ).execute()

    messages = results.get("messages", [])

    if not messages:
        return json.dumps({"emails": [], "note": f"No unread emails in the last {hours_back} hours."})

    emails = []
    for msg in messages:
        detail = service.users().messages().get(
            userId="me", id=msg["id"], format="metadata",
            metadataHeaders=["From", "Subject", "Date"]
        ).execute()

        headers = {h["name"]: h["value"] for h in detail.get("payload", {}).get("headers", [])}
        snippet = detail.get("snippet", "")[:200]

        emails.append({
            "sender": headers.get("From", "Unknown"),
            "subject": headers.get("Subject", "(no subject)"),
            "date": headers.get("Date", "Unknown"),
            "snippet": snippet,
        })

    return json.dumps({"emails": emails})


# ─────────────────────────────────────────────────────────────────────────────
# Tool 2 — Google Calendar
# ─────────────────────────────────────────────────────────────────────────────

@tool
def check_calendar(hours_ahead: int = 24) -> str:
    """
    Fetches upcoming events from Google Calendar for the next N hours.

    Args:
        hours_ahead: How many hours ahead to look (default 24).

    Returns:
        A JSON string of events with title, start, end, location, and attendees.
    """
    creds = get_google_credentials()
    service = build("calendar", "v3", credentials=creds)

    now = datetime.now(timezone.utc)
    time_min = now.isoformat()
    time_max = (now + timedelta(hours=hours_ahead)).isoformat()

    results = service.events().list(
        calendarId="primary",
        timeMin=time_min,
        timeMax=time_max,
        maxResults=20,
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    events = results.get("items", [])

    if not events:
        return json.dumps({"events": [], "note": f"No events in the next {hours_ahead} hours."})

    formatted = []
    for event in events:
        start = event.get("start", {})
        end = event.get("end", {})
        attendees = [
            a.get("email", "") for a in event.get("attendees", [])
            if not a.get("self", False)
        ]

        formatted.append({
            "title": event.get("summary", "(no title)"),
            "start": start.get("dateTime", start.get("date", "Unknown")),
            "end": end.get("dateTime", end.get("date", "Unknown")),
            "location": event.get("location", ""),
            "attendees": attendees,
            "meeting_link": event.get("hangoutLink", ""),
        })

    return json.dumps({"events": formatted})


# ─────────────────────────────────────────────────────────────────────────────
# Tool 3 — Slack
# ─────────────────────────────────────────────────────────────────────────────

@tool
def check_slack(hours_back: int = 12, max_channels: int = 5) -> str:
    """
    Fetches recent Slack messages from the most recently active channels.

    Args:
        hours_back: How many hours back to look (default 12).
        max_channels: Max number of channels to check (default 5).

    Returns:
        A JSON string of channels, each with up to 5 recent messages.
    """
    token = os.getenv("SLACK_BOT_TOKEN")
    if not token:
        return json.dumps({"error": "SLACK_BOT_TOKEN not found in .env"})

    client = WebClient(token=token)
    cutoff_ts = str((datetime.now(timezone.utc) - timedelta(hours=hours_back)).timestamp())

    try:
        # Get all joined channels
        response = client.conversations_list(
            types="public_channel,private_channel",
            exclude_archived=True,
            limit=200,
        )
        channels = response.get("channels", [])
    except SlackApiError as e:
        return json.dumps({"error": f"Slack API error listing channels: {e.response['error']}"})

    # Filter to channels with recent activity
    active_channels = [
        c for c in channels
        if c.get("last_read") or c.get("is_member", False)
    ]

    # Sort by most recent activity — use id as a stable fallback
    active_channels = sorted(
        active_channels,
        key=lambda c: c.get("updated", 0),
        reverse=True,
    )[:max_channels]

    result = []
    for channel in active_channels:
        channel_id = channel["id"]
        channel_name = channel.get("name", channel_id)

        try:
            history = client.conversations_history(
                channel=channel_id,
                oldest=cutoff_ts,
                limit=5,
            )
            messages = history.get("messages", [])
        except SlackApiError as e:
            result.append({
                "channel": channel_name,
                "error": e.response["error"],
            })
            continue

        formatted_msgs = []
        for msg in messages:
            if msg.get("subtype"):
                continue  # skip bot/system messages
            formatted_msgs.append({
                "user": msg.get("user", "unknown"),
                "text": msg.get("text", "")[:300],
                "ts": datetime.fromtimestamp(
                    float(msg.get("ts", 0)), tz=timezone.utc
                ).strftime("%Y-%m-%d %H:%M UTC"),
            })

        result.append({
            "channel": channel_name,
            "messages": formatted_msgs,
        })

    return json.dumps({"channels": result})


# ─────────────────────────────────────────────────────────────────────────────
# System prompt
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """
You are a morning briefing agent. Your job is to give a concise, prioritized
briefing that helps the user know exactly what needs attention today.

Always follow this process:
1. Call check_gmail to get recent unread emails.
2. Call check_calendar to get upcoming events.
3. Call check_slack to get recent Slack activity.
4. Synthesize everything into a structured briefing.

Your briefing must use EXACTLY these five sections, in this order:

URGENT
  — Emails flagged as time-sensitive, action-required, from important senders,
    or with subjects containing words like "urgent", "deadline", "action required".
  — Events starting within 2 hours that the user may not be prepared for.

UPCOMING EVENTS
  — All calendar events for today, formatted as a clean schedule.
  — Include time, title, location (if any), and who else is attending.

SLACK HIGHLIGHTS
  — Threads or messages that seem to require a response or contain decisions.
  — Skip small talk and reactions. Surface what matters.

OTHER EMAILS
  — Non-urgent emails worth knowing about but not immediately actionable.

SUGGESTED ACTIONS
  — 3–5 specific actions the user should take today, in priority order.
  — Be direct. "Reply to X about Y" not "consider responding."

If any source returns no data, say so briefly and move on.
Do not dump raw data. Write like a sharp executive assistant.
""".strip()


# ─────────────────────────────────────────────────────────────────────────────
# Agent runner
# ─────────────────────────────────────────────────────────────────────────────

def run():
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENROUTER_API_KEY not found in .env")

    # Run Google OAuth synchronously up front so the (potentially parallel)
    # Gmail and Calendar tool calls share a single token instead of each
    # launching its own browser flow on a separate localhost port.
    print("Authenticating with Google (browser may open on first run)...")
    get_google_credentials()

    model = LiteLLMModel(
        client_args={
            "api_key": api_key,
            "api_base": "https://openrouter.ai/api/v1",
        },
        model_id="openrouter/tencent/hy3-preview:free",
        params={"max_tokens": 4096},
    )

    agent = Agent(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        tools=[check_gmail, check_calendar, check_slack],
    )

    print("=" * 60)
    print("  MORNING BRIEFING AGENT")
    print(f"  {datetime.now().strftime('%A, %B %d, %Y — %I:%M %p')}")
    print("=" * 60)
    print("Calling tools and synthesizing your briefing...\n")

    response = agent("What did I miss? Give me my morning briefing.")
    print(response)


# ─────────────────────────────────────────────────────────────────────────────
# Milestone 2 — Quick tool isolation tests
# Run these manually to confirm each tool works before running the full agent:
#
#   python -c "from agent import check_gmail; print(check_gmail(hours_back=24))"
#   python -c "from agent import check_calendar; print(check_calendar(hours_ahead=24))"
#   python -c "from agent import check_slack; print(check_slack(hours_back=24))"
#
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run()
