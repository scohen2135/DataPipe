import os
import ssl
from collections import defaultdict
from urllib.parse import urlparse

import pg8000.dbapi

_PLAYER_FIELDS = ("name", "min", "pts", "reb", "ast", "stl", "blk", "plus_minus")


def _ssl_context():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def get_conn():
    p = urlparse(os.environ["DATABASE_URL"])
    return pg8000.dbapi.connect(
        host=p.hostname,
        database=p.path.lstrip("/"),
        user=p.username,
        password=p.password,
        port=p.port or 5432,
        ssl_context=_ssl_context(),
    )


def _fetchall_dicts(cursor):
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def existing_game_ids(conn):
    cur = conn.cursor()
    cur.execute("SELECT game_id FROM games")
    return {row[0] for row in cur.fetchall()}


def insert_game(conn, record):
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO games (game_id, title, date, venue, away_team, home_team,
                           away_score, home_score, series, source)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (game_id) DO NOTHING
        """,
        (
            record["game_id"], record["title"], record["date"], record["venue"],
            record["away_team"], record["home_team"], record["away_score"],
            record["home_score"], record["series"], record["source"],
        ),
    )
    for side in ("away", "home"):
        for p in record[f"{side}_players"]:
            cur.execute(
                """
                INSERT INTO players (game_id, side, name, min, pts, reb, ast, stl, blk, plus_minus)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    record["game_id"], side,
                    p["name"], p["min"], p["pts"], p["reb"],
                    p["ast"], p["stl"], p["blk"], p["plus_minus"],
                ),
            )
    conn.commit()


def load_all_games(conn):
    cur = conn.cursor()
    cur.execute("SELECT * FROM games ORDER BY date DESC, game_id")
    games = _fetchall_dicts(cur)

    cur.execute("SELECT * FROM players")
    all_players = _fetchall_dicts(cur)

    by_game = defaultdict(lambda: {"away": [], "home": []})
    for p in all_players:
        by_game[p["game_id"]][p["side"]].append({k: p[k] for k in _PLAYER_FIELDS})

    for g in games:
        g["away_players"] = by_game[g["game_id"]]["away"]
        g["home_players"] = by_game[g["game_id"]]["home"]
        g["date"] = str(g["date"])

    return games
