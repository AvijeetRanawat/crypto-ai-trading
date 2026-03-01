from __future__ import annotations

import html
import json
import re
import time
import hashlib
import boto3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree

import requests
from logger import logger
from config import config
from local_llm import get_local_llm_agent


REQUEST_TIMEOUT_SECONDS = 8
CACHE_TTL_SECONDS = 120


POSITIVE_TERMS = {
    "surge",
    "rally",
    "bull",
    "bullish",
    "gain",
    "gains",
    "up",
    "approval",
    "adoption",
    "inflow",
    "breakout",
    "high",
    "growth",
    "beat",
}

NEGATIVE_TERMS = {
    "drop",
    "crash",
    "bear",
    "bearish",
    "down",
    "hack",
    "lawsuit",
    "ban",
    "outflow",
    "fear",
    "risk",
    "fraud",
    "selloff",
    "decline",
    "slump",
}

_CACHE: Dict[str, Any] = {"ts": 0.0, "payload": None}
_SUMMARY_CACHE: Dict[str, Any] = {"ts": 0.0, "fingerprint": "", "summary": None, "usage_event": None}
SUMMARY_CACHE_TTL_SECONDS = 300

SYMBOL_TOPIC_MAP = {
    "BTCUSDT": {
        "name": "BTC",
        "alphavantage_ticker": "CRYPTO:BTC",
        "cryptocompare_categories": "BTC,Bitcoin",
        "gdelt_query": "bitcoin OR btc OR cryptocurrency",
    },
    "ETHUSDT": {
        "name": "ETH",
        "alphavantage_ticker": "CRYPTO:ETH",
        "cryptocompare_categories": "ETH,Ethereum",
        "gdelt_query": "ethereum OR eth OR cryptocurrency",
    },
    "SOLUSDT": {
        "name": "SOL",
        "alphavantage_ticker": "CRYPTO:SOL",
        "cryptocompare_categories": "SOL,Solana",
        "gdelt_query": "solana OR sol OR cryptocurrency",
    },
    "ETHBTC": {
        "name": "ETH",
        "alphavantage_ticker": "CRYPTO:ETH",
        "cryptocompare_categories": "ETH,Ethereum",
        "gdelt_query": "ethereum OR eth OR cryptocurrency",
    },
    "SOLBTC": {
        "name": "SOL",
        "alphavantage_ticker": "CRYPTO:SOL",
        "cryptocompare_categories": "SOL,Solana",
        "gdelt_query": "solana OR sol OR cryptocurrency",
    },
    "SOLETH": {
        "name": "SOL",
        "alphavantage_ticker": "CRYPTO:SOL",
        "cryptocompare_categories": "SOL,Solana",
        "gdelt_query": "solana OR sol OR cryptocurrency",
    },
}


def _topic_for_symbol(symbol: str) -> Dict[str, str]:
    return SYMBOL_TOPIC_MAP.get(str(symbol).upper(), SYMBOL_TOPIC_MAP["BTCUSDT"])


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _label(score: float) -> str:
    if score >= 0.2:
        return "BULLISH"
    if score <= -0.2:
        return "BEARISH"
    return "NEUTRAL"


def _headline_sentiment(title: str) -> float:
    text = re.sub(r"[^a-z0-9\s]", " ", title.lower())
    tokens = [tok for tok in text.split() if tok]
    if not tokens:
        return 0.0
    pos = sum(1 for t in tokens if t in POSITIVE_TERMS)
    neg = sum(1 for t in tokens if t in NEGATIVE_TERMS)
    return _clamp((pos - neg) / 4.0)


