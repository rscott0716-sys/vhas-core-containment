import sqlite3
from pathlib import Path
from datetime import datetime, timezone


class VHASMemory:
    def __init__(self, database_path=None):
        if database_path is None:
            database_path = Path(__file__).resolve().parent / "vhas_memory.db"

        self.database_path = str(database_path)
        self.initialize_database()

    def initialize_database(self):
        with sqlite3.connect(self.database_path) as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    message TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
            """)

    def save_message(self, role, message):
        if role not in ("user", "assistant"):
            raise ValueError("Invalid conversation role.")

        if not isinstance(message, str):
            raise TypeError("Message must be text.")

        timestamp = datetime.now(timezone.utc).isoformat()

        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO conversations (role, message, timestamp)
                VALUES (?, ?, ?)
                """,
                (role, message, timestamp)
            )

    def get_recent_messages(self, limit=10):
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("Limit must be a positive integer.")

        with sqlite3.connect(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT role, message, timestamp
                FROM conversations
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,)
            ).fetchall()

        return [
            {"role": role, "message": message, "timestamp": timestamp}
            for role, message, timestamp in reversed(rows)
        ]

    def clear_memory(self):
        with sqlite3.connect(self.database_path) as connection:
            connection.execute("DELETE FROM conversations")

