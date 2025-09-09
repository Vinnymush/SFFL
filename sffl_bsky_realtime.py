import os, sys
from sffl_common import (
    get_current_week, get_league_users, get_rosters, get_players, get_transactions,
    format_txn_lines, bsky_post_many, state_load, state_save,
    players_cache_load, players_cache_save
)


def main():
    league_id = os.getenv("SLEEPER_LEAGUE_ID")
    handle = os.getenv("BSKY_HANDLE")
    app_pw  = os.getenv("BSKY_APP_PASSWORD")
    if not all([league_id, handle, app_pw]):
        print("Missing env vars", file=sys.stderr)
        sys.exit(1)

    week = get_current_week()
    # Pull transactions first
    txns = get_transactions(league_id, week)
    if not txns:
        print("No transactions present.")
        return

    seen = state_load()
    candidate_ids = {str(t.get("transaction_id", "")) for t in txns if t.get("status") in (None, "complete", "processed")}
    if not any((tid and tid not in seen) for tid in candidate_ids):
        print("No new transactions to post.")
        return

    users = get_league_users(league_id)
    owner_by_roster, teamname_by_roster = get_rosters(league_id)

    players = players_cache_load(max_age_hours=24)
    if players is None:
        players = get_players()
        players_cache_save(players)

    pairs = format_txn_lines(txns, players, users, owner_by_roster, teamname_by_roster)
    new = [(tid, txt) for (tid, txt, _ts) in pairs if tid and tid not in seen]
    if not new:
        print("No new transactions after formatting.")
        return

    to_post = [txt for (_tid, txt) in sorted(new, key=lambda x: x[0])]
    bsky_post_many(handle, app_pw, to_post)

    for tid, _ in new:
        seen.add(tid)
    state_save(seen)
    print(f"Posted {len(to_post)} update(s).")


if __name__ == "__main__":
    main()
