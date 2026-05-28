import os

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from pathlib import Path

import db

load_dotenv()

st.set_page_config(
    page_title="NBA Stat Leaders",
    page_icon="🏀",
    layout="wide"
)

# ---- Password gate ----
def check_password():
    if st.session_state.get("authenticated"):
        return True
    st.markdown("## 🏀 NBA Stat Leaders")
    st.divider()
    pwd = st.text_input("Password", type="password")
    if st.button("Login"):
        if pwd == os.environ.get("APP_PASSWORD", ""):
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    return False

if not check_password():
    st.stop()

TEAM_COLORS = {
    "New York Knicks":         "#003DA5",
    "Cleveland Cavaliers":     "#6F263D",
    "Oklahoma City Thunder":   "#002B5C",
    "San Antonio Spurs":       "#1a1a1a",
}

STATS = [
    ("pts",        "Points"),
    ("reb",        "Rebounds"),
    ("ast",        "Assists"),
    ("stl",        "Steals"),
    ("blk",        "Blocks"),
    ("plus_minus", "+/-"),
]

@st.cache_data(ttl=300)
def load_games():
    conn = db.get_conn()
    try:
        return db.load_all_games(conn)
    finally:
        conn.close()

def pipeline_status():
    """Return (level, message) for the most recent pipeline run, or (None, None) if clean."""
    log_path = Path(__file__).parent / "pipeline.log"
    if not log_path.exists():
        return None, None

    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()

    last_start = max((i for i, l in enumerate(lines) if "Pipeline started" in l), default=-1)
    if last_start == -1:
        return None, None

    run_lines = lines[last_start:]
    run_date  = run_lines[0][:10]
    completed = any("Pipeline complete" in l for l in run_lines)
    errors    = [l.split("  ERROR  ", 1)[-1] for l in run_lines if "  ERROR  " in l]
    warnings  = [l.split("  WARNING  ", 1)[-1] for l in run_lines if "  WARNING  " in l]

    if errors:
        return "error", f"Pipeline error on {run_date}: {errors[0]}"
    if not completed:
        return "error", f"Pipeline did not complete on {run_date} -- data may be stale."
    if warnings:
        return "warning", f"Pipeline warning on {run_date}: {warnings[0]}"
    return None, None

def team_header(name, score, color):
    st.markdown(
        f"<div style='background:{color};padding:14px 18px;border-radius:8px;margin-bottom:14px'>"
        f"<span style='color:white;font-size:20px;font-weight:700'>{name}</span>"
        f"<span style='color:white;font-size:26px;font-weight:800;float:right'>{score}</span>"
        f"</div>",
        unsafe_allow_html=True
    )

def stat_card(label, player_name, value, color):
    st.markdown(
        f"<div style='border-left:5px solid {color};padding:10px 14px;margin-bottom:10px;"
        f"background:#f8f9fa;border-radius:0 8px 8px 0'>"
        f"<div style='font-size:11px;color:#999;text-transform:uppercase;letter-spacing:1px;margin-bottom:2px'>{label}</div>"
        f"<div style='font-size:17px;font-weight:600;color:#1a1a1a'>{player_name}</div>"
        f"<div style='font-size:28px;font-weight:800;color:{color};line-height:1.1'>{value}</div>"
        f"</div>",
        unsafe_allow_html=True
    )

# ---- Header ----
st.markdown("## 🏀 NBA Stat Leaders")
st.caption("Stat leader for each category, per team, per game")
st.divider()

# ---- Pipeline health alert ----
_status_level, _status_msg = pipeline_status()
if _status_level == "error":
    st.error(_status_msg)
elif _status_level == "warning":
    st.warning(_status_msg)

# ---- Game selector ----
games = load_games()
labels = [
    f"{g['date']}  |  {g['away_team']} @ {g['home_team']}  "
    f"({g['away_score']}-{g['home_score']})  |  {g['title']}"
    for g in games
]
selected = st.selectbox("Select Game", range(len(labels)), format_func=lambda i: labels[i])
game = games[selected]

# ---- Game subtitle ----
col_info, _ = st.columns([3, 1])
with col_info:
    st.markdown(
        f"**{game['title']}**  &nbsp;|&nbsp;  {game['venue']}  &nbsp;|&nbsp;  "
        f"Series: {game['series']}"
    )
st.divider()

# ---- Build DataFrames ----
away_df = pd.DataFrame(game["away_players"])
home_df = pd.DataFrame(game["home_players"])

away_color = TEAM_COLORS.get(game["away_team"], "#333")
home_color = TEAM_COLORS.get(game["home_team"], "#333")

# ---- Two-column stat leaders ----
col_away, col_home = st.columns(2)

with col_away:
    team_header(game["away_team"], game["away_score"], away_color)
    for stat_key, stat_label in STATS:
        row = away_df.loc[away_df[stat_key].idxmax()]
        stat_card(stat_label, row["name"], row[stat_key], away_color)

with col_home:
    team_header(game["home_team"], game["home_score"], home_color)
    for stat_key, stat_label in STATS:
        row = home_df.loc[home_df[stat_key].idxmax()]
        stat_card(stat_label, row["name"], row[stat_key], home_color)

st.divider()
st.caption(f"Source: {game.get('source', 'ESPN')}  |  Game date: {game['date']}")
