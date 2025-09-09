import os, sys, json, time
from typing import Dict, List, Tuple, Set
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests

SLEEPER_API = "https://api.sleeper.app/v1"
DRY_RUN = os.getenv("DRY_RUN") == "1"
DEBUG   = os.getenv("DEBUG") == "1"

# -------- Time helpers (NY guard) --------
def is_now_ny(hour: int, dow: int | None = None) -> bool:
    """True if America/New_York local time matches hour (0-23) and optional weekday Mon=0..Sun=6."""
    now = datetime.now(ZoneInfo("America/New_York"))
    if dow is not None and now.weekday() != dow:
        return False
    return now.hour == hour

def ny_day_bounds(days_back: int = 0) -> Tuple[int,int]:
    tz = ZoneInfo("America/New_York")
    now_ny = datetime.now(tz)
    target = (now_ny - timedelta(days=days_back)).replace(hour=0, minute=0, second=0, microsecond=0)
    start = int(target.timestamp() * 1000)
    end = int((target + timedelta(days=1)).timestamp() * 1000)
    return start, end

# -------- Bluesky --------
def bsky_post_many(handle: str, app_password: str, posts: List[str]) -> None:
    if not posts:
        return
    if DRY_RUN:
        print("\n--- DRY RUN (would post) ---")
        for p in posts:
            print(p[:300]); print("----------------------------")
        return
    from atproto import Client
    client = Client()
    client.login(handle, app_password)
    for p in posts:
        client.send_post(text=(p[:300] if len(p) > 300 else p))
        time.sleep(1.0)

# -------- Sleeper API --------
def get_current_week() -> int:
    r = requests.get(f"{SLEEPER_API}/state/nfl", timeout=15)
    r.raise_for_status()
    return int(r.json().get("week", 0) or 0)

def get_league_users(league_id: str) -> Dict[str, str]:
    r = requests.get(f"{SLEEPER_API}/league/{league_id}/users", timeout=30)
    r.raise_for_status()
    out = {}
    for u in r.json():
        name = (
            u.get("metadata", {}).get("team_name")
            or u.get("display_name")
            or u.get("username")
            or str(u.get("user_id"))
        )
        out[str(u["user_id"])] = name
    return out

def get_rosters(league_id: str) -> Tuple[Dict[str,str], Dict[str,str]]:
    r = requests.get(f"{SLEEPER_API}/league/{league_id}/rosters", timeout=30)
    r.raise_for_status()
    owner_by_roster, teamname_by_roster = {}, {}
    for row in r.json():
        rid = str(row.get("roster_id"))
        owner_by_roster[rid] = str(row.get("owner_id"))
        tn = row.get("metadata", {}).get("team_name")
        if tn:
            teamname_by_roster[rid] = tn
    return owner_by_roster, teamname_by_roster

def get_players() -> Dict[str,dict]:
    r = requests.get(f"{SLEEPER_API}/players/nfl", timeout=60)
    r.raise_for_status()
    return r.json()

def get_transactions(league_id: str, week: int) -> List[dict]:
    r = requests.get(f"{SLEEPER_API}/league/{league_id}/transactions/{week}", timeout=30)
    r.raise_for_status()
    return r.json() or []

# -------- Formatting --------
def team_name_for(roster_id: str, owner_by_roster: Dict[str,str], teamname_by_roster: Dict[str,str], users: Dict[str,str]) -> str:
    if roster_id in teamname_by_roster:
        return teamname_by_roster[roster_id]
    owner_id = owner_by_roster.get(roster_id)
    if owner_id and owner_id in users:
        return users[owner_id]
    return f"Team {roster_id}"

