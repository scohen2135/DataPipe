"""One-time migration: load existing games.json into the database."""
import json
from pathlib import Path
from dotenv import load_dotenv
import db

load_dotenv()

DATA_FILE = Path(__file__).parent / "data" / "games.json"

with open(DATA_FILE) as f:
    data = json.load(f)

conn = db.get_conn()
try:
    for record in data["games"]:
        db.insert_game(conn, record)
        print(f"Inserted: {record['title']}")
    print(f"\nMigration complete. {len(data['games'])} game(s) loaded.")
finally:
    conn.close()
