from __future__ import annotations

from sqlalchemy import Engine, text


def _has_column(conn, table: str, column: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return any(r[1] == column for r in rows)  # r[1] = name


def _has_table(conn, table: str) -> bool:
    row = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:t"),
        {"t": table},
    ).fetchone()
    return row is not None


def migrate_sqlite(engine: Engine) -> None:
    """
    Minimal, idempotent SQLite migrations for the demo.
    Keeps the project beginner-friendly (no Alembic yet).
    """
    with engine.begin() as conn:
        # Stage: likes + replies
        if _has_table(conn, "comments"):
            if not _has_column(conn, "comments", "like_count"):
                conn.execute(text("ALTER TABLE comments ADD COLUMN like_count INTEGER NOT NULL DEFAULT 0"))
            if not _has_column(conn, "comments", "parent_comment_id"):
                conn.execute(text("ALTER TABLE comments ADD COLUMN parent_comment_id INTEGER NULL"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_comments_parent_comment_id ON comments (parent_comment_id)"))

        # moderation_results.policy_version (added in stage 2/3)
        if _has_table(conn, "moderation_results") and not _has_column(conn, "moderation_results", "policy_version"):
            conn.execute(text("ALTER TABLE moderation_results ADD COLUMN policy_version VARCHAR(32) DEFAULT 'policy_v0_1_rules'"))

        # Stage 5/6: moderation LLM + severity band fields
        if _has_table(conn, "moderation_results"):
            if not _has_column(conn, "moderation_results", "severity"):
                conn.execute(text("ALTER TABLE moderation_results ADD COLUMN severity VARCHAR(3) DEFAULT 'MED'"))
            if not _has_column(conn, "moderation_results", "llm_used"):
                conn.execute(text("ALTER TABLE moderation_results ADD COLUMN llm_used BOOLEAN DEFAULT 0"))
            if not _has_column(conn, "moderation_results", "llm_model"):
                conn.execute(text("ALTER TABLE moderation_results ADD COLUMN llm_model VARCHAR(128)"))
            if not _has_column(conn, "moderation_results", "llm_error"):
                conn.execute(text("ALTER TABLE moderation_results ADD COLUMN llm_error VARCHAR(256)"))

        # Stage B+Passkey: user profile fields
        if _has_table(conn, "users"):
            if not _has_column(conn, "users", "avatar_url"):
                conn.execute(text("ALTER TABLE users ADD COLUMN avatar_url VARCHAR(512) DEFAULT ''"))
            if not _has_column(conn, "users", "gender"):
                conn.execute(text("ALTER TABLE users ADD COLUMN gender VARCHAR(16) DEFAULT ''"))
            if not _has_column(conn, "users", "fandom"):
                conn.execute(text("ALTER TABLE users ADD COLUMN fandom VARCHAR(64) DEFAULT ''"))

        # new tables
        if not _has_table(conn, "penalty_events"):
            conn.execute(
                text(
                    """
                    CREATE TABLE penalty_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        comment_id INTEGER NULL,
                        type VARCHAR(32) NOT NULL,
                        delta_strikes INTEGER NOT NULL DEFAULT 0,
                        reason VARCHAR(256) NOT NULL DEFAULT '',
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY(user_id) REFERENCES users(id),
                        FOREIGN KEY(comment_id) REFERENCES comments(id)
                    )
                    """
                )
            )
            conn.execute(text("CREATE INDEX ix_penalty_events_user_id ON penalty_events (user_id)"))
            conn.execute(text("CREATE INDEX ix_penalty_events_comment_id ON penalty_events (comment_id)"))

        if not _has_table(conn, "moderation_overrides"):
            conn.execute(
                text(
                    """
                    CREATE TABLE moderation_overrides (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        comment_id INTEGER NOT NULL,
                        previous_action VARCHAR(16) NOT NULL,
                        new_action VARCHAR(16) NOT NULL,
                        moderator VARCHAR(64) NOT NULL DEFAULT 'admin',
                        reason TEXT NOT NULL DEFAULT '',
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY(comment_id) REFERENCES comments(id)
                    )
                    """
                )
            )
            conn.execute(text("CREATE INDEX ix_moderation_overrides_comment_id ON moderation_overrides (comment_id)"))

        if not _has_table(conn, "llm_call_logs"):
            conn.execute(
                text(
                    """
                    CREATE TABLE llm_call_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        comment_id INTEGER NOT NULL,
                        user_id INTEGER NOT NULL,
                        model VARCHAR(128) NOT NULL DEFAULT '',
                        ok BOOLEAN NOT NULL DEFAULT 0,
                        http_status INTEGER NULL,
                        error VARCHAR(512) NULL,
                        latency_ms INTEGER NULL,
                        response_json TEXT NOT NULL DEFAULT '',
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY(comment_id) REFERENCES comments(id),
                        FOREIGN KEY(user_id) REFERENCES users(id)
                    )
                    """
                )
            )
            conn.execute(text("CREATE INDEX ix_llm_call_logs_comment_id ON llm_call_logs (comment_id)"))
            conn.execute(text("CREATE INDEX ix_llm_call_logs_user_id ON llm_call_logs (user_id)"))

        if not _has_table(conn, "comment_translations"):
            conn.execute(
                text(
                    """
                    CREATE TABLE comment_translations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        comment_id INTEGER NOT NULL,
                        source_lang VARCHAR(8) NOT NULL DEFAULT 'unknown',
                        target_lang VARCHAR(8) NOT NULL,
                        translated_text TEXT NOT NULL DEFAULT '',
                        model VARCHAR(128) NOT NULL DEFAULT '',
                        ok BOOLEAN NOT NULL DEFAULT 1,
                        error VARCHAR(512) NOT NULL DEFAULT '',
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY(comment_id) REFERENCES comments(id)
                    )
                    """
                )
            )
            conn.execute(text("CREATE INDEX ix_comment_translations_comment_id ON comment_translations (comment_id)"))
            conn.execute(text("CREATE INDEX ix_comment_translations_target_lang ON comment_translations (target_lang)"))

        # WebAuthn removed: no login/passkey in this demo

