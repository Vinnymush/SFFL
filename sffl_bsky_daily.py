import os, sys
from sffl_common import (
    is_now_ny, get_current_week, get_league_users, get_rosters, get_players,
    get_transactions, format_txn_lines, bsky_post_many, ny_day_bounds
)


def main():
    # 8am ET guard
    if not is_now_ny(8):
        print("Skipping: not 8am New York time.")
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
    pairs = format_txn_lines(txns, players, users, owner_by_roster, teamname_by_roster)  # (id, text, created_ms)

    start_ms, end_ms = ny_day_bounds(days_back=1)  # yesterday
    yday = [txt for (_tid, txt, created) in pairs if start_ms <= created < end_ms]
    if not yday:
        print("No transactions yesterday.")
        return

    posts = ["Daily SFFL Transaction Recap (yesterday):"] + yday
    bsky_post_many(handle, app_pw, posts)
    print(f"Posted daily digest with {len(yday)} item(s).")


if __name__ == "__main__":
    main()
