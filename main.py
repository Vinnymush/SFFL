import os
import time
import requests
from atproto import Client

# Functions to get league and player data from Sleeper

def get_current_nfl_week():
    """Return the current NFL week based on Sleeper API."""
    response = requests.get("https://api.sleeper.app/v1/state/nfl")
    response.raise_for_status()
    return response.json().get("week", 0)

def get_league_users(league_id):
    """Return a dict mapping user_id to user display names."""
    response = requests.get(f"https://api.sleeper.app/v1/league/{league_id}/users")
    response.raise_for_status()
    users = {}
    for user in response.json():
        users[user['user_id']] = user.get('display_name') or user.get('metadata', {}).get('team_name', user['username'])
    return users

def get_players():
    """Return a dict mapping player_id to player metadata from Sleeper."""
    response = requests.get("https://api.sleeper.app/v1/players/nfl")
    response.raise_for_status()
    return response.json()

def get_transactions(league_id, week):
    """Return the list of transactions for the given league and week."""
    response = requests.get(f"https://api.sleeper.app/v1/league/{league_id}/transactions/{week}")
    response.raise_for_status()
    return response.json() or []

def format_transactions(transactions, players, users):
    """Format transactions into human-readable messages."""
    messages = []
    for t in transactions:
        t_type = t.get("type")
        # Skip transactions that are not executed (e.g. free agent bids that failed)
        status = t.get("status")
        if status not in ["complete", "processed", None]:
            continue
        roster_ids = t.get("roster_ids", [])
        if t_type == "trade":
            # Format trade transactions
            team_a = users.get(roster_ids[0], f"Team {roster_ids[0]}")
            team_b = users.get(roster_ids[1], f"Team {roster_ids[1]}")
            adds = t.get("adds", {})
            team_a_received = []
            team_b_received = []
            for player_id, to_roster in adds.items():
                player_name = players.get(player_id, {}).get("full_name", player_id)
                if to_roster == roster_ids[0]:
                    team_a_received.append(player_name)
                elif to_roster == roster_ids[1]:
                    team_b_received.append(player_name)
            part_a = f"{team_a} received {', '.join(team_a_received)} from {team_b}" if team_a_received else ""
            part_b = f"{team_b} received {', '.join(team_b_received)} from {team_a}" if team_b_received else ""
            trade_msg = "Trade: " + ", ".join(filter(None, [part_a, part_b]))
            if trade_msg:
                messages.append(trade_msg)
        elif t_type in ["add", "drop"]:
            if not roster_ids:
                continue
            team_name = users.get(roster_ids[0], f"Team {roster_ids[0]}")
            adds = t.get("adds", {}) or {}
            drops = t.get("drops", {}) or {}
            add_names = [players.get(pid, {}).get("full_name", pid) for pid in adds.keys()] if adds else []
            drop_names = [players.get(pid, {}).get("full_name", pid) for pid in drops.keys()] if drops else []
            if add_names and drop_names:
                msg = f"{team_name} added {', '.join(add_names)} and dropped {', '.join(drop_names)}"
            elif add_names:
                msg = f"{team_name} added {', '.join(add_names)}"
            elif drop_names:
                msg = f"{team_name} dropped {', '.join(drop_names)}"
            else:
                continue
            messages.append(msg)
    return messages

def main():
    # Get environment variables
    league_id = os.getenv("SLEEPER_LEAGUE_ID")
    handle = os.getenv("BSKY_HANDLE")
    app_password = os.getenv("BSKY_APP_PASSWORD")
    if not all([league_id, handle, app_password]):
        print("Missing environment variables.")
        return
    # Get current week and data
    week = get_current_nfl_week()
    users = get_league_users(league_id)
    players = get_players()
    transactions = get_transactions(league_id, week)
    msgs = format_transactions(transactions, players, users)
    # Fallback: use a fake transaction for testing when there are no transactions
    if not msgs:
        msgs = ["Test Transaction: Jakki adds Amon-Ra St. Brown and drops Defense."]
    # Join messages and enforce 300-char limit (Bluesky limit ~300)
    post_text = "\n\n".join(msgs)
    if len(post_text) > 300:
        post_text = post_text[:300]
    # Send post to Bluesky
    client = Client()
    client.login(handle, app_password)
    client.send_post(text=post_text)

if __name__ == "__main__":
    main()
