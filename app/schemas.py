from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class CommentCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    content: str = Field(min_length=1, max_length=5000)
    parent_comment_id: int | None = Field(default=None, ge=1)


class AtmosphereOut(BaseModel):
    label: Literal["友好", "中性", "紧张"]
    reply_total: int
    hidden_or_deleted: int
    high_risk: int


class UserOut(BaseModel):
    id: int
    username: str
    avatar_url: str = ""
    gender: str = ""
    fandom: str = ""
    is_banned: bool
    strikes: int
    created_at: datetime


class ModerationOut(BaseModel):
    action: Literal["ALLOW", "HIDE", "DELETE", "WARN", "MUTE", "BAN", "REVIEW"]
    risk_score: int
    severity: Literal["LOW", "MED", "HIGH"]
    llm_used: bool = False
    llm_model: str | None = None
    llm_error: str | None = None
    categories: list[str]
    evidence: str
    rationale: str
    created_at: datetime


class CommentOut(BaseModel):
    id: int
    user_id: int
    username: str | None = None
    parent_comment_id: int | None = None
    content: str
    lang: str
    status: Literal["VISIBLE", "HIDDEN", "DELETED"]
    like_count: int = 0
    reply_count: int = 0
    atmosphere: AtmosphereOut | None = None
    created_at: datetime
    moderation: ModerationOut | None = None


class CommentCreateResponse(BaseModel):
    user: UserOut
    comment: CommentOut


class CommentsListResponse(BaseModel):
    total: int
    items: list[CommentOut]


class AdminOverrideRequest(BaseModel):
    new_action: Literal["ALLOW", "HIDE", "DELETE", "WARN", "MUTE", "BAN", "REVIEW"]
    reason: str = Field(default="", max_length=2000)
    moderator: str = Field(default="admin", min_length=1, max_length=64)


class AdminOverrideResponse(BaseModel):
    comment: CommentOut
    user: UserOut


class AdminResetResponse(BaseModel):
    ok: bool
    deleted_comments: int
    deleted_users: int


class UserLookupResponse(BaseModel):
    user: UserOut


class ProfileUpdateRequest(BaseModel):
    avatar_url: str = Field(default="", max_length=512)
    gender: str = Field(default="", max_length=16)
    fandom: str = Field(default="", max_length=64)


class TranslationRequest(BaseModel):
    target_lang: Literal["zh", "en", "ja", "ko", "th"]


class TranslationResponse(BaseModel):
    comment_id: int
    source_lang: str
    target_lang: str
    translated_text: str
    cached: bool
    model: str | None = None
    error: str | None = None


class TextTranslateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    target_lang: Literal["zh", "en", "ja", "ko", "th"]


class TextTranslateResponse(BaseModel):
    target_lang: str
    translated_text: str
    model: str | None = None
    error: str | None = None


class AgentAdviceRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


class AgentAdviceResponse(BaseModel):
    risk_level: Literal["safe", "warning", "toxic"]
    action: Literal["ALLOW", "HIDE", "DELETE", "WARN", "MUTE", "BAN", "REVIEW"]
    risk_score: int
    severity: Literal["LOW", "MED", "HIGH"]
    categories: list[str]
    evidence: str
    rationale: str
    suggestion: str

class PenaltyEventOut(BaseModel):
    id: int
    user_id: int
    comment_id: int | None
    type: Literal["STRIKE_ADDED", "BANNED", "UNBANNED", "STRIKE_REMOVED"]
    delta_strikes: int
    reason: str
    created_at: datetime


class PenaltyEventsListResponse(BaseModel):
    total: int
    items: list[PenaltyEventOut]

