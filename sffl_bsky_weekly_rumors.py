import os, sys
from collections import defaultdict, Counter
from sffl_common import (
    is_now_ny, get_current_week, get_league_users, get_rosters, get_players,
    get_transactions, format_txn_lines, bsky_post_many, ny_day_bounds
)


def infer_position(pid: str, players: dict) -> str:
    return players.get(pid, {}).get("position") or players.get(pid, {}).get("fantasy_positions", ["?"])[0] or "?"


def main():
    # Wednesday 8pm ET guard (Mon=0 -> Wed=2)
    if not is_now_ny(20, dow=2):
        print("Skipping: not Wed 8pm New York time.")
        return

    league_id = os.getenv("SLEEPER_LEAGUE_ID")
    handle = os.getenv("BSKY_HANDLE")
    app_pw  = os.getenv("BSKY_APP_PASSWORD")
    if not all([league_id, handle, app_pw]):
        print("Missing env vars", file=sys.stderr)
        sys.exit(1)

    week = get_current_week()
    users = get_league_users(league_id)
    owner_by_roster, teamname_by_roster = get_rosters(league_id)
    players = get_players()
    txns = get_transactions(league_id, week)

    # Past 7 days window (NY time)
    start_ms, _ = ny_day_bounds(days_back=7)
    # Build simple heuristics
    adds_pos = defaultdict(Counter)
    drops_pos = defaultdict(Counter)
    trades = Counter()

    for t in txns:
        created = int(t.get("created", 0) or 0)
        if created < start_ms:
            continue
        status = t.get("status")
        if status not in (None, "complete", "processed"):
            continue
        ttype = t.get("type")
        roster_ids = [str(r) for r in (t.get("roster_ids") or [])]
        if not roster_ids:
            continue
        rid = roster_ids[0]

        if ttype in {"waiver","free_agent","waivers","add"}:
            for pid in (t.get("adds") or {}).keys():
                adds_pos[rid][infer_position(pid, players)] += 1
        if ttype in {"waiver","free_agent","waivers","drop"}:
            for pid in (t.get("drops") or {}).keys():
                drops_pos[rid][infer_position(pid, players)] += 1
        if ttype == "trade":
            trades[rid] += 1
            if len(roster_ids) > 1:
                trades[roster_ids[1]] += 1

    lines = ["Rumor Central (last 7 days):"]
    for rid, pos_counts in adds_pos.items():
        for pos, n in pos_counts.items():
            if n >= 3:
                lines.append(f"Sources: {rid} kicked the tires on {pos} (≥{n} adds). Market watch.")
    for rid, pos_counts in drops_pos.items():
        for pos, n in pos_counts.items():
            if n >= 3:
                lines.append(f"Whispers: {rid} churning depth at {pos} (≥{n} drops).")
    for rid, n in trades.items():
        if n >= 1:
            lines.append(f"Front office buzz: {rid} completed {n} trade(s) — more calls likely.")

    if len(lines) == 1:
        lines.append("Quiet week. GMs playing it close to the vest.")

    bsky_post_many(handle, app_pw, lines)
    print(f"Posted weekly rumor note with {len(lines)-1} insight line(s).")


if __name__ == "__main__":
    main()
