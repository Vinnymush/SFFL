import os
import requests
from atproto import Client


def get_current_nfl_week():
    resp = requests.get("https://api.sleeper.app/v1/state/nfl")
    data = resp.json()
    return data["week"]


def get_league_users(league_id):
    resp = requests.get(f"https://api.sleeper.app/v1/league/{league_id}/users")
    data = resp.json()
    user_map = {}
    for u in data:
        user_map[str(u["user_id"])] = u.get("display_name") or u.get("username") or str(u["user_id"])
    return user_map


def get_players():
    resp = requests.get("https://api.sleeper.app/v1/players/nfl")
    return resp.json()


def get_transactions(league_id, week):
    resp = requests.get(f"https://api.sleeper.app/v1/league/{league_id}/transactions/{week}")
    return resp.json()


def format_transactions(transactions, players, users):
    messages = []
    for t in transactions:
        if t.get("status") != "complete":
            continue
        if t["type"] in ["waiver", "free_agent", "waivers"]:
            roster_ids = t.get("roster_ids", [])
            if not roster_ids:
                continue
            roster_id = roster_ids[0]
            team_name = users.get(str(roster_id), f"Team {roster_id}")
            adds = t.get("adds", {})
            drops = t.get("drops", {})
            add_names = [players[p]["full_name"] for p in adds.keys()] if adds else []
            drop_names = [players[p]["full_name"] for p in drops.keys()] if drops else []
            if add_names and drop_names:
                msg = f"{team_name} added {', '.join(add_names)} and dropped {', '.join(drop_names)}"
            elif add_names:
                msg = f"{team_name} added {', '.join(add_names)}"
            elif drop_names:
                msg = f"{team_name} dropped {', '.join(drop_names)}"
            else:
                continue
            messages.append(msg)
        elif t["type"] == "trade":
            roster_ids = t.get("roster_ids", [])
            if len(roster_ids) < 2:
                continue
            team_a = users.get(str(roster_ids[0]), f"Team {roster_ids[0]}")
            team_b = users.get(str(roster_ids[1]), f"Team {roster_ids[1]}")
            adds = t.get("adds", {})
            team_a_received = []
            team_b_received = []
            for player_id, to_roster in adds.items():
                name = players.get(player_id, {}).get("full_name", player_id)
                if to_roster == roster_ids[0]:
                    team_a_received.append(name)
                elif to_roster == roster_ids[1]:
                    team_b_received.append(name)
            part_a = f"{team_a} received {', '.join(team_a_received)} from {team_b}" if team_a_received else ""
            part_b = f"{team_b} received {', '.join(team_b_received)} from {team_a}" if team_b_received else ""
            if part_a or part_b:
                msg = "Trade: " + "; ".join(filter(None, [part_a, part_b]))
                messages.append(msg)
        elif t["type"] in ["add", "drop"]:
            roster_ids = t.get("roster_ids", [])
            if not roster_ids:
                continue
            team_name = users.get(str(roster_ids[0]), f"Team {roster_ids[0]}")
            adds = t.get("adds", {})
            drops = t.get("drops", {})
            add_names = [players[p]["full_name"] for p in adds.keys()] if adds else []
            drop_names = [players[p]["full_name"] for p in drops.keys()] if drops else []
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
    league_id = os.getenv("SLEEPER_LEAGUE_ID")
    handle = os.getenv("BSKY_HANDLE")
    app_password = os.getenv("BSKY_APP_PASSWORD")
    if not all([league_id, handle, app_password]):
        print("Missing environment variables.")
        return
    week = get_current_nfl_week()
    users = get_league_users(league_id)
    players = get_players()
    transactions = get_transactions(league_id, week)
    msgs = format_transactions(transactions, players, users)
    if not msgs:
        print("No new transactions to post.")
        return
    post_text = "\n".join(msgs)
    if len(post_text) > 280:
        post_text = post_text[:280]
    client = Client()
    client.login(handle, app_password)
    client.send_post(text=post_text)


if __name__ == "__main__":
    main()
