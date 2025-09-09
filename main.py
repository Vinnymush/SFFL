import os
import sys
import time
import requests
from typing import Dict, List, Tuple

# ---------------- Env toggles ----------------
DRY_RUN = os.getenv("DRY_RUN") == "1"   # print instead of posting
DEBUG   = os.getenv("DEBUG") == "1"     # extra logging

SLEEPER_API = "https://api.sleeper.app/v1"

# --------------- Sleeper helpers ---------------

def get_current_nfl_week() -> int:
    """Return the current NFL week per Sleeper."""
    r = requests.get(f"{SLEEPER_API}/state/nfl", timeout=15)
    r.raise_for_status()
    week = int(r.json().get("week", 0) or 0)
    return week

def get_league_users(league_id: str) -> Dict[str, str]:
    """user_id -> display name (fallback: team_name -> username -> user_id)."""
    r = requests.get(f"{SLEEPER_API}/league/{league_id}/users", timeout=30)
    r.raise_for_status()
    users = {}
    for u in r.json():
        name = (
            u.get("display_name")
            or u.get("metadata", {}).get("team_name")
            or u.get("username")
            or str(u.get("user_id"))
        )
        users[str(u["user_id"])] = name
    return users

def get_league_rosters(league_id: str) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Return (roster_owner_map, roster_name_override).
    roster_owner_map: roster_id -> owner_id
    roster_name_override: roster_id -> team_name from roster metadata (if set)
    """
    r = requests.get(f"{SLEEPER_API}/league/{league_id}/rosters", timeout=30)
    r.raise_for_status()
    roster_owner = {}
    roster_name_override = {}
    for row in r.json():
        rid = str(row.get("roster_id"))
        owner_id = str(row.get("owner_id"))
        roster_owner[rid] = owner_id
        team_name = row.get("metadata", {}).get("team_name")
        if team_name:
            roster_name_override[rid] = team_name
    return roster_owner, roster_name_override

def get_players() -> Dict[str, dict]:
    """player_id -> player meta (expects 'full_name')."""
    r = requests.get(f"{SLEEPER_API}/players/nfl", timeout=60)
    r.raise_for_status()
    return r.json()

def get_transactions(league_id: str, week: int) -> List[dict]:
    r = requests.get(f"{SLEEPER_API}/league/{league_id}/transactions/{week}", timeout=30)
    r.raise_for_status()
    return r.json() or []

# --------------- Formatting ---------------

def resolve_team_name(
    roster_id: str,
    roster_owner: Dict[str, str],
    roster_name_override: Dict[str, str],
    users: Dict[str, str],
) -> str:
    """Prefer roster metadata name; else owner's display; else 'Team X'."""
    if roster_id in roster_name_override:
        return roster_name_override[roster_id]
    owner_id = roster_owner.get(roster_id)
    if owner_id and owner_id in users:
        return users[owner_id]
    return f"Team {roster_id}"

