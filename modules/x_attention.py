"""
x_attention.py
--------------
Early-attention detector for a token/ticker on X (Twitter).

Two modes:

1. Demo mode (default, no API keys required)
   Generates a plausible synthetic attention timeline so the app is fully
   explorable on Streamlit Community Cloud without any paid API access.

2. Live mode (optional)
   If an X API v2 bearer token is provided via Streamlit secrets as
   X_BEARER_TOKEN, this module can pull recent post-count timeseries for a
   query via the official "recent counts" endpoint. This requires a paid
   X API tier — this file only wires up the call; you must supply your own
   token. We deliberately do NOT scrape X/Twitter, which would violate its
   terms of service.

Attention acceleration is measured the same way in both modes: we compare
post-volume growth rate over a short window vs. a longer baseline window,
and estimate what fraction of accounts look "bot-like" using simple
heuristics (duplicate near-identical text, account age, follower/following
ratio) when that data is available.
"""

import math
import random
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import requests

X_RECENT_COUNTS_URL = "https://api.twitter.com/2/tweets/counts/recent"


def _synthetic_timeline(seed: str, hours: int = 12, accelerating: bool = None) -> List[Dict]:
    """Deterministic-ish synthetic hourly post counts for demo mode."""
    rnd = random.Random(seed)
    if accelerating is None:
        accelerating = rnd.random() > 0.5

    base = rnd.randint(3, 15)
    counts = []
    now = datetime.now(timezone.utc)
    for h in range(hours, 0, -1):
        t = now - timedelta(hours=h)
        if accelerating:
            growth = math.exp((hours - h) / hours * 2.2)
        else:
            growth = 1 + rnd.uniform(-0.1, 0.1)
        noise = rnd.uniform(0.8, 1.2)
        count = max(0, int(base * growth * noise))
        counts.append({"hour_start": t.isoformat(), "post_count": count})
    return counts


def get_attention_timeline(query: str, bearer_token: Optional[str] = None,
                            demo_mode: bool = True) -> List[Dict]:
    if demo_mode or not bearer_token:
        return _synthetic_timeline(seed=query)

    headers = {"Authorization": f"Bearer {bearer_token}"}
    params = {"query": query, "granularity": "hour"}
    resp = requests.get(X_RECENT_COUNTS_URL, headers=headers, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json().get("data", [])
    return [
        {"hour_start": d["start"], "post_count": d["tweet_count"]}
        for d in data
    ]


def compute_acceleration(timeline: List[Dict], short_window: int = 3,
                          long_window: int = 9) -> Dict:
    """
    Compare average post volume over the most recent `short_window` hours
    vs. the preceding `long_window` hours to get an acceleration ratio.
    Ratio > 1.5 is treated as "building"; > 3.0 as a strong attention spike.
    """
    if len(timeline) < short_window + 1:
        return {"acceleration_ratio": 0.0, "label": "INSUFFICIENT_DATA"}

    counts = [row["post_count"] for row in timeline]
    recent = counts[-short_window:]
    prior = counts[max(0, len(counts) - short_window - long_window): len(counts) - short_window]

    recent_avg = sum(recent) / len(recent) if recent else 0
    prior_avg = sum(prior) / len(prior) if prior else 0.001  # avoid div-by-zero

    ratio = round(recent_avg / max(prior_avg, 0.001), 2)

    if ratio >= 3.0:
        label = "SPIKING"
    elif ratio >= 1.5:
        label = "BUILDING"
    elif ratio <= 0.6:
        label = "FADING"
    else:
        label = "FLAT"

    return {
        "acceleration_ratio": ratio,
        "recent_avg_per_hour": round(recent_avg, 1),
        "prior_avg_per_hour": round(prior_avg, 1),
        "label": label,
    }


def estimate_bot_share(sample_posts: Optional[List[Dict]] = None, seed: str = "") -> float:
    """
    Rough bot/coordinated-promotion share estimate (0.0-1.0).
    In demo mode (no sample_posts) this returns a plausible synthetic value.
    In live mode, pass posts with fields like {"text":..., "account_age_days":...,
    "followers":..., "following":...} and this applies simple heuristics:
    near-duplicate text and very young / lopsided-ratio accounts count as
    likely-bot.
    """
    if not sample_posts:
        rnd = random.Random(seed or "bot-share")
        return round(rnd.uniform(0.1, 0.6), 2)

    flagged = 0
    seen_texts = set()
    for post in sample_posts:
        text_key = (post.get("text") or "").strip().lower()[:40]
        is_dup = text_key in seen_texts
        seen_texts.add(text_key)

        young_account = (post.get("account_age_days") or 9999) < 14
        lopsided = (post.get("following", 0) > 0 and
                    post.get("followers", 1) / max(post.get("following", 1), 1) < 0.05)

        if is_dup or young_account or lopsided:
            flagged += 1

    return round(flagged / len(sample_posts), 2) if sample_posts else 0.0
