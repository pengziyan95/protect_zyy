from __future__ import annotations

import json
import os
from datetime import datetime
from dataclasses import replace
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi import Request
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import delete, update
from fastapi.staticfiles import StaticFiles

from .db import Base, get_db_session, get_engine, make_session_factory
from .migrations import migrate_sqlite
from .metrics import daily_metrics
from .moderation import moderate_text_hybrid
from .models import (
    Comment,
    CommentStatus,
    CommentTranslation,
    LlmCallLog,
    ModerationAction,
    ModerationOverride,
    ModerationResult,
    PenaltyEvent,
    PenaltyType,
    User,
)
from .schemas import (
    AdminOverrideRequest,
    AdminOverrideResponse,
    AdminResetResponse,
    PenaltyEventOut,
    PenaltyEventsListResponse,
    CommentCreate,
    CommentCreateResponse,
    CommentOut,
    CommentsListResponse,
    AtmosphereOut,
    ModerationOut,
    UserOut,
    UserLookupResponse,
    ProfileUpdateRequest,
    TranslationRequest,
    TranslationResponse,
    TextTranslateRequest,
    TextTranslateResponse,
    AgentAdviceRequest,
    AgentAdviceResponse,
)
from .llm_volcengine import load_volc_config, volc_chat_text_traced, VolcengineError

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
SQLITE_PATH = str(DATA_DIR / "protect_zyy.sqlite3")

# Load .env if present (Stage 4: Volcengine config)
load_dotenv(dotenv_path=APP_DIR.parent / ".env", override=False)

engine = get_engine(SQLITE_PATH)
SessionFactory = make_session_factory(engine)
Base.metadata.create_all(bind=engine)
migrate_sqlite(engine)

app = FastAPI(title="protect_zyy", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")

POLICY_VERSION = "policy_v0_2_hybrid"


def db() -> Session:
    yield from get_db_session(SessionFactory)


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "time": datetime.utcnow().isoformat()}


@app.get("/v1/metrics/summary")
def metrics_summary(days: int = Query(default=7, ge=1, le=90)) -> dict:
    return {"days": days, "points": daily_metrics(engine, days=days)}


@app.get("/ui", response_class=HTMLResponse, include_in_schema=False)
def ui() -> str:
    # Minimal, dependency-free UI for demos (no build step)
    return f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>protect_zyy dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
  </head>
  <body class="bg-slate-950 text-slate-100">
    <div class="max-w-5xl mx-auto p-6">
      <div class="flex items-center justify-between gap-4">
        <div>
          <h1 class="text-2xl font-semibold">protect_zyy 风控看板</h1>
          <p class="text-slate-400 text-sm mt-1">本地演示：近 7 天评论量 / 严重度 / LLM 调用成功情况</p>
        </div>
        <a class="text-sm text-sky-300 hover:text-sky-200" href="/docs">OpenAPI 文档 /docs</a>
      </div>

      <div class="mt-6 grid grid-cols-1 md:grid-cols-3 gap-3">
        <div class="rounded-xl border border-slate-800 p-4 bg-slate-900/40">
          <div class="text-xs text-slate-400">说明</div>
          <div class="text-sm mt-2 leading-6">
            <div><span class="text-slate-300">严重度</span>：LOW / MED / HIGH（由风险分映射）</div>
            <div class="mt-2"><span class="text-slate-300">llm_ok</span>：LLM 返回可解析 JSON 且 HTTP 成功</div>
          </div>
        </div>
        <div class="rounded-xl border border-slate-800 p-4 bg-slate-900/40 md:col-span-2">
          <div class="text-xs text-slate-400">快捷操作</div>
          <div class="text-sm mt-2 flex flex-wrap gap-2">
            <a class="px-3 py-1 rounded-lg bg-slate-800 hover:bg-slate-700" href="/v1/metrics/summary?days=7">下载 metrics JSON</a>
            <span class="text-slate-500">建议先 <span class="text-slate-300">POST /v1/admin/demo/reset</span> 再发评论做对比</span>
          </div>
        </div>
      </div>

      <div class="mt-6 overflow-x-auto rounded-xl border border-slate-800">
        <table class="w-full text-sm">
          <thead class="text-left text-slate-300 bg-slate-900/60">
            <tr>
              <th class="p-3">日期</th>
              <th class="p-3">评论</th>
              <th class="p-3">严重度(LOW/MED/HIGH)</th>
              <th class="p-3">LLM 调用</th>
            </tr>
          </thead>
          <tbody id="rows" class="divide-y divide-slate-800"></tbody>
        </table>
      </div>
    </div>
    <script>
      async function load() {{
        const r = await fetch('/v1/metrics/summary?days=7');
        const j = await r.json();
        const tbody = document.getElementById('rows');
        tbody.innerHTML = '';
        for (const p of j.points) {{
          const tr = document.createElement('tr');
          tr.className = 'hover:bg-slate-900/40';
          const sev = p.severities || {{}};
          const sevText = `LOW=${{sev.LOW||0}} / MED=${{sev.MED||0}} / HIGH=${{sev.HIGH||0}}`;
          const okRate = p.llm_calls ? Math.round(100 * p.llm_ok / p.llm_calls) : 0;
          tr.innerHTML = `
            <td class="p-3 font-mono text-slate-200">${{p.day}}</td>
            <td class="p-3">${{p.comments}}</td>
            <td class="p-3 text-slate-200">${{sevText}}</td>
            <td class="p-3 text-slate-200">${{p.llm_calls}} (ok ${{p.llm_ok}}, ${{okRate}}%)</td>
          `;
          tbody.appendChild(tr);
        }}
      }}
      load();
    </script>
  </body>