def format_txn_lines(txns: List[dict], players: Dict[str,dict],
                     users: Dict[str,str], owner_by_roster: Dict[str,str],
                     teamname_by_roster: Dict[str,str]) -> List[Tuple[str, str, int]]:
    """
    Returns list of tuples: (txn_id, text, created_ts_ms)
    """
    out: List[Tuple[str,str,int]] = []
    for t in txns:
        status = t.get("status")
        if status not in (None, "complete", "processed"):
            continue
        txn_id = str(t.get("transaction_id", "")) or json.dumps(t, sort_keys=True)[:64]
        created = int(t.get("created", 0) or 0)
        ttype = t.get("type")
        roster_ids = [str(r) for r in (t.get("roster_ids") or [])]
        if ttype in {"waiver","free_agent","waivers","add","drop"}:
            if not roster_ids:
                continue
            rid = roster_ids[0]
            team = team_name_for(rid, owner_by_roster, teamname_by_roster, users)
            adds = t.get("adds") or {}
            drops = t.get("drops") or {}
            add_names  = [players.get(pid, {}).get("full_name", pid) for pid in adds.keys()]
            drop_names = [players.get(pid, {}).get("full_name", pid) for pid in drops.keys()]
            if add_names and drop_names:
                out.append((txn_id, f"Beat Reporter: {team} added {', '.join(add_names)} and dropped {', '.join(drop_names)}.", created))
            elif add_names:
                out.append((txn_id, f"Beat Reporter: {team} added {', '.join(add_names)}.", created))
            elif drop_names:
                out.append((txn_id, f"Beat Reporter: {team} dropped {', '.join(drop_names)}.", created))
        elif ttype == "trade":
            if len(roster_ids) < 2:
                continue
            rid_a, rid_b = roster_ids[0], roster_ids[1]
            team_a = team_name_for(rid_a, owner_by_roster, teamname_by_roster, users)
            team_b = team_name_for(rid_b, owner_by_roster, teamname_by_roster, users)
            adds = t.get("adds") or {}  # pid -> to_roster_id
            a_recv, b_recv = [], []
            for pid, to_r in adds.items():
                name = players.get(pid, {}).get("full_name", pid)
                if str(to_r) == rid_a: a_recv.append(name)
                elif str(to_r) == rid_b: b_recv.append(name)
            parts = []
            if a_recv: parts.append(f"{team_a} receive {', '.join(a_recv)} from {team_b}")
            if b_recv: parts.append(f"{team_b} receive {', '.join(b_recv)} from {team_a}")
            if parts:
                out.append((txn_id, "SPECIAL ALERT: Trade finalized — " + "; ".join(parts) + ".", created))
    return out

# -------- Gist state (de-dupe) --------
def _gist_headers():
    tok = os.getenv("GH_TOKEN")
    return {"Authorization": f"token {tok}"} if tok else {}

def state_load() -> Set[str]:
    tok = os.getenv("GH_TOKEN"); gid = os.getenv("GH_GIST_ID")
    if not tok or not gid: return set()
    try:
        gr = requests.get(f"https://api.github.com/gists/{gid}", headers=_gist_headers(), timeout=20)
        gr.raise_for_status()
        files = gr.json().get("files", {})
        content = files.get("state.json", {}).get("content", "")
        return set(json.loads(content).get("posted_ids", [])) if content else set()
    except Exception as e:
        print(f"State load skipped: {e}", file=sys.stderr); return set()

def state_save(posted_ids: Set[str]) -> None:
    tok = os.getenv("GH_TOKEN"); gid = os.getenv("GH_GIST_ID")
    if not tok: return
    payload = {"files": {"state.json": {"content": json.dumps({"posted_ids": sorted(list(posted_ids))}, indent=2)}}}
    try:
        if gid:
            r = requests.patch(f"https://api.github.com/gists/{gid}", headers=_gist_headers(), json=payload, timeout=20)
            r.raise_for_status()
        else:
            create = {"description": "SFFL Beat Reporter state", "public": False, "files": payload["files"]}
            r = requests.post("https://api.github.com/gists", headers=_gist_headers(), json=create, timeout=20)
            r.raise_for_status()
            new_id = r.json().get("id")
            print(f"Created Gist state store: {new_id}")
            os.environ["GH_GIST_ID"] = new_id
    except Exception as e:
        print(f"State save skipped: {e}", file=sys.stderr)