def format_transactions(
    transactions: List[dict],
    players: Dict[str, dict],
    users: Dict[str, str],
    roster_owner: Dict[str, str],
    roster_name_override: Dict[str, str],
) -> List[str]:
    """Produce human-readable lines for Bluesky."""
    messages: List[str] = []

    for t in transactions:
        status = t.get("status")
        if status not in (None, "complete", "processed"):
            continue

        t_type = t.get("type")
        roster_ids = [str(r) for r in (t.get("roster_ids") or [])]

        # Waivers/FA/Add/Drop
        if t_type in {"waiver", "free_agent", "waivers", "add", "drop"}:
            if not roster_ids:
                continue
            rid = roster_ids[0]
            team = resolve_team_name(rid, roster_owner, roster_name_override, users)

            adds = t.get("adds") or {}
            drops = t.get("drops") or {}

            add_names = [players.get(pid, {}).get("full_name", pid) for pid in adds.keys()]
            drop_names = [players.get(pid, {}).get("full_name", pid) for pid in drops.keys()]

            if add_names and drop_names:
                messages.append(f"{team} added {', '.join(add_names)} and dropped {', '.join(drop_names)}.")
            elif add_names:
                messages.append(f"{team} added {', '.join(add_names)}.")
            elif drop_names:
                messages.append(f"{team} dropped {', '.join(drop_names)}.")

        # Trades
        elif t_type == "trade":
            if len(roster_ids) < 2:
                continue
            rid_a, rid_b = roster_ids[0], roster_ids[1]
            team_a = resolve_team_name(rid_a, roster_owner, roster_name_override, users)
            team_b = resolve_team_name(rid_b, roster_owner, roster_name_override, users)

            adds = t.get("adds") or {}   # pid -> to_roster_id
            team_a_received, team_b_received = [], []

            for pid, to_rid in adds.items():
                name = players.get(pid, {}).get("full_name", pid)
                if str(to_rid) == rid_a:
                    team_a_received.append(name)
                elif str(to_rid) == rid_b:
                    team_b_received.append(name)

            parts = []
            if team_a_received:
                parts.append(f"{team_a} received {', '.join(team_a_received)} from {team_b}")
            if team_b_received:
                parts.append(f"{team_b} received {', '.join(team_b_received)} from {team_a}")

            if parts:
                messages.append("Trade: " + "; ".join(parts) + ".")

    return messages

# --------------- Bluesky ---------------

def post_to_bluesky(handle: str, app_password: str, texts: List[str]) -> None:
    """Post each message separately; obey 300-char cap. Honors DRY_RUN."""
    if not texts:
        return

    if DRY_RUN:
        print("\n--- DRY RUN (would post) ---")
        for t in texts:
            print(t[:300])
            print("----------------------------")
        return

    try:
        from atproto import Client
        client = Client()
        client.login(handle, app_password)
    except Exception as e:
        print(f"Bluesky login failed: {e}", file=sys.stderr)
        return

    for txt in texts:
        try:
            if len(txt) > 300:
                txt = txt[:300]
            client.send_post(text=txt)
            time.sleep(1.0)  # be polite
        except Exception as e:
            print(f"Post failed: {e}", file=sys.stderr)

# --------------- Main ---------------

def main():
    league_id = os.getenv("SLEEPER_LEAGUE_ID")
    handle = os.getenv("BSKY_HANDLE")
    app_password = os.getenv("BSKY_APP_PASSWORD")

    if not league_id or not handle or not app_password:
        print("Missing env vars: SLEEPER_LEAGUE_ID, BSKY_HANDLE, BSKY_APP_PASSWORD", file=sys.stderr)
        sys.exit(1)

    # Choose week: override if provided, else current.
    week_env = os.getenv("SLEEPER_WEEK")
    if week_env:
        try:
            week = int(week_env)
        except ValueError:
            print("Invalid SLEEPER_WEEK; using current NFL week.")
            week = get_current_nfl_week()
    else:
        week = get_current_nfl_week()

    # Pull data
    users = get_league_users(league_id)
    roster_owner, roster_name_override = get_league_rosters(league_id)
    players = get_players()
    txns = get_transactions(league_id, week)

    if DEBUG:
        print(f"DEBUG: week={week}, users={len(users)}, rosters={len(roster_owner)}, players={len(players)}, txns={len(txns)}")
        if txns:
            print(f"DEBUG: first txn sample keys={list(txns[0].keys())}")

    # Build messages
    msgs = format_transactions(txns, players, users, roster_owner, roster_name_override)

    if not msgs:
        print(f"No transactions found for week {week}. Nothing to do.")
        return

    # Post (or dry-run print)
    post_to_bluesky(handle, app_password, msgs)
    print(f"Done. {'(DRY RUN)' if DRY_RUN else f'Posted {len(msgs)} update(s)'} for week {week}.")

if __name__ == "__main__":
    main()
