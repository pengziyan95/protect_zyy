from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

from .models import ModerationAction
from .llm_volcengine import load_volc_config, volc_chat_json_traced


@dataclass(frozen=True)
class ModerationDecision:
    action: ModerationAction
    risk_score: int
    severity: str  # LOW/MED/HIGH
    categories: list[str]
    evidence: str
    rationale: str
    lang: str = "unknown"
    raw_llm: dict[str, Any] | None = None
    llm_used: bool = False
    llm_model: str | None = None
    llm_error: str | None = None


_CONTACT_RE = re.compile(r"(\b\d{5,12}\b)|(@\w+)|(wx|v|wechat)\s*[:：]?\s*[a-zA-Z0-9_-]{5,}")
_URL_RE = re.compile(r"https?://\S+")

# 极简“种子词”：只用于跑通闭环；后续会替换为可配置词典 + 自动生长
_ZH_TOXIC = {"nmsl", "傻逼", "sb", "滚", "脑残", "死", "废物", "贱", "畜生"}
_EN_TOXIC = {"idiot", "stupid", "trash", "die", "kill yourself"}
_JA_TOXIC = {"死ね", "消えろ"}
_KO_TOXIC = {"꺼져", "죽어"}
_TH_TOXIC = {"โง่", "เกลียด"}

_ZH_MILD_NEG = {"恶心", "下头", "真下头", "你也配", "糊", "退圈", "滚出"}

# 用于“更智能一点”的变体匹配：去掉标点/空格/重复字符
_PUNCT_SPACE_RE = re.compile(r"[\s\.\,\!\?\~\-\_\+\=\(\)\[\]\{\}<>/\\|:;\"'“”‘’，。！？、…【】（）]+")
_REPEAT_RE = re.compile(r"(.)\1{2,}")  # e.g. 哈哈哈哈 -> 哈哈 (保留2个)


def _read_int(name: str, default: int) -> int:
    v = os.environ.get(name, "").strip()
    if not v:
        return default
    try:
        return int(v)
    except ValueError:
        return default


SEVERITY_LOW_MAX = _read_int("SEVERITY_LOW_MAX", 34)
SEVERITY_MED_MAX = _read_int("SEVERITY_MED_MAX", 69)


def risk_to_severity(risk_score: int) -> str:
    r = max(0, min(100, int(risk_score)))
    if r <= SEVERITY_LOW_MAX:
        return "LOW"
    if r <= SEVERITY_MED_MAX:
        return "MED"
    return "HIGH"


def _normalize_for_match(text: str) -> str:
    t = text.strip().lower()
    t = _PUNCT_SPACE_RE.sub("", t)
    t = _REPEAT_RE.sub(r"\1\1", t)
    return t


def detect_lang(text: str) -> str:
    # 轻量语言检测：够用来分流词典；后续可升级为更稳的 langid/fastText
    for ch in text:
        code = ord(ch)
        if 0x4E00 <= code <= 0x9FFF:
            return "zh"
        if 0x3040 <= code <= 0x30FF:
            return "ja"
        if 0xAC00 <= code <= 0xD7AF:
            return "ko"
        if 0x0E00 <= code <= 0x0E7F:
            return "th"
    return "en"


def _contains_any(text_lower: str, vocab: set[str]) -> str | None:
    for w in vocab:
        if w in text_lower:
            return w
    return None


def moderate_text(text: str) -> ModerationDecision:
    normalized = text.strip()
    lang = detect_lang(normalized)
    lower = normalized.lower()
    norm_match = _normalize_for_match(normalized)

    # 广告/引流：链接或联系方式
    if _URL_RE.search(normalized) or _CONTACT_RE.search(normalized):
        return ModerationDecision(
            action=ModerationAction.hide,
            risk_score=75,
            severity=risk_to_severity(75),
            categories=["ad"],
            evidence=_URL_RE.findall(normalized)[:1] or _CONTACT_RE.findall(normalized)[:1].__str__(),
            rationale="疑似广告/引流或泄露联系方式，默认折叠隐藏。",
            lang=lang,
        )

    toxic_hit = None
    if lang == "zh":
        toxic_hit = _contains_any(norm_match, {_normalize_for_match(w) for w in _ZH_TOXIC})
    elif lang == "ja":
        toxic_hit = _contains_any(norm_match, {_normalize_for_match(w) for w in _JA_TOXIC})
    elif lang == "ko":
        toxic_hit = _contains_any(norm_match, {_normalize_for_match(w) for w in _KO_TOXIC})
    elif lang == "th":
        toxic_hit = _contains_any(norm_match, {_normalize_for_match(w) for w in _TH_TOXIC})
    else:
        toxic_hit = _contains_any(norm_match, {_normalize_for_match(w) for w in _EN_TOXIC})

    if toxic_hit:
        return ModerationDecision(
            action=ModerationAction.warn,
            risk_score=85,
            severity=risk_to_severity(85),
            categories=["toxicity"],
            evidence=toxic_hit,
            rationale="命中明显辱骂/攻击性词汇：警告并计入一次违规（strike）。",
            lang=lang,
        )

    # 复核队列（REVIEW）：存在明显负面但不够确定/可能是善意批评
    if lang == "zh":
        mild_hit = _contains_any(norm_match, {_normalize_for_match(w) for w in _ZH_MILD_NEG})
        if mild_hit:
            return ModerationDecision(
                action=ModerationAction.review,
                risk_score=55,
                severity=risk_to_severity(55),
                categories=["mild_negativity"],
                evidence=mild_hit,
                rationale="可能存在负面表达但语境不确定：进入复核队列以降低误杀。",
                lang=lang,
            )

    # 默认放行
    return ModerationDecision(
        action=ModerationAction.allow,
        risk_score=5,
        severity=risk_to_severity(5),
        categories=[],
        evidence="",
        rationale="未命中明显风险信号：默认放行。",
        lang=lang,
    )


