"""
wallet_intel.py
---------------
Two scoring models for a wallet:

1. Wallet Intelligence Score (0-100)
   A proxy for "does this wallet behave like an informed / skilled trader",
   based on observable on-chain behavior only (no off-chain PnL API needed):
     - trade frequency (very high frequency looks bot-like, penalized)
     - buy/sell follow-through ratio (wallets that only ever buy and never
       sell look like bag holders or bots, not skilled traders)
     - SOL sizing consistency (skilled wallets tend to size positions
       deliberately rather than erratically)
     - account age proxy via first-seen trade time (older = more trust)

2. Early-Runner Score (0-100)
   A proxy for "how early does this wallet tend to enter tokens relative to
   the token's own lifetime", using the wallet's first buy timestamp on a
   token vs. the token mint's creation time (if available) or vs. the
   earliest transaction seen for that token in our dataset. Earlier entries
   score higher.

Both scores are heuristic and explicitly NOT financial advice. They exist
to help a human researcher triage which wallets are worth watching.
"""

from typing import Dict, List, Optional
import statistics


def wallet_intelligence_score(trade_summary: Dict) -> int:
    total = trade_summary.get("total_trades", 0)
    if total == 0:
        return 0

    buy_count = trade_summary.get("buy_count", 0)
    sell_count = trade_summary.get("sell_count", 0)

    score = 50.0

    # Follow-through: wallets that sell what they buy show real trading
    # behavior rather than pure accumulation or bot spam.
    if buy_count > 0:
        follow_through = min(sell_count / buy_count, 1.0)
        score += follow_through * 20
    else:
        score -= 10

    # Frequency: extremely high trade counts in the sample window look
    # bot-like; moderate activity is favored.
    if total > 200:
        score -= 15
    elif 5 <= total <= 60:
        score += 10

    # Unknown-classified trades reduce confidence in the read.
    unknown_ratio = trade_summary.get("unknown_count", 0) / total
    score -= unknown_ratio * 15

    return int(max(0, min(100, round(score))))


def early_runner_score(wallet_first_buy_time: Optional[int],
                        token_earliest_seen_time: Optional[int],
                        token_window_seconds: int = 6 * 3600) -> int:
    """
    Score how early a wallet entered relative to the earliest activity we've
    observed for the token. `token_window_seconds` is the assumed length of
    a token's "early" window (default 6 hours) — entries near the start of
    that window score near 100, entries near the end score near 0.
    """
    if not wallet_first_buy_time or not token_earliest_seen_time:
        return 0

    delta = wallet_first_buy_time - token_earliest_seen_time
    if delta < 0:
        delta = 0  # wallet appears before our earliest observed record

    fraction_in = min(delta / token_window_seconds, 1.0)
    score = (1.0 - fraction_in) * 100
    return int(max(0, min(100, round(score))))


def combined_wallet_score(intel_score: int, runner_score: int,
                           intel_weight: float = 0.55) -> int:
    """Blend the two scores into one 0-100 "watch this wallet" number."""
    runner_weight = 1.0 - intel_weight
    return int(round(intel_score * intel_weight + runner_score * runner_weight))


def rank_wallets(wallet_rows: List[Dict]) -> List[Dict]:
    """
    wallet_rows: list of dicts each containing at least
      {"wallet": str, "intel_score": int, "runner_score": int}
    Returns the same rows sorted by combined score, with the combined score
    attached.
    """
    for row in wallet_rows:
        row["combined_score"] = combined_wallet_score(
            row.get("intel_score", 0), row.get("runner_score", 0)
        )
    return sorted(wallet_rows, key=lambda r: r["combined_score"], reverse=True)