def _to_iso(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    value = value.strip()
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %z",
        "%Y%m%dT%H%M%S",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            dt = datetime.strptime(value, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        except ValueError:
            continue
    return value


def _safe_get_json(
    url: str,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Optional[Dict[str, Any]]:
    try:
        response = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.json()
    except Exception:
        return None


def _safe_get_text(url: str, params: Optional[Dict[str, Any]] = None) -> Optional[str]:
    try:
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.text
    except Exception:
        return None


def fetch_cryptocompare_news(api_key: str, categories: str, limit: int = 10) -> List[Dict[str, Any]]:
    if not api_key:
        return []

    data = _safe_get_json(
        "https://min-api.cryptocompare.com/data/v2/news/",
        params={
            "lang": "EN",
            "categories": categories,
            "sortOrder": "latest",
            "limit": limit,
        },
        headers={"authorization": f"Apikey {api_key}"},
    )
    if not data:
        return []

    items = data.get("Data") or []
    out: List[Dict[str, Any]] = []
    for item in items:
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        out.append(
            {
                "source": "CryptoCompare",
                "title": title,
                "url": item.get("url") or "",
                "published_at": _to_iso(datetime.fromtimestamp(int(item.get("published_on", 0)), tz=timezone.utc).isoformat())
                if item.get("published_on")
                else None,
                "sentiment_score": _headline_sentiment(title),
            }
        )
    return out


def fetch_alpha_vantage_news(api_key: str, ticker: str, limit: int = 10) -> List[Dict[str, Any]]:
    if not api_key:
        return []

    data = _safe_get_json(
        "https://www.alphavantage.co/query",
        params={
            "function": "NEWS_SENTIMENT",
            "tickers": ticker,
            "sort": "LATEST",
            "limit": limit,
            "apikey": api_key,
        },
    )
    if not data:
        return []

    feed = data.get("feed") or []
    out: List[Dict[str, Any]] = []
    for item in feed:
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        av_score = item.get("overall_sentiment_score")
        try:
            score = _clamp(float(av_score))
        except Exception:
            score = _headline_sentiment(title)
        out.append(
            {
                "source": item.get("source") or "AlphaVantage",
                "title": title,
                "url": item.get("url") or "",
                "published_at": _to_iso(item.get("time_published")),
                "sentiment_score": score,
            }
        )
    return out


def fetch_fear_and_greed() -> Dict[str, Any]:
    data = _safe_get_json("https://api.alternative.me/fng/", params={"limit": 1})
    if not data:
        return {"value": None, "value_classification": "Unknown", "sentiment_score": 0.0}

    entries = data.get("data") or []
    if not entries:
        return {"value": None, "value_classification": "Unknown", "sentiment_score": 0.0}

    row = entries[0]
    try:
        value = int(row.get("value", 50))
    except Exception:
        value = 50

    return {
        "value": value,
        "value_classification": row.get("value_classification") or "Unknown",
        "sentiment_score": _clamp((value - 50.0) / 50.0),
        "timestamp": _to_iso(row.get("timestamp")),
    }


def fetch_cointelegraph_rss(limit: int = 12) -> List[Dict[str, Any]]:
    xml_text = _safe_get_text("https://cointelegraph.com/rss/tag/bitcoin")
    if not xml_text:
        return []

    try:
        root = ElementTree.fromstring(xml_text)
    except Exception:
        return []

    out: List[Dict[str, Any]] = []
    items = root.findall(".//item")
    for item in items[:limit]:
        title = html.unescape((item.findtext("title") or "").strip())
        if not title:
            continue
        out.append(
            {
                "source": "Cointelegraph",
                "title": title,
                "url": (item.findtext("link") or "").strip(),
                "published_at": _to_iso(item.findtext("pubDate")),
                "sentiment_score": _headline_sentiment(title),
            }
        )
    return out


def fetch_gdelt_news(query: str, limit: int = 12) -> List[Dict[str, Any]]:
    data = _safe_get_json(
        "https://api.gdeltproject.org/api/v2/doc/doc",
        params={
            "query": query,
            "mode": "ArtList",
            "maxrecords": limit,
            "format": "json",
            "sort": "DateDesc",
        },
    )
    if not data:
        return []

    articles = data.get("articles") or []
    out: List[Dict[str, Any]] = []
    for article in articles:
        title = str(article.get("title") or "").strip()
        if not title:
            continue
        out.append(
            {
                "source": article.get("sourcecommonname") or article.get("domain") or "GDELT",
                "title": title,
                "url": article.get("url") or "",
                "published_at": _to_iso(article.get("seendate")),
                "sentiment_score": _headline_sentiment(title),
            }
        )
    return out


def build_sentiment_snapshot(alpha_key: str, cryptocompare_key: str, symbol: str = "BTCUSDT") -> Dict[str, Any]:
    now = time.time()
    cached_payload = _CACHE.get("payload")
    cached_symbol = str((_CACHE.get("payload") or {}).get("symbol", "")).upper()
    if cached_payload and cached_symbol == str(symbol).upper() and now - float(_CACHE.get("ts", 0.0)) < CACHE_TTL_SECONDS:
        return cached_payload

    topic = _topic_for_symbol(symbol)
    provider_items: Dict[str, List[Dict[str, Any]]] = {
        "alphavantage": fetch_alpha_vantage_news(alpha_key, ticker=topic["alphavantage_ticker"], limit=10),
        "cryptocompare": fetch_cryptocompare_news(cryptocompare_key, categories=topic["cryptocompare_categories"], limit=10),
        "cointelegraph": fetch_cointelegraph_rss(limit=10),
        "gdelt": fetch_gdelt_news(query=topic["gdelt_query"], limit=10),
    }

    fear_greed = fetch_fear_and_greed()

    dedup: Dict[str, Dict[str, Any]] = {}
    for source_items in provider_items.values():
        for item in source_items:
            key = (item.get("url") or "").strip() or f"{item.get('source','src')}::{item.get('title','')}"
            if key in dedup:
                continue
            dedup[key] = item

    articles = sorted(
        dedup.values(),
        key=lambda x: x.get("published_at") or "",
        reverse=True,
    )[:25]

    news_scores = [float(item.get("sentiment_score", 0.0)) for item in articles]
    news_score = sum(news_scores) / len(news_scores) if news_scores else 0.0

    source_available = {
        "alphavantage": bool(provider_items["alphavantage"]),
        "cryptocompare": bool(provider_items["cryptocompare"]),
        "cointelegraph": bool(provider_items["cointelegraph"]),
        "gdelt": bool(provider_items["gdelt"]),
        "fear_greed": fear_greed.get("value") is not None,
    }

    # Weighted blend: news sentiment + fear/greed market mood
    fear_score = float(fear_greed.get("sentiment_score", 0.0))
    composite = _clamp((news_score * 0.75) + (fear_score * 0.25))

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "symbol": str(symbol).upper(),
        "sentiment_score": round(composite, 3),
        "sentiment_label": _label(composite),
        "components": {
            "news_score": round(news_score, 3),
            "fear_greed_score": round(fear_score, 3),
            "fear_greed": fear_greed,
            "articles_count": len(articles),
            "sources_available": source_available,
        },
        "articles": articles,
    }

    _CACHE["ts"] = now
    _CACHE["payload"] = payload
    return payload


def _estimate_tokens(text: str) -> int:
    return max(1, int(len(text or "") / 4))


def _coerce_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        v = value.get("value")
        if isinstance(v, str):
            return v.strip()
        t = value.get("text")
        if isinstance(t, str):
            return t.strip()
    return ""


def _extract_responses_text(payload: Dict[str, Any]) -> str:
    text = str(payload.get("output_text") or "").strip()
    if text:
        return text

    out = payload.get("output") or []
    parts: List[str] = []
    for item in out:
        item_type = (item or {}).get("type")
        if item_type == "output_text":
            t = _coerce_text((item or {}).get("text"))
            if t:
                parts.append(t)
            continue
        if item_type != "message":
            continue
        for c in (item.get("content") or []):
            ctype = (c or {}).get("type")
            if ctype not in {"output_text", "text"}:
                continue
            t = _coerce_text(c.get("text")) or _coerce_text(c.get("value"))
            if t:
                parts.append(t)

    # Some responses may place text blocks at top-level content.
    for c in (payload.get("content") or []):
        t = _coerce_text(c.get("text")) or _coerce_text(c.get("value"))
        if t:
            parts.append(t)

    return "\n".join([p for p in parts if p]).strip()


def _build_summary_prompt(snapshot: Dict[str, Any]) -> str:
    symbol = str(snapshot.get("symbol") or "BTCUSDT").upper()
    coin_name = _topic_for_symbol(symbol)["name"]
    score = snapshot.get("sentiment_score", 0.0)
    label = snapshot.get("sentiment_label", "NEUTRAL")
    components = snapshot.get("components", {}) or {}
    fear_greed = components.get("fear_greed", {}) or {}
    headlines = snapshot.get("articles", [])[:8]

    lines = [
        f"Summarize {coin_name} market sentiment for a trader in <= 70 words.",
        "Return plain text only.",
        "Include: direction (bullish/bearish/neutral), confidence (low/medium/high), and 1 risk to watch.",
        "",
        f"Composite sentiment score: {score}",
        f"Composite label: {label}",
        f"Fear & Greed: {fear_greed.get('value')} ({fear_greed.get('value_classification')})",
        f"News score: {components.get('news_score')}",
        "",
        "Recent headlines:",
    ]
    for item in headlines:
        lines.append(f"- [{item.get('source', 'src')}] {item.get('title', '')}")
    return "\n".join(lines)


def summarize_sentiment_with_local_model(snapshot: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    agent = get_local_llm_agent()
    if not agent or not agent.ready():
        return None, None
    prompt = _build_summary_prompt(snapshot)
    text, usage = agent.complete(prompt)
    out = dict(snapshot)
    summary_text = text or "Local model produced no summary."
    out["llm_summary"] = {
        "text": summary_text,
        "model_id": agent.model_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cached": False,
    }
    usage_event = {
        "model_id": agent.model_id,
        "token_cost_usd": 0.0,
        "input_tokens": int(usage.get("input_tokens") or 0),
        "output_tokens": int(usage.get("output_tokens") or len(summary_text.split())),
        "total_tokens": int(usage.get("total_tokens") or 0),
        "latency_ms": int(usage.get("latency_ms") or 0),
        "source": "local",
    }
    return out, usage_event


def _summary_fingerprint(snapshot: Dict[str, Any]) -> str:
    head = [
        {
            "t": a.get("title", ""),
            "s": a.get("source", ""),
            "p": a.get("published_at", ""),
        }
        for a in (snapshot.get("articles") or [])[:10]
    ]
    payload = {
        "score": snapshot.get("sentiment_score"),
        "label": snapshot.get("sentiment_label"),
        "head": head,
        "fg": ((snapshot.get("components") or {}).get("fear_greed") or {}).get("value"),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _bedrock_model_candidates(model_id: str) -> List[str]:
    from config import config as _cfg

    raw = str(model_id or "").strip()
    out: List[str] = []
    profile = str(getattr(_cfg, "BEDROCK_INFERENCE_PROFILE_ID", "") or "").strip()
    if profile:
        out.append(profile)
    if raw:
        out.append(raw)
        if not (raw.startswith("us.") or raw.startswith("eu.") or raw.startswith("apac.") or raw.startswith("arn:")):
            out.append(f"us.{raw}")
    seen = set()
    uniq: List[str] = []
    for m in out:
        if m and m not in seen:
            seen.add(m)
            uniq.append(m)
    return uniq


def summarize_sentiment_with_api(
    snapshot: Dict[str, Any],
    *,
    openai_api_key: str,
    openai_base_url: str,
    model_id: str = "gpt-5-nano",
    input_price_per_1m: float = 0.05,
    output_price_per_1m: float = 0.40,
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """
    Adds an LLM-generated summary to the snapshot.
    Returns (augmented_snapshot, usage_event_or_none).
    usage_event is non-None only when a fresh API call is made.
    """
    if not openai_api_key:
        out = dict(snapshot)
        out["llm_summary"] = {
            "text": "LLM summary unavailable (missing OPENAI_API_KEY).",
            "model_id": model_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cached": True,
        }
        return out, None

    fingerprint = _summary_fingerprint(snapshot)
    now = time.time()
    cached = _SUMMARY_CACHE.get("summary")
    cached_fp = _SUMMARY_CACHE.get("fingerprint", "")
    cached_symbol = str((cached or {}).get("symbol", "")).upper()
    current_symbol = str(snapshot.get("symbol", "")).upper()
    if (
        cached
        and cached_symbol == current_symbol
        and cached_fp == fingerprint
        and now - float(_SUMMARY_CACHE.get("ts", 0.0)) < SUMMARY_CACHE_TTL_SECONDS
    ):
        out = dict(snapshot)
        out["llm_summary"] = dict(cached)
        out["llm_summary"]["cached"] = True
        return out, None

    prompt = _build_summary_prompt(snapshot)
    started = time.time()

    headers = {
        "Authorization": f"Bearer {openai_api_key}",
        "Content-Type": "application/json",
    }
    safe_headers = {
        "Authorization": "Bearer ***REDACTED***",
        "Content-Type": "application/json",
    }
    base = openai_base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        base = base[: -len("/chat/completions")]
    if base.endswith("/v1"):
        api_root = base
    else:
        api_root = f"{base}/v1"

    # GPT-5 models are most reliable on Responses API.
    payload = None
    text = ""
    usage = {}
    error_text = ""
    model_lower = str(model_id or "").lower()
    supports_custom_temperature = not model_lower.startswith("gpt-5")
    aggregate_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    try:
        responses_payload = {
            "model": model_id,
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": prompt}],
                }
            ],
            "max_output_tokens": 140,
        }
        if supports_custom_temperature:
            responses_payload["temperature"] = 0.1

        logger.info(f"OPENAI_REQ POST {api_root}/responses model={model_id} symbol={current_symbol}")
        logger.info(
            "OPENAI_REQ_VERBOSE endpoint=%s headers=%s payload=%s",
            f"{api_root}/responses",
            json.dumps(safe_headers, default=str),
            json.dumps(responses_payload, default=str),
        )
        resp = requests.post(
            f"{api_root}/responses",
            headers=headers,
            json=responses_payload,
            timeout=20,
        )
        logger.info(
            f"OPENAI_RES POST {api_root}/responses -> {resp.status_code} "
            f"({int((time.time() - started) * 1000)}ms)"
        )
        logger.info("OPENAI_RES_VERBOSE endpoint=%s body=%s", f"{api_root}/responses", (resp.text or ""))
        if not resp.ok:
            error_text = (resp.text or "").strip()[:500]
            logger.error(
                f"OPENAI_ERR model={model_id} symbol={current_symbol} "
                f"endpoint=/responses status={resp.status_code} body={error_text}"
            )
            resp.raise_for_status()
        payload = resp.json()
        text = _extract_responses_text(payload)
        usage_responses = payload.get("usage", {}) or {}
        aggregate_usage["input_tokens"] += int(usage_responses.get("input_tokens") or usage_responses.get("prompt_tokens") or 0)
        aggregate_usage["output_tokens"] += int(usage_responses.get("output_tokens") or usage_responses.get("completion_tokens") or 0)
        aggregate_usage["total_tokens"] += int(usage_responses.get("total_tokens") or 0)
        usage = dict(usage_responses)

        # If Responses produced only reasoning tokens and no text, run chat fallback for final text.
        if not text:
            logger.warning(
                "OPENAI responses returned empty text for model=%s symbol=%s; "
                "attempting /chat/completions fallback for final summary.",
                model_id,
                current_symbol,
            )
            fallback_started = time.time()
            chat_payload = {
                "model": model_id,
                "messages": [{"role": "user", "content": prompt}],
                "max_completion_tokens": 220,
            }
            if supports_custom_temperature:
                chat_payload["temperature"] = 0.1

            logger.info(f"OPENAI_REQ POST {api_root}/chat/completions model={model_id} symbol={current_symbol}")
            logger.info(
                "OPENAI_REQ_VERBOSE endpoint=%s headers=%s payload=%s",
                f"{api_root}/chat/completions",
                json.dumps(safe_headers, default=str),
                json.dumps(chat_payload, default=str),
            )
            resp2 = requests.post(
                f"{api_root}/chat/completions",
                headers=headers,
                json=chat_payload,
                timeout=20,
            )
            logger.info(
                f"OPENAI_RES POST {api_root}/chat/completions -> {resp2.status_code} "
                f"({int((time.time() - fallback_started) * 1000)}ms)"
            )
            logger.info("OPENAI_RES_VERBOSE endpoint=%s body=%s", f"{api_root}/chat/completions", (resp2.text or ""))
            if not resp2.ok:
                error_text = (resp2.text or "").strip()[:500]
                logger.error(
                    f"OPENAI_ERR model={model_id} symbol={current_symbol} "
                    f"status={resp2.status_code} body={error_text}"
                )
                resp2.raise_for_status()

            payload2 = resp2.json()
            choices2 = payload2.get("choices") or []
            text = ((choices2[0] or {}).get("message") or {}).get("content", "") if choices2 else ""
            usage_chat = payload2.get("usage", {}) or {}
            aggregate_usage["input_tokens"] += int(usage_chat.get("input_tokens") or usage_chat.get("prompt_tokens") or 0)
            aggregate_usage["output_tokens"] += int(usage_chat.get("output_tokens") or usage_chat.get("completion_tokens") or 0)
            aggregate_usage["total_tokens"] += int(usage_chat.get("total_tokens") or 0)

            in_res = int(usage_responses.get("prompt_tokens") or usage_responses.get("input_tokens") or 0)
            out_res = int(usage_responses.get("completion_tokens") or usage_responses.get("output_tokens") or 0)
            tot_res = int(usage_responses.get("total_tokens") or (in_res + out_res))
            in_chat = int(usage_chat.get("prompt_tokens") or usage_chat.get("input_tokens") or 0)
            out_chat = int(usage_chat.get("completion_tokens") or usage_chat.get("output_tokens") or 0)
            tot_chat = int(usage_chat.get("total_tokens") or (in_chat + out_chat))
            usage = {
                "input_tokens": in_res + in_chat,
                "output_tokens": out_res + out_chat,
                "total_tokens": tot_res + tot_chat,
            }
    except Exception as e:
        logger.warning(
            f"OPENAI responses call failed for model={model_id} symbol={current_symbol}: {e}. "
            "Falling back to /chat/completions."
        )
        # Fallback for older-compatible setups.
        fallback_started = time.time()
        chat_payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}],
            "max_completion_tokens": 140,
        }
        if supports_custom_temperature:
            chat_payload["temperature"] = 0.1

        logger.info(f"OPENAI_REQ POST {api_root}/chat/completions model={model_id} symbol={current_symbol}")
        logger.info(
            "OPENAI_REQ_VERBOSE endpoint=%s headers=%s payload=%s",
            f"{api_root}/chat/completions",
            json.dumps(safe_headers, default=str),
            json.dumps(chat_payload, default=str),
        )
        resp = requests.post(
            f"{api_root}/chat/completions",
            headers=headers,
            json=chat_payload,
            timeout=20,
        )
        logger.info(
            f"OPENAI_RES POST {api_root}/chat/completions -> {resp.status_code} "
            f"({int((time.time() - fallback_started) * 1000)}ms)"
        )
        logger.info("OPENAI_RES_VERBOSE endpoint=%s body=%s", f"{api_root}/chat/completions", (resp.text or ""))
        if not resp.ok:
            error_text = (resp.text or "").strip()[:500]
            logger.error(
                f"OPENAI_ERR model={model_id} symbol={current_symbol} "
                f"status={resp.status_code} body={error_text}"
            )
            resp.raise_for_status()
        payload = resp.json()
        choices = payload.get("choices") or []
        text = ((choices[0] or {}).get("message") or {}).get("content", "") if choices else ""
        usage = payload.get("usage", {}) or {}
        aggregate_usage["input_tokens"] += int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
        aggregate_usage["output_tokens"] += int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
        aggregate_usage["total_tokens"] += int(usage.get("total_tokens") or 0)

    latency_ms = int((time.time() - started) * 1000)
    if not text and error_text:
        text = f"Summary unavailable: {error_text}"
    if not text:
        # Final rescue path: use a lightweight non-reasoning model for text output.
        rescue_model = "gpt-4.1-mini"
        logger.warning(
            "OPENAI_EMPTY_OUTPUT model=%s symbol=%s. Attempting rescue model=%s",
            model_id,
            current_symbol,
            rescue_model,
        )
        rescue_payload = {
            "model": rescue_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 180,
        }
        logger.info("OPENAI_REQ POST %s/chat/completions model=%s symbol=%s", api_root, rescue_model, current_symbol)
        logger.info(
            "OPENAI_REQ_VERBOSE endpoint=%s headers=%s payload=%s",
            f"{api_root}/chat/completions",
            json.dumps(safe_headers, default=str),
            json.dumps(rescue_payload, default=str),
        )
        rescue_resp = requests.post(
            f"{api_root}/chat/completions",
            headers=headers,
            json=rescue_payload,
            timeout=20,
        )
        logger.info("OPENAI_RES POST %s/chat/completions -> %s", api_root, rescue_resp.status_code)
        logger.info("OPENAI_RES_VERBOSE endpoint=%s body=%s", f"{api_root}/chat/completions", (rescue_resp.text or ""))
        if rescue_resp.ok:
            rescue_json = rescue_resp.json()
            rescue_choices = rescue_json.get("choices") or []
            rescue_text = ((rescue_choices[0] or {}).get("message") or {}).get("content", "") if rescue_choices else ""
            if rescue_text:
                text = rescue_text.strip()
            rescue_usage = rescue_json.get("usage", {}) or {}
            aggregate_usage["input_tokens"] += int(rescue_usage.get("input_tokens") or rescue_usage.get("prompt_tokens") or 0)
            aggregate_usage["output_tokens"] += int(rescue_usage.get("output_tokens") or rescue_usage.get("completion_tokens") or 0)
            aggregate_usage["total_tokens"] += int(rescue_usage.get("total_tokens") or 0)
        if not text:
            text = "Summary unavailable: model returned empty output."
        logger.warning(f"OPENAI_EMPTY_OUTPUT model={model_id} symbol={current_symbol}")
        try:
            logger.warning(
                "OPENAI_EMPTY_OUTPUT_PAYLOAD model=%s symbol=%s payload=%s",
                model_id,
                current_symbol,
                json.dumps(payload or {}, default=str)[:2000],
            )
        except Exception:
            pass

    input_tokens = int(aggregate_usage.get("input_tokens") or usage.get("prompt_tokens") or usage.get("input_tokens") or _estimate_tokens(prompt))
    output_tokens = int(aggregate_usage.get("output_tokens") or usage.get("completion_tokens") or usage.get("output_tokens") or _estimate_tokens(text))
    total_tokens = int(aggregate_usage.get("total_tokens") or usage.get("total_tokens") or (input_tokens + output_tokens))
    cost = round(
        ((input_tokens / 1_000_000) * input_price_per_1m)
        + ((output_tokens / 1_000_000) * output_price_per_1m),
        8,
    )

    summary = {
        "text": (text or "").strip(),
        "model_id": model_id,
        "symbol": current_symbol,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cached": False,
    }
    usage_event = {
        "stage": "news_sentiment_summary",
        "model_id": model_id,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "latency_ms": latency_ms,
        "estimated_cost_usd": cost,
    }

    _SUMMARY_CACHE["ts"] = now
    _SUMMARY_CACHE["fingerprint"] = fingerprint
    _SUMMARY_CACHE["summary"] = summary
    _SUMMARY_CACHE["usage_event"] = usage_event

    out = dict(snapshot)
    out["llm_summary"] = dict(summary)
    logger.info(
        f"OPENAI_SUMMARY_OK model={model_id} symbol={current_symbol} "
        f"tokens={total_tokens} cost=${cost:.6f} latency_ms={latency_ms}"
    )
    return out, usage_event


