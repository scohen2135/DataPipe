"""
DataPipe NBA pipeline
Fetches completed games from yesterday via ESPN APIs, writes to PostgreSQL.
Runs daily via Windows Task Scheduler.

Flow:
  1. ESPN scoreboard API  → all games for a date + their IDs + completion status
  2. ESPN summary API     → full box score for each new game
  3. Insert into database
"""

import logging
from datetime import date, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

import db

load_dotenv()

LOG_FILE     = Path(__file__).parent / "pipeline.log"
ESPN_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ---- Data helpers ----

def safe_int(val, default=0):
    """Convert any scalar to int regardless of whether ESPN returns a str, float, int, or None."""
    try:
        return int(val) if val is not None else default
    except (ValueError, TypeError):
        return default


# ---- Step 1: get completed games for a date from ESPN scoreboard ----

def fetch_completed_games(for_date: date):
    """Returns list of (espn_game_id, away_name, home_name) for all final games."""
    date_str = for_date.strftime("%Y%m%d")
    url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={date_str}"
    resp = requests.get(url, headers=ESPN_HEADERS, timeout=20)
    resp.raise_for_status()

    games = []
    for event in resp.json().get("events", []):
        try:
            status = event.get("status", {}).get("type", {})
            if not status.get("completed", False):
                continue
            competitors = event["competitions"][0]["competitors"]
            teams = {c["homeAway"]: c["team"]["displayName"] for c in competitors}
            games.append({
                "espn_id":   event["id"],
                "away_name": teams.get("away", ""),
                "home_name": teams.get("home", ""),
            })
        except Exception:
            log.warning(f"Skipping malformed scoreboard event {event.get('id', '?')}")
    return games


# ---- Step 2: fetch full box score from ESPN summary API ----

def fetch_espn_summary(espn_id: str):
    url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={espn_id}"
    resp = requests.get(url, headers=ESPN_HEADERS, timeout=20)
    resp.raise_for_status()
    return resp.json()


# ---- Step 3: parse ESPN summary into our schema ----

def parse_players(team_block):
    players = []
    if not team_block or not team_block.get("statistics"):
        return players

    stats_section = team_block["statistics"][0]
    if not isinstance(stats_section, dict):
        return players

    # Labels may be plain strings or dicts with a "name" key depending on API version
    raw_labels = stats_section.get("labels", [])
    col_names = [s if isinstance(s, str) else s.get("name", "") for s in raw_labels]

    for entry in stats_section.get("athletes", []):
        try:
            if entry.get("didNotPlay"):
                continue
            raw = dict(zip(col_names, entry.get("stats", [])))
            players.append({
                "name":       entry.get("athlete", {}).get("displayName", "Unknown"),
                "min":        safe_int(raw.get("MIN")),
                "pts":        safe_int(raw.get("PTS")),
                "reb":        safe_int(raw.get("REB")),
                "ast":        safe_int(raw.get("AST")),
                "stl":        safe_int(raw.get("STL")),
                "blk":        safe_int(raw.get("BLK")),
                "plus_minus": safe_int(raw.get("+/-")),
            })
        except Exception:
            log.warning(f"Skipping malformed player entry: {entry.get('athlete', {}).get('displayName', '?')}")
    return players


def build_record(espn_data, game_date: str):
    competition = espn_data["header"]["competitions"][0]
    competitors = {c["homeAway"]: c for c in competition.get("competitors", [])}
    home = competitors["home"]
    away = competitors["away"]

    notes     = competition.get("notes", [])
    series    = notes[0].get("headline", "") if notes else ""
    venue_info = espn_data.get("gameInfo", {}).get("venue", {})
    venue_name = venue_info.get("fullName", "")
    address    = venue_info.get("address", {})
    venue_str  = f"{venue_name}, {address.get('city', '')} {address.get('state', '')}".strip(", ")

    home_block, away_block = None, None
    for block in espn_data.get("boxscore", {}).get("players", []):
        if block["team"]["id"] == home["team"]["id"]:
            home_block = block
        else:
            away_block = block

    away_name = away["team"]["displayName"]
    home_name = home["team"]["displayName"]

    return {
        "game_id":      competition["id"],
        "title":        f"{away_name} @ {home_name} -- {game_date}",
        "date":         game_date,
        "venue":        venue_str,
        "away_team":    away_name,
        "home_team":    home_name,
        "away_score":   safe_int(away.get("score")),
        "home_score":   safe_int(home.get("score")),
        "series":       series,
        "source":       "ESPN",
        "away_players": parse_players(away_block) if away_block else [],
        "home_players": parse_players(home_block) if home_block else [],
    }


# ---- Main ----

def run(target_date: date = None):
    if target_date is None:
        target_date = date.today() - timedelta(days=1)

    log.info(f"Pipeline started -- fetching games for {target_date}")

    conn = db.get_conn()
    try:
        seen  = db.existing_game_ids(conn)
        games = fetch_completed_games(target_date)

        if not games:
            log.info("No completed games found -- nothing to do.")
            return

        added = 0
        for g in games:
            log.info(f"Processing: {g['away_name']} @ {g['home_name']}")

            if g["espn_id"] in seen:
                log.info(f"  Already in database -- skipping.")
                continue

            try:
                espn_data = fetch_espn_summary(g["espn_id"])
                record    = build_record(espn_data, target_date.isoformat())
                db.insert_game(conn, record)
                seen.add(g["espn_id"])
                added += 1
                log.info(f"  Added: {record['away_team']} {record['away_score']} @ "
                         f"{record['home_team']} {record['home_score']}")
            except Exception:
                conn.rollback()
                log.exception(f"  Failed to process game {g['espn_id']} -- skipping.")

        if added:
            log.info(f"Inserted {added} new game(s) into database.")
        else:
            log.info("No new games added.")

        log.info("Pipeline complete.")
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        run()
    except Exception:
        log.exception("Pipeline crashed")
