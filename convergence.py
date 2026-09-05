"""
convergence.py
--------------
Wallet convergence detection: flags when multiple independent wallets
(especially high-scoring ones) buy the same token within a short time
window of each other. Independent convergence is a much stronger signal
than any single wallet's activity, and is much harder to fake than a
single wallet's history.
"""

from collections import defaultdict
from typing import Dict, List


def detect_convergence(buy_events: List[Dict], window_seconds: int = 1800,
                        min_wallets: int = 3) -> List[Dict]:
    """
    buy_events: list of dicts like
      {"wallet": str, "token_mint": str, "block_time": int, "combined_score": int}

    Returns a list of convergence clusters:
      {"token_mint": str, "wallet_count": int, "wallets": [...],
       "window_start": int, "window_end": int, "avg_wallet_score": float}
    """
    by_token = defaultdict(list)
    for ev in buy_events:
        if ev.get("block_time") is not None:
            by_token[ev["token_mint"]].append(ev)

    clusters = []
    for token_mint, events in by_token.items():
        events = sorted(events, key=lambda e: e["block_time"])
        n = len(events)
        i = 0
        while i < n:
            window_wallets = {events[i]["wallet"]}
            window_events = [events[i]]
            j = i + 1
            while j < n and events[j]["block_time"] - events[i]["block_time"] <= window_seconds:
                window_wallets.add(events[j]["wallet"])
                window_events.append(events[j])
                j += 1

            if len(window_wallets) >= min_wallets:
                scores = [e.get("combined_score", 0) for e in window_events]
                clusters.append({
                    "token_mint": token_mint,
                    "wallet_count": len(window_wallets),
                    "wallets": sorted(window_wallets),
                    "window_start": events[i]["block_time"],
                    "window_end": window_events[-1]["block_time"],
                    "avg_wallet_score": round(sum(scores) / len(scores), 1) if scores else 0,
                })
                i = j  # skip past this cluster
            else:
                i += 1

    return sorted(clusters, key=lambda c: (c["wallet_count"], c["avg_wallet_score"]), reverse=True)