</html>"""


@app.get("/app", response_class=HTMLResponse, include_in_schema=False)
def app_home() -> str:
    return (APP_DIR / "static" / "app.html").read_text(encoding="utf-8")


def _user_to_out(u: User) -> UserOut:
    return UserOut(
        id=u.id,
        username=u.username,
        avatar_url=getattr(u, "avatar_url", "") or "",
        gender=getattr(u, "gender", "") or "",
        fandom=getattr(u, "fandom", "") or "",
        is_banned=u.is_banned,
        strikes=u.strikes,
        created_at=u.created_at,
    )


def _moderation_to_out(m: ModerationResult) -> ModerationOut:
    cats = [c for c in (m.categories or "").split(",") if c]
    sev = getattr(m, "severity", None) or "MED"
    return ModerationOut(
        action=m.action.value,
        risk_score=m.risk_score,
        severity=sev,
        llm_used=bool(getattr(m, "llm_used", False)),
        llm_model=getattr(m, "llm_model", None),
        llm_error=getattr(m, "llm_error", None),
        categories=cats,
        evidence=m.evidence or "",
        rationale=m.rationale or "",
        created_at=m.created_at,
    )


def _comment_to_out(c: Comment) -> CommentOut:
    return CommentOut(
        id=c.id,
        user_id=c.user_id,
        username=(getattr(getattr(c, "user", None), "username", None) or None),
        parent_comment_id=getattr(c, "parent_comment_id", None),
        content=c.content,
        lang=c.lang,
        status=c.status.value,
        like_count=int(getattr(c, "like_count", 0) or 0),
        created_at=c.created_at,
        moderation=_moderation_to_out(c.moderation) if c.moderation else None,
    )


def _atmosphere_label(reply_total: int, hidden_or_deleted: int, high_risk: int) -> str:
    if reply_total <= 0:
        return "中性"
    # 简单可解释：高风险/被隐藏比例越高，氛围越紧张
    tense_score = (high_risk * 2 + hidden_or_deleted) / max(1, reply_total)
    if tense_score >= 0.8:
        return "紧张"
    if tense_score >= 0.35:
        return "中性"
    return "友好"


def _attach_thread_meta(items: list[CommentOut], db: Session) -> list[CommentOut]:
    """
    For root comments only, attach reply_count and atmosphere summary.
    """
    root_ids = [c.id for c in items if c.parent_comment_id is None]
    if not root_ids:
        return items

    # reply_total per root
    reply_counts = dict(
        db.execute(
            select(Comment.parent_comment_id, func.count(Comment.id))
            .where(Comment.parent_comment_id.in_(root_ids))
            .group_by(Comment.parent_comment_id)
        ).all()
    )

    # hidden/deleted replies per root
    hd_counts = dict(
        db.execute(
            select(Comment.parent_comment_id, func.count(Comment.id))
            .where(
                Comment.parent_comment_id.in_(root_ids),
                Comment.status.in_([CommentStatus.hidden, CommentStatus.deleted]),
            )
            .group_by(Comment.parent_comment_id)
        ).all()
    )

    # high-risk replies per root (severity HIGH OR action BAN/MUTE/WARN)
    hi_counts = dict(
        db.execute(
            select(Comment.parent_comment_id, func.count(Comment.id))
            .join(ModerationResult, ModerationResult.comment_id == Comment.id)
            .where(
                Comment.parent_comment_id.in_(root_ids),
                (ModerationResult.severity == "HIGH")
                | (ModerationResult.action.in_([ModerationAction.warn, ModerationAction.mute, ModerationAction.ban])),
            )
            .group_by(Comment.parent_comment_id)
        ).all()
    )

    for c in items:
        if c.parent_comment_id is not None:
            continue
        reply_total = int(reply_counts.get(c.id, 0) or 0)
        hidden_or_deleted = int(hd_counts.get(c.id, 0) or 0)
        high_risk = int(hi_counts.get(c.id, 0) or 0)
        c.reply_count = reply_total
        c.atmosphere = AtmosphereOut(
            label=_atmosphere_label(reply_total, hidden_or_deleted, high_risk),
            reply_total=reply_total,
            hidden_or_deleted=hidden_or_deleted,
            high_risk=high_risk,
        )
    return items


def _penalty_to_out(p: PenaltyEvent) -> PenaltyEventOut:
    return PenaltyEventOut(
        id=p.id,
        user_id=p.user_id,
        comment_id=p.comment_id,
        type=p.type.value,
        delta_strikes=p.delta_strikes,
        reason=p.reason,
        created_at=p.created_at,
    )

def _require_admin(x_admin_key: str | None) -> None:
    # v0.1：为了让初学者能跑通先不强制鉴权
    # 你后续可以在 .env 设置 ADMIN_KEY 并启用强制校验
    # （阶段 5 会把这块变成真正的登录体系）
    return None


@app.post("/v1/comments", response_model=CommentCreateResponse)
def create_comment(payload: CommentCreate, db: Session = Depends(db)) -> CommentCreateResponse:
    # 1) Find or create user
    user = db.scalar(select(User).where(User.username == payload.username))
    if not user:
        user = User(username=payload.username)
        db.add(user)
        db.commit()
        db.refresh(user)

    if user.is_banned:
        raise HTTPException(status_code=403, detail="该用户已被封禁。")

    # 2) Create comment (initially visible)
    parent_id = payload.parent_comment_id
    if parent_id is not None:
        parent = db.get(Comment, parent_id)
        if not parent:
            raise HTTPException(status_code=404, detail="要回复的帖子不存在。")
        if getattr(parent, "parent_comment_id", None) is not None:
            raise HTTPException(status_code=400, detail="暂不支持回复的回复（只支持一层回复）。")

    comment = Comment(user_id=user.id, content=payload.content, parent_comment_id=parent_id)
    db.add(comment)
    db.commit()
    db.refresh(comment)

    # 3) Moderate (stage 4: hybrid rules + LLM if configured)
    decision, llm_meta = moderate_text_hybrid(payload.content)
    comment.lang = decision.lang

    # 4) Apply action to comment + strikes
    if decision.action in {ModerationAction.hide, ModerationAction.review}:
        comment.status = CommentStatus.hidden
    elif decision.action in {ModerationAction.delete}:
        comment.status = CommentStatus.deleted
    else:
        comment.status = CommentStatus.visible

    strike_added = False
    if decision.action in {ModerationAction.warn, ModerationAction.mute, ModerationAction.ban}:
        user.strikes += 1
        strike_added = True
        db.add(
            PenaltyEvent(
                user_id=user.id,
                comment_id=comment.id,
                type=PenaltyType.strike_added,
                delta_strikes=1,
                reason="触发风控：已记一次违规（strike）。",
            )
        )

    # 5) Three-strikes auto-ban
    if user.strikes >= 3:
        if not user.is_banned:
            user.is_banned = True
            db.add(
                PenaltyEvent(
                    user_id=user.id,
                    comment_id=comment.id,
                    type=PenaltyType.banned,
                    delta_strikes=0,
                    reason="三振规则触发：自动封禁。",
                )
            )
        new_risk = max(decision.risk_score, 90)
        decision = replace(
            decision,
            action=ModerationAction.ban,
            risk_score=new_risk,
            severity="HIGH",
            categories=list(set(decision.categories + ["three_strikes"])),
            evidence=decision.evidence,
            rationale=(decision.rationale + " 三振规则触发：自动封禁。").strip(),
            lang=decision.lang,
        )

    # 6) Save moderation result (audit trail)
    moderation = ModerationResult(
        comment_id=comment.id,
        action=decision.action,
        risk_score=decision.risk_score,
        severity=decision.severity,
        llm_used=bool(decision.llm_used),
        llm_model=decision.llm_model,
        llm_error=decision.llm_error,
        categories=",".join(decision.categories),
        evidence=str(decision.evidence),
        rationale=decision.rationale + (f" StrikeAdded={strike_added}" if strike_added else ""),
        policy_version=POLICY_VERSION,
    )
    db.add(moderation)

    if llm_meta.get("used"):
        db.add(
            LlmCallLog(
                comment_id=comment.id,
                user_id=user.id,
                model=str(llm_meta.get("model") or decision.llm_model or ""),
                ok=bool(llm_meta.get("ok")),
                http_status=llm_meta.get("http_status"),
                error=(str(llm_meta.get("error"))[:500] if llm_meta.get("error") else None),
                latency_ms=llm_meta.get("latency_ms"),
                response_json=(
                    json.dumps(decision.raw_llm, ensure_ascii=False) if decision.raw_llm is not None else ""
                )[:2000],
            )
        )

    db.commit()
    db.refresh(user)
    db.refresh(comment)
    db.refresh(moderation)

    return CommentCreateResponse(user=_user_to_out(user), comment=_comment_to_out(comment))


@app.post("/v1/comments/{comment_id}/like")
def like_comment(comment_id: int, db: Session = Depends(db)) -> dict:
    c = db.get(Comment, comment_id)
    if not c:
        raise HTTPException(status_code=404, detail="评论不存在。")
    db.execute(update(Comment).where(Comment.id == comment_id).values(like_count=Comment.like_count + 1))
    db.commit()
    db.refresh(c)
    return {"ok": True, "comment_id": comment_id, "like_count": int(getattr(c, "like_count", 0) or 0)}


@app.get("/v1/comments/{comment_id}/replies", response_model=CommentsListResponse)
def list_replies(
    comment_id: int,
    db: Session = Depends(db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> CommentsListResponse:
    if not db.get(Comment, comment_id):
        raise HTTPException(status_code=404, detail="帖子不存在。")
    stmt = (
        select(Comment)
        .options(selectinload(Comment.user))
        .where(Comment.parent_comment_id == comment_id)
        .order_by(Comment.id.asc())
    )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.limit(limit).offset(offset)).all()
    outs = [_comment_to_out(c) for c in items]
    return CommentsListResponse(total=int(total), items=outs)


@app.get("/v1/users/{user_id}", response_model=UserOut)
def get_user(user_id: int, db: Session = Depends(db)) -> UserOut:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在。")
    return _user_to_out(user)


def _translation_prompt(src_text: str, target_lang: str) -> str:
    # We reuse chat completions; keep prompt simple and deterministic.
    return (
        "你是翻译助手。只输出翻译后的文本，不要解释。\n"
        f"目标语言：{target_lang}\n"
        "待翻译内容：\n"
        f"{src_text}"
    )


@app.post("/v1/comments/{comment_id}/translate", response_model=TranslationResponse)
def translate_comment(comment_id: int, payload: TranslationRequest, db: Session = Depends(db)) -> TranslationResponse:
    c = db.get(Comment, comment_id)
    if not c:
        raise HTTPException(status_code=404, detail="评论不存在。")

    target = payload.target_lang
    # 1) cache hit
    cached = db.scalar(
        select(CommentTranslation).where(
            CommentTranslation.comment_id == comment_id, CommentTranslation.target_lang == target
        )
    )
    if cached and cached.ok and cached.translated_text:
        return TranslationResponse(
            comment_id=comment_id,
            source_lang=c.lang,
            target_lang=target,
            translated_text=cached.translated_text,
            cached=True,
            model=cached.model or None,
            error=None,
        )

    config = load_volc_config()
    if not config:
        raise HTTPException(status_code=400, detail="未配置火山引擎（VOLC_API_KEY / VOLC_MODEL）。")

    sys_prompt = "你是翻译助手。严格只输出翻译结果，不要解释，不要加引号。"
    user_prompt = _translation_prompt(c.content, target)
    translated, trace = volc_chat_text_traced(
        config,
        system_prompt=sys_prompt,
        user_text=user_prompt,
        timeout_s=float(os.environ.get("VOLC_TIMEOUT_S", "12")),
    )
    if not translated:
        err = (trace.error or "翻译失败")[:500]
        db.add(
            CommentTranslation(
                comment_id=comment_id,
                source_lang=c.lang,
                target_lang=target,
                translated_text="",
                model=config.model,
                ok=False,
                error=err,
            )
        )
        db.commit()
        return TranslationResponse(
            comment_id=comment_id,
            source_lang=c.lang,
            target_lang=target,
            translated_text="",
            cached=False,
            model=config.model,
            error=err,
        )

    ok = bool(translated.strip())
    db.add(
        CommentTranslation(
            comment_id=comment_id,
            source_lang=c.lang,
            target_lang=target,
            translated_text=translated,
            model=config.model,
            ok=ok,
            error="" if ok else "empty_translation",
        )
    )
    db.commit()
    return TranslationResponse(
        comment_id=comment_id,
        source_lang=c.lang,
        target_lang=target,
        translated_text=translated,
        cached=False,
        model=config.model,
        error=None if ok else "empty_translation",
    )


@app.post("/v1/translate", response_model=TextTranslateResponse)
def translate_text(payload: TextTranslateRequest) -> TextTranslateResponse:
    config = load_volc_config()
    if not config:
        raise HTTPException(status_code=400, detail="未配置火山引擎（VOLC_API_KEY / VOLC_MODEL）。")
    sys_prompt = "你是翻译助手。严格只输出翻译结果，不要解释，不要加引号。"
    user_prompt = _translation_prompt(payload.text, payload.target_lang)
    translated, trace = volc_chat_text_traced(
        config,
        system_prompt=sys_prompt,
        user_text=user_prompt,
        timeout_s=float(os.environ.get("VOLC_TIMEOUT_S", "12")),
    )
    if not translated:
        return TextTranslateResponse(
            target_lang=payload.target_lang,
            translated_text="",
            model=config.model,
            error=(trace.error or "翻译失败")[:500],
        )
    return TextTranslateResponse(
        target_lang=payload.target_lang,
        translated_text=translated,
        model=config.model,
        error=None,
    )


@app.post("/v1/agent/advice", response_model=AgentAdviceResponse)
def agent_advice(payload: AgentAdviceRequest) -> AgentAdviceResponse:
    text = payload.text.strip()
    decision, _meta = moderate_text_hybrid(text)

    risk_level = "safe"
    if decision.severity == "HIGH" or decision.action in {ModerationAction.ban, ModerationAction.delete}:
        risk_level = "toxic"
    elif decision.severity == "MED" or decision.action in {
        ModerationAction.warn,
        ModerationAction.mute,
        ModerationAction.hide,
        ModerationAction.review,
    }:
        risk_level = "warning"

    suggestion = "建议：保持礼貌表达，避免辱骂、拉踩与引战措辞。"
    if risk_level == "warning":
        suggestion = "建议：把强硬/阴阳怪气的句式改成“我更喜欢/我觉得…”，并避免点名拉踩。"
    if risk_level == "toxic":
        suggestion = "建议：删去辱骂/攻击性词汇，改为描述事实或表达个人偏好，避免人身攻击。"

    return AgentAdviceResponse(
        risk_level=risk_level,
        action=decision.action.value,
        risk_score=int(decision.risk_score),
        severity=str(decision.severity),
        categories=list(decision.categories or []),
        evidence=str(decision.evidence or ""),
        rationale=str(decision.rationale or ""),
        suggestion=suggestion,
    )


@app.get("/v1/users/by-username/{username}", response_model=UserLookupResponse)
def get_user_by_username(username: str, db: Session = Depends(db)) -> UserLookupResponse:
    user = db.scalar(select(User).where(User.username == username))
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在。")
    return UserLookupResponse(user=_user_to_out(user))


@app.get("/v1/users/{user_id}/penalties", response_model=PenaltyEventsListResponse)
def list_user_penalties(
    user_id: int,
    db: Session = Depends(db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> PenaltyEventsListResponse:
    if not db.get(User, user_id):
        raise HTTPException(status_code=404, detail="用户不存在。")

    stmt = select(PenaltyEvent).where(PenaltyEvent.user_id == user_id).order_by(PenaltyEvent.id.desc())
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.limit(limit).offset(offset)).all()
    return PenaltyEventsListResponse(total=int(total), items=[_penalty_to_out(p) for p in items])


@app.get("/v1/comments", response_model=CommentsListResponse)
def list_comments(
    db: Session = Depends(db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    username: str | None = Query(default=None, description="Filter by username"),
    user_id: int | None = Query(default=None, description="Filter by user_id"),
    status: str | None = Query(default=None, description="VISIBLE/HIDDEN/DELETED"),
    action: str | None = Query(default=None, description="ALLOW/HIDE/DELETE/WARN/MUTE/BAN/REVIEW"),
    include_replies: bool = Query(default=False, description="Include replies (default: root posts only)"),
) -> CommentsListResponse:
    stmt = select(Comment).options(selectinload(Comment.user)).order_by(Comment.id.desc())
    if not include_replies:
        stmt = stmt.where(Comment.parent_comment_id.is_(None))
    if username:
        stmt = stmt.join(User).where(User.username == username)
    if user_id is not None:
        stmt = stmt.where(Comment.user_id == user_id)
    if status:
        stmt = stmt.where(Comment.status == CommentStatus(status))
    if action:
        stmt = stmt.join(ModerationResult).where(ModerationResult.action == ModerationAction(action))

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.limit(limit).offset(offset)).all()
    outs = [_comment_to_out(c) for c in items]
    outs = _attach_thread_meta(outs, db)
    return CommentsListResponse(total=int(total), items=outs)


@app.get("/v1/comments/{comment_id}", response_model=CommentOut)
def get_comment(comment_id: int, db: Session = Depends(db)) -> CommentOut:
    c = db.get(Comment, comment_id)
    if not c:
        raise HTTPException(status_code=404, detail="评论不存在。")
    return _comment_to_out(c)


@app.get("/v1/review-queue", response_model=CommentsListResponse)
def review_queue(
    db: Session = Depends(db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> CommentsListResponse:
    stmt = (
        select(Comment)
        .join(ModerationResult)
        .where(ModerationResult.action == ModerationAction.review)
        .order_by(Comment.id.desc())
    )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.limit(limit).offset(offset)).all()
    return CommentsListResponse(total=int(total), items=[_comment_to_out(c) for c in items])


@app.post("/v1/admin/comments/{comment_id}/override", response_model=AdminOverrideResponse)
def admin_override_comment(
    comment_id: int,
    payload: AdminOverrideRequest,
    db: Session = Depends(db),
    x_admin_key: str | None = Header(default=None),
) -> AdminOverrideResponse:
    _require_admin(x_admin_key)

    comment = db.get(Comment, comment_id)
    if not comment:
        raise HTTPException(status_code=404, detail="评论不存在。")

    user = db.get(User, comment.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在。")

    moderation = comment.moderation
    if not moderation:
        raise HTTPException(status_code=400, detail="该评论没有风控结果。")

    new_action = ModerationAction(payload.new_action)
    prev_action = moderation.action

    # Save override audit
    db.add(
        ModerationOverride(
            comment_id=comment.id,
            previous_action=prev_action,
            new_action=new_action,
            moderator=payload.moderator,
            reason=payload.reason,
        )
    )

    # Apply new action to comment status
    if new_action in {ModerationAction.hide, ModerationAction.review}:
        comment.status = CommentStatus.hidden
    elif new_action == ModerationAction.delete:
        comment.status = CommentStatus.deleted
    else:
        comment.status = CommentStatus.visible

    # Strikes adjustment (simple, transparent rule for v0.1)
    prev_strike = prev_action in {ModerationAction.warn, ModerationAction.mute, ModerationAction.ban}
    new_strike = new_action in {ModerationAction.warn, ModerationAction.mute, ModerationAction.ban}
    if prev_strike and not new_strike and user.strikes > 0:
        user.strikes -= 1
        db.add(
            PenaltyEvent(
                user_id=user.id,
                comment_id=comment.id,
                type=PenaltyType.strike_removed,
                delta_strikes=-1,
                reason="Strike removed by admin override.",
            )
        )
    elif (not prev_strike) and new_strike:
        user.strikes += 1
        db.add(
            PenaltyEvent(
                user_id=user.id,
                comment_id=comment.id,
                type=PenaltyType.strike_added,
                delta_strikes=1,
                reason="管理员改判：新增一次违规（strike）。",
            )
        )

    # Ban/unban based on strikes + explicit action
    if new_action == ModerationAction.ban or user.strikes >= 3:
        if not user.is_banned:
            user.is_banned = True
            db.add(
                PenaltyEvent(
                    user_id=user.id,
                    comment_id=comment.id,
                    type=PenaltyType.banned,
                    delta_strikes=0,
                    reason="管理员改判/三振规则：执行封禁。",
                )
            )
        moderation.action = ModerationAction.ban
    else:
        moderation.action = new_action
        # Auto-unban when strikes dropped below threshold (v0.1 policy)
        if user.is_banned and user.strikes < 3:
            user.is_banned = False
            db.add(
                PenaltyEvent(
                    user_id=user.id,
                    comment_id=comment.id,
                    type=PenaltyType.unbanned,
                    delta_strikes=0,
                    reason="Auto-unbanned because strikes < 3 after override.",
                )
            )

    moderation.rationale = (moderation.rationale + f" | OverriddenBy={payload.moderator}").strip()
    moderation.policy_version = POLICY_VERSION

    db.commit()
    db.refresh(user)
    db.refresh(comment)
    db.refresh(moderation)

    return AdminOverrideResponse(comment=_comment_to_out(comment), user=_user_to_out(user))


@app.post("/v1/admin/demo/reset", response_model=AdminResetResponse)
def admin_reset_demo_data(
    db: Session = Depends(db),
    x_admin_key: str | None = Header(default=None),
) -> AdminResetResponse:
    _require_admin(x_admin_key)

    # 删除顺序：依赖表 -> 主表
    db.execute(delete(ModerationOverride))
    db.execute(delete(PenaltyEvent))
    db.execute(delete(LlmCallLog))
    db.execute(delete(ModerationResult))
    deleted_comments = db.execute(delete(Comment)).rowcount or 0
    deleted_users = db.execute(delete(User)).rowcount or 0
    db.commit()
    return AdminResetResponse(ok=True, deleted_comments=int(deleted_comments), deleted_users=int(deleted_users))

