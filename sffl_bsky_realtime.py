import os, sys
from sffl_common import (
    get_current_week, get_league_users, get_rosters, get_players, get_transactions,
    format_txn_lines, bsky_post_many, state_load, state_save
)

def main():
    league_id = os.getenv("SLEEPER_LEAGUE_ID")
    handle = os.getenv("BSKY_HANDLE")
    app_pw  = os.getenv("BSKY_APP_PASSWORD")
    if not all([league_id, handle, app_pw]):
        print("Missing env vars", file=sys.stderr); sys.exit(1)

    week = get_current_week()
    users = get_league_users(league_id)
    owner_by_roster, teamname_by_roster = get_rosters(league_id)
    players = get_players()
    txns = get_transactions(league_id, week)

    pairs = format_txn_lines(txns, players, users, owner_by_roster, teamname_by_roster)  # (id, text, created)
    seen = state_load()
    new = [(tid, txt) for (tid, txt, _ts) in pairs if tid not in seen]
    if not new:
        print("No new transactions."); return

    # Oldest first for narrative order
    to_post = [txt for (_tid, txt) in sorted(new, key=lambda x: x[0])]
    bsky_post_many(handle, app_pw, to_post)

    for tid, _ in new:
        seen.add(tid)
    state_save(seen)
    print(f"Posted {len(to_post)} update(s).")

if __name__ == "__main__":
    main()
