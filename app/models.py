from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, LargeBinary, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class ModerationAction(str, enum.Enum):
    allow = "ALLOW"
    hide = "HIDE"
    delete = "DELETE"
    warn = "WARN"
    mute = "MUTE"
    ban = "BAN"
    review = "REVIEW"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    avatar_url: Mapped[str] = mapped_column(String(512), default="")
    gender: Mapped[str] = mapped_column(String(16), default="")  # 女/男/其他/不透露
    fandom: Mapped[str] = mapped_column(String(64), default="")  # 粉籍（可选）
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    strikes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    comments: Mapped[list["Comment"]] = relationship(back_populates="user")
    penalties: Mapped[list["PenaltyEvent"]] = relationship(back_populates="user")
    # No login system in this demo; everyone is a guest commenter.


class CommentStatus(str, enum.Enum):
    visible = "VISIBLE"
    hidden = "HIDDEN"
    deleted = "DELETED"


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    parent_comment_id: Mapped[int | None] = mapped_column(
        ForeignKey("comments.id"), nullable=True, index=True, default=None
    )
    content: Mapped[str] = mapped_column(Text)
    lang: Mapped[str] = mapped_column(String(8), default="unknown")
    status: Mapped[CommentStatus] = mapped_column(Enum(CommentStatus), default=CommentStatus.visible)
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="comments")
    moderation: Mapped["ModerationResult"] = relationship(back_populates="comment", uselist=False)
    overrides: Mapped[list["ModerationOverride"]] = relationship(back_populates="comment")

    parent: Mapped["Comment | None"] = relationship(remote_side="Comment.id", backref="replies")


class ModerationResult(Base):
    __tablename__ = "moderation_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    comment_id: Mapped[int] = mapped_column(ForeignKey("comments.id"), unique=True, index=True)
    action: Mapped[ModerationAction] = mapped_column(Enum(ModerationAction))
    risk_score: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    severity: Mapped[str] = mapped_column(String(3), default="MED")  # LOW/MED/HIGH
    llm_used: Mapped[bool] = mapped_column(Boolean, default=False)
    llm_model: Mapped[str | None] = mapped_column(String(128), nullable=True, default=None)
    llm_error: Mapped[str | None] = mapped_column(String(256), nullable=True, default=None)
    categories: Mapped[str] = mapped_column(String(256), default="")  # comma-separated
    evidence: Mapped[str] = mapped_column(Text, default="")
    rationale: Mapped[str] = mapped_column(Text, default="")
    policy_version: Mapped[str] = mapped_column(String(32), default="policy_v0_1_rules")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    comment: Mapped["Comment"] = relationship(back_populates="moderation")


class PenaltyType(str, enum.Enum):
    strike_added = "STRIKE_ADDED"
    banned = "BANNED"
    unbanned = "UNBANNED"
    strike_removed = "STRIKE_REMOVED"


class PenaltyEvent(Base):
    __tablename__ = "penalty_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    comment_id: Mapped[int | None] = mapped_column(ForeignKey("comments.id"), nullable=True, index=True)
    type: Mapped[PenaltyType] = mapped_column(Enum(PenaltyType))
    delta_strikes: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="penalties")


class LlmCallLog(Base):
    __tablename__ = "llm_call_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    comment_id: Mapped[int] = mapped_column(ForeignKey("comments.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    model: Mapped[str] = mapped_column(String(128), default="")
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    error: Mapped[str | None] = mapped_column(String(512), nullable=True, default=None)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    response_json: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModerationOverride(Base):
    __tablename__ = "moderation_overrides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    comment_id: Mapped[int] = mapped_column(ForeignKey("comments.id"), index=True)
    previous_action: Mapped[ModerationAction] = mapped_column(Enum(ModerationAction))
    new_action: Mapped[ModerationAction] = mapped_column(Enum(ModerationAction))
    moderator: Mapped[str] = mapped_column(String(64), default="admin")
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    comment: Mapped["Comment"] = relationship(back_populates="overrides")


class CommentTranslation(Base):
    __tablename__ = "comment_translations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    comment_id: Mapped[int] = mapped_column(ForeignKey("comments.id"), index=True)
    source_lang: Mapped[str] = mapped_column(String(8), default="unknown")
    target_lang: Mapped[str] = mapped_column(String(8), index=True)
    translated_text: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String(128), default="")
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


