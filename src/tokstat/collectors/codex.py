# codex.py
"""Codex CLI & VS Code session collector (REAL token usage).

Scans ~/.codex/ state databases (e.g. state_5.sqlite) for the `threads` table,
which records exact token totals (`tokens_used`), model names (`gpt-5.2-codex`),
timestamps, working directories and git metadata.
"""
import datetime
import os
import sqlite3

from .. import config
from .base import BaseCollector

CODEX_DIR = os.path.expanduser("~/.codex")


class CodexCollector(BaseCollector):
    name = "codex"

    def poll(self, bookmark: dict):
        files_state = bookmark.get("files", {})
        new_state = {}
        events = []

        if not os.path.isdir(CODEX_DIR):
            return [], {"files": files_state}

        for fname in os.listdir(CODEX_DIR):
            if fname.startswith("state_") and fname.endswith(".sqlite"):
                path = os.path.join(CODEX_DIR, fname)
                try:
                    mtime = os.path.getmtime(path)
                except OSError:
                    continue

                if files_state.get(path) == mtime:
                    new_state[path] = mtime
                    continue

                parsed_events = self._parse_db(path)
                events.extend(parsed_events)
                new_state[path] = mtime

        return events, {"files": new_state}

    def _parse_db(self, db_path: str) -> list[dict]:
        try:
            conn = sqlite3.connect(db_path, timeout=5)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            tables = [r[0] for r in cursor.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()]
            if "threads" not in tables:
                conn.close()
                return []
            rows = cursor.execute("SELECT * FROM threads;").fetchall()
        except (sqlite3.Error, OSError):
            return []

        events = []
        try:
            for row in rows:
                d = dict(row)
                thread_id = d.get("id")
                tokens_used = d.get("tokens_used") or 0
                if not thread_id or tokens_used <= 0:
                    continue

                created_at_ms = d.get("created_at_ms")
                created_at_sec = d.get("created_at")
                if created_at_ms:
                    ts_sec = created_at_ms / 1000.0
                elif created_at_sec:
                    ts_sec = float(created_at_sec)
                else:
                    continue

                dt = datetime.datetime.fromtimestamp(ts_sec, tz=datetime.timezone.utc)
                occurred_at = dt.isoformat()

                model_raw = d.get("model") or "gpt-5.2-codex"
                provider_id = d.get("model_provider") or "openai"
                source = d.get("source") or "cli"
                agent_name = f"codex_{source}"

                cwd = d.get("cwd") or ""
                workspace_id = os.path.basename(cwd.rstrip("/")) if cwd else "Global/No Project"

                # Split total tokens into input (85%) and output (15%) approximation
                input_tokens = int(tokens_used * 0.85)
                output_tokens = tokens_used - input_tokens

                events.append({
                    "event_id": None,
                    "occurred_at": occurred_at,
                    "provider_id": provider_id,
                    "agent_name": agent_name,
                    "workspace_id": workspace_id,
                    "session_id": str(thread_id),
                    "turn_id": str(thread_id),
                    "event_type": "message_usage",
                    "model_raw": model_raw,
                    "model_canonical": model_raw,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cache_read_tokens": 0,
                    "cache_write_tokens": 0,
                    "total_tokens": tokens_used,
                    "cost_usd": 0.0,
                    "requests": 1,
                    "status": "ok",
                    "dedup_key": f"codex-{thread_id}",
                })
        finally:
            conn.close()

        return events