def summarize_sentiment_with_openai(
    snapshot: Dict[str, Any],
    *,
    openai_api_key: str,
    openai_base_url: str,
    model_id: str = "gpt-5-nano",
    input_price_per_1m: float = 0.05,
    output_price_per_1m: float = 0.40,
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """
    Backward-compatible alias.
    Prefer `summarize_sentiment_with_api`.
    """
    return summarize_sentiment_with_api(
        snapshot,
        openai_api_key=openai_api_key,
        openai_base_url=openai_base_url,
        model_id=model_id,
        input_price_per_1m=input_price_per_1m,
        output_price_per_1m=output_price_per_1m,
    )


def summarize_sentiment_with_bedrock(
    snapshot: Dict[str, Any],
    *,
    model_id: str,
    aws_region: str = "us-east-1",
    input_price_per_1m: float = 3.0,
    output_price_per_1m: float = 15.0,
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """
    Bedrock equivalent of sentiment summarization used by dashboard.
    Returns (augmented_snapshot, usage_event_or_none).
    """
    fingerprint = _summary_fingerprint(snapshot)
    now = time.time()
    cached = _SUMMARY_CACHE.get("summary")
    cached_fp = _SUMMARY_CACHE.get("fingerprint", "")
    cached_symbol = str((cached or {}).get("symbol", "")).upper()
    current_symbol = str(snapshot.get("symbol", "")).upper()
    if (
        cached
        and cached_symbol == current_symbol
        and cached_fp == fingerprint
        and now - float(_SUMMARY_CACHE.get("ts", 0.0)) < SUMMARY_CACHE_TTL_SECONDS
    ):
        out = dict(snapshot)
        out["llm_summary"] = dict(cached)
        out["llm_summary"]["cached"] = True
        return out, None

    prompt = _build_summary_prompt(snapshot)
    started = time.time()
    try:
        req_payload = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 220,
            "temperature": 0.1,
            "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
        }
        logger.info("BEDROCK_REQ invoke_model model=%s symbol=%s region=%s", model_id, current_symbol, aws_region)
        logger.info(
            "BEDROCK_REQ_VERBOSE model=%s payload=%s",
            model_id,
            json.dumps(req_payload, default=str),
        )
        client = boto3.client(service_name="bedrock-runtime", region_name=aws_region)
        resp = None
        used_model_id = model_id
        last_error = None
        for candidate in _bedrock_model_candidates(model_id):
            try:
                logger.info("BEDROCK_REQ invoke_model_try model=%s symbol=%s", candidate, current_symbol)
                resp = client.invoke_model(
                    body=json.dumps(req_payload),
                    modelId=candidate,
                    accept="application/json",
                    contentType="application/json",
                )
                used_model_id = candidate
                break
            except Exception as e:
                last_error = e
                logger.warning("BEDROCK_RETRY model=%s symbol=%s err=%s", candidate, current_symbol, e)
                continue
        if resp is None:
            raise last_error or RuntimeError("Bedrock invoke failed")
        latency_ms = int((time.time() - started) * 1000)
        payload = json.loads(resp.get("body").read())
        logger.info("BEDROCK_RES invoke_model model=%s symbol=%s -> 200 (%sms)", used_model_id, current_symbol, latency_ms)
        logger.info("BEDROCK_RES_VERBOSE model=%s body=%s", used_model_id, json.dumps(payload, default=str))

        content = payload.get("content") or []
        text = ""
        if content and isinstance(content, list):
            text = str((content[0] or {}).get("text") or "").strip()
        if not text:
            choices = payload.get("choices") or []
            if choices and isinstance(choices, list):
                text = str((((choices[0] or {}).get("message") or {}).get("content") or "")).strip()
        if not text:
            text = "Summary unavailable: model returned empty output."
            logger.warning("BEDROCK_EMPTY_OUTPUT model=%s symbol=%s", model_id, current_symbol)

        usage = payload.get("usage", {}) or {}
        input_tokens = int(
            usage.get("input_tokens")
            or usage.get("inputTokens")
            or usage.get("prompt_tokens")
            or _estimate_tokens(prompt)
        )
        output_tokens = int(
            usage.get("output_tokens")
            or usage.get("outputTokens")
            or usage.get("completion_tokens")
            or _estimate_tokens(text)
        )
        total_tokens = int(usage.get("total_tokens") or usage.get("totalTokens") or (input_tokens + output_tokens))
        cost = round(
            ((input_tokens / 1_000_000) * input_price_per_1m)
            + ((output_tokens / 1_000_000) * output_price_per_1m),
            8,
        )

        summary = {
            "text": text,
            "model_id": used_model_id,
            "symbol": current_symbol,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cached": False,
        }
        usage_event = {
            "stage": "news_sentiment_summary",
            "model_id": used_model_id,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "latency_ms": latency_ms,
            "estimated_cost_usd": cost,
        }

        _SUMMARY_CACHE["ts"] = now
        _SUMMARY_CACHE["fingerprint"] = fingerprint
        _SUMMARY_CACHE["summary"] = summary
        _SUMMARY_CACHE["usage_event"] = usage_event

        out = dict(snapshot)
        out["llm_summary"] = dict(summary)
        logger.info(
            "BEDROCK_SUMMARY_OK model=%s symbol=%s tokens=%s cost=$%.6f latency_ms=%s",
            used_model_id,
            current_symbol,
            total_tokens,
            cost,
            latency_ms,
        )
        return out, usage_event
    except Exception as e:
        logger.error("BEDROCK_ERR model=%s symbol=%s error=%s", model_id, current_symbol, e, exc_info=True)
        out = dict(snapshot)
        out["llm_summary"] = {
            "text": f"LLM summary unavailable: {e}",
            "model_id": model_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cached": True,
        }
        return out, None


def summarize_sentiment_with_llm(
    snapshot: Dict[str, Any],
    *,
    provider: str,
    model_id: str,
    openai_api_key: str = "",
    openai_base_url: str = "https://api.openai.com/v1",
    aws_region: str = "us-east-1",
    input_price_per_1m: float = 0.05,
    output_price_per_1m: float = 0.40,
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    provider_upper = str(provider or "OPENAI").upper()
    if config.LOCAL_LLM_ENABLED:
        local_result = summarize_sentiment_with_local_model(snapshot)
        if local_result[0]:
            return local_result
    if provider_upper == "BEDROCK":
        return summarize_sentiment_with_bedrock(
            snapshot,
            model_id=model_id,
            aws_region=aws_region,
            input_price_per_1m=input_price_per_1m,
            output_price_per_1m=output_price_per_1m,
        )
    return summarize_sentiment_with_api(
        snapshot,
        openai_api_key=openai_api_key,
        openai_base_url=openai_base_url,
        model_id=model_id,
        input_price_per_1m=input_price_per_1m,
        output_price_per_1m=output_price_per_1m,
    )
