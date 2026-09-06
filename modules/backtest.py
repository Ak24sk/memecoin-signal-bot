"""
backtest.py
-----------
Validates the wallet intelligence / early-runner / convergence scores
against what actually happened to token prices afterward, using real
historical prices from gecko_price.py.

Honesty notes:
- Requires REAL token mint addresses GeckoTerminal has indexed pools for.
  Demo Mode's synthetic mints will not return data.
- A correlation near 0 is a real, useful finding, not a failure.
- Small samples can look misleadingly strong by chance.
"""

from typing import Dict, List, Optional
from modules import gecko_price as gp


def evaluate_trades(buy_events, horizon_seconds=3600, max_trades=20, progress_callback=None):
    results = []
    trimmed = buy_events[:max_trades]
    for i, event in enumerate(trimmed):
        forward_return = gp.compute_forward_return(
            mint_address=event["token_mint"],
            entry_unix_time=int(event["block_time"]),
            horizon_seconds=horizon_seconds,
        )
        enriched = dict(event)
        enriched["forward_return_pct"] = forward_return
        results.append(enriched)
        if progress_callback:
            progress_callback(i + 1, len(trimmed))
    return results


def pearson_correlation(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    n = len(pairs)
    if n < 2:
        return None
    xs_v = [p[0] for p in pairs]
    ys_v = [p[1] for p in pairs]
    mean_x = sum(xs_v) / n
    mean_y = sum(ys_v) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in pairs)
    var_x = sum((x - mean_x) ** 2 for x in xs_v)
    var_y = sum((y - mean_y) ** 2 for y in ys_v)
    if var_x == 0 or var_y == 0:
        return None
    return round(cov / ((var_x ** 0.5) * (var_y ** 0.5)), 3)


def summarize_validation(evaluated_trades, score_field="combined_score"):
    with_data = [t for t in evaluated_trades if t.get("forward_return_pct") is not None]
    missing = len(evaluated_trades) - len(with_data)
    scores = [t.get(score_field) for t in with_data]
    returns = [t.get("forward_return_pct") for t in with_data]
    correlation = pearson_correlation(scores, returns)

    if correlation is None:
        interpretation = (
            "Not enough real price data was found to compute a meaningful "
            "correlation. This usually means the tested tokens are too new, "
            "too illiquid, or not indexed by GeckoTerminal yet."
        )
    elif correlation >= 0.4:
        interpretation = (
            f"Correlation of {correlation}: higher-scored trades in this "
            "sample did tend to see better forward returns."
        )
    elif correlation <= -0.4:
        interpretation = (
            f"Correlation of {correlation}: higher-scored trades in this "
            "sample tended to see WORSE forward returns."
        )
    else:
        interpretation = (
            f"Correlation of {correlation}: no meaningful relationship found "
            "between the score and what happened to price afterward."
        )

    return {
        "total_trades": len(evaluated_trades),
        "trades_with_price_data": len(with_data),
        "trades_missing_data": missing,
        "correlation": correlation,
        "interpretation": interpretation,
        "avg_forward_return_pct": round(sum(returns) / len(returns), 2) if returns else None,
    }
