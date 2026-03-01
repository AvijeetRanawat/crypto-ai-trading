from __future__ import annotations

import html
import json
import re
import time
import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree

import requests


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


def fetch_cryptocompare_news(api_key: str, limit: int = 10) -> List[Dict[str, Any]]:
    if not api_key:
        return []

    data = _safe_get_json(
        "https://min-api.cryptocompare.com/data/v2/news/",
        params={
            "lang": "EN",
            "categories": "BTC,Bitcoin",
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


def fetch_alpha_vantage_news(api_key: str, limit: int = 10) -> List[Dict[str, Any]]:
    if not api_key:
        return []

    data = _safe_get_json(
        "https://www.alphavantage.co/query",
        params={
            "function": "NEWS_SENTIMENT",
            "tickers": "CRYPTO:BTC",
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


def fetch_gdelt_news(limit: int = 12) -> List[Dict[str, Any]]:
    data = _safe_get_json(
        "https://api.gdeltproject.org/api/v2/doc/doc",
        params={
            "query": "bitcoin OR btc OR cryptocurrency",
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


def build_sentiment_snapshot(alpha_key: str, cryptocompare_key: str) -> Dict[str, Any]:
    now = time.time()
    cached_payload = _CACHE.get("payload")
    if cached_payload and now - float(_CACHE.get("ts", 0.0)) < CACHE_TTL_SECONDS:
        return cached_payload

    provider_items: Dict[str, List[Dict[str, Any]]] = {
        "alphavantage": fetch_alpha_vantage_news(alpha_key, limit=10),
        "cryptocompare": fetch_cryptocompare_news(cryptocompare_key, limit=10),
        "cointelegraph": fetch_cointelegraph_rss(limit=10),
        "gdelt": fetch_gdelt_news(limit=10),
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
        "symbol": "BTCUSDT",
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


def _build_summary_prompt(snapshot: Dict[str, Any]) -> str:
    score = snapshot.get("sentiment_score", 0.0)
    label = snapshot.get("sentiment_label", "NEUTRAL")
    components = snapshot.get("components", {}) or {}
    fear_greed = components.get("fear_greed", {}) or {}
    headlines = snapshot.get("articles", [])[:8]

    lines = [
        "Summarize BTC market sentiment for a trader in <= 70 words.",
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
    if (
        cached
        and cached_fp == fingerprint
        and now - float(_SUMMARY_CACHE.get("ts", 0.0)) < SUMMARY_CACHE_TTL_SECONDS
    ):
        out = dict(snapshot)
        out["llm_summary"] = dict(cached)
        out["llm_summary"]["cached"] = True
        return out, None

    prompt = _build_summary_prompt(snapshot)
    started = time.time()
    resp = requests.post(
        f"{openai_base_url.rstrip('/')}/chat/completions",
        headers={
            "Authorization": f"Bearer {openai_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 140,
        },
        timeout=20,
    )
    resp.raise_for_status()
    payload = resp.json()
    latency_ms = int((time.time() - started) * 1000)

    choices = payload.get("choices") or []
    text = ((choices[0] or {}).get("message") or {}).get("content", "") if choices else ""
    usage = payload.get("usage", {}) or {}
    input_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or _estimate_tokens(prompt))
    output_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or _estimate_tokens(text))
    total_tokens = int(usage.get("total_tokens") or (input_tokens + output_tokens))
    cost = round(
        ((input_tokens / 1_000_000) * input_price_per_1m)
        + ((output_tokens / 1_000_000) * output_price_per_1m),
        8,
    )

    summary = {
        "text": (text or "").strip(),
        "model_id": model_id,
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
    return out, usage_event