def _llm_mode() -> str:
    return os.environ.get("VOLC_LLM_MODE", "smart").strip().lower()  # off|fast_only|smart|always


def _llm_timeout_s() -> float:
    v = os.environ.get("VOLC_TIMEOUT_S", "12").strip()
    try:
        return float(v)
    except ValueError:
        return 12.0


def _should_call_llm(fast: ModerationDecision) -> bool:
    mode = _llm_mode()
    if mode in {"0", "false", "off", "no"}:
        return False
    if mode in {"always", "all", "force"}:
        return True
    if mode in {"fast_only", "rules_only", "no_llm"}:
        return False

    # smart (default)
    if fast.action in {ModerationAction.warn, ModerationAction.ban, ModerationAction.hide} and fast.risk_score >= 70:
        return False
    return True


def _decide_from_llm_json(j: dict[str, Any], fast: ModerationDecision) -> ModerationDecision:
    suggested = str(j.get("suggested_action", "")).upper().strip()
    action = fast.action
    if suggested in {a.value for a in ModerationAction}:
        action = ModerationAction(suggested)

    categories = j.get("categories") or []
    if isinstance(categories, str):
        categories = [categories]
    categories = [str(c) for c in categories][:12]

    risk = j.get("risk_score")
    try:
        risk_score = int(risk)
    except Exception:  # noqa: BLE001
        risk_score = fast.risk_score
    risk_score = max(0, min(100, risk_score))

    lang = str(j.get("lang") or fast.lang or "unknown")
    evidence = str(j.get("evidence") or fast.evidence or "")
    rationale = str(j.get("rationale") or fast.rationale or "")

    # Good-faith gate: if model says good_faith, avoid escalating to BAN
    good_faith = bool(j.get("good_faith")) if "good_faith" in j else False
    if good_faith and action in {ModerationAction.ban, ModerationAction.mute}:
        action = ModerationAction.review
        categories = list(set(categories + ["good_faith_criticism"]))
        rationale = (rationale + " (good-faith gate: downgraded to REVIEW)").strip()

    sev = risk_to_severity(risk_score)
    return ModerationDecision(
        action=action,
        risk_score=risk_score,
        severity=sev,
        categories=categories,
        evidence=evidence,
        rationale=rationale,
        lang=lang,
        raw_llm=j,
        llm_used=True,
        llm_model=None,  # filled by caller
        llm_error=None,
    )


def moderate_text_hybrid(text: str) -> tuple[ModerationDecision, dict[str, Any]]:
    """
    Returns (decision, llm_meta) where llm_meta is safe to store/audit.
    """
    fast = moderate_text(text)
    llm_meta: dict[str, Any] = {
        "used": False,
        "ok": None,
        "http_status": None,
        "latency_ms": None,
        "error": None,
        "model": None,
    }

    if not _should_call_llm(fast):
        return fast, llm_meta

    config = load_volc_config()
    if not config:
        return fast, llm_meta

    j, trace = volc_chat_json_traced(config, text, timeout_s=_llm_timeout_s())
    llm_meta.update(
        {
            "used": True,
            "ok": bool(trace.ok),
            "http_status": trace.http_status,
            "latency_ms": trace.latency_ms,
            "error": trace.error,
            "model": trace.model,
        }
    )

    if j is None:
        return (
            ModerationDecision(
                action=fast.action,
                risk_score=fast.risk_score,
                severity=fast.severity,
                categories=fast.categories,
                evidence=fast.evidence,
                rationale=fast.rationale,
                lang=fast.lang,
                raw_llm=None,
                llm_used=True,
                llm_model=trace.model,
                llm_error=(trace.error or "llm_error")[:255],
            ),
            llm_meta,
        )

    d = _decide_from_llm_json(j, fast)
    return (
        ModerationDecision(
            action=d.action,
            risk_score=d.risk_score,
            severity=d.severity,
            categories=d.categories,
            evidence=d.evidence,
            rationale=d.rationale,
            lang=d.lang,
            raw_llm=d.raw_llm,
            llm_used=True,
            llm_model=trace.model,
            llm_error=d.llm_error,
        ),
        llm_meta,
    )

