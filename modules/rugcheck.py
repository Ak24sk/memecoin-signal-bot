"""
rugcheck.py
-----------
Optional integration with RugCheck's free public API (api.rugcheck.xyz) to
fill in the two safety checks that plain Solana RPC calls can't answer:
LP-lock status and honeypot/high-risk signals.

RugCheck's `/tokens/{mint}/report/summary` endpoint is used by several
open-source Solana tooling projects without an API key for basic reports,
so this module calls it directly with no auth. That said, RugCheck is a
third-party service Claude cannot vouch for the uptime, rate limits, or
schema stability of — treat this integration as best-effort. If the call
fails or the response doesn't contain the fields we expect, every function
here returns `None` (== "unknown") rather than guessing, so the safety gate
correctly shows "status unknown" instead of a false pass or fail.

IMPORTANT: RugCheck does not run an actual sell-simulation for you. What we
derive as `honeypot_proxy` is really "does RugCheck's own risk engine flag
this token with a high-severity warning" — a reasonable proxy signal, but
not the same guarantee as a real swap simulation. Treat it as one more data
point, not a verdict.
"""

from typing import Dict, Optional
import requests

RUGCHECK_BASE_URL = "https://api.rugcheck.xyz/v1"
REQUEST_TIMEOUT = 10

# A market's LP is treated as "locked" if at least this share of LP tokens
# are reported locked/burned. RugCheck reports this per-market; we take the
# best (highest) figure across all markets found for the mint.
LP_LOCKED_THRESHOLD = 0.80

# RugCheck risk severities that should count as a hard red flag for our
# honeypot proxy. Exact level strings can vary by RugCheck API version, so
# we match case-insensitively against a small set of known "bad" labels.
HIGH_SEVERITY_LEVELS = {"danger", "high", "critical"}


class RugCheckError(Exception):
    """Raised when RugCheck is unreachable or returns an unexpected response."""
    pass


def get_token_summary(mint_address: str) -> Dict:
    """Fetch RugCheck's summary risk report for a token mint. Raises
    RugCheckError on network failure or a non-2xx response."""
    url = f"{RUGCHECK_BASE_URL}/tokens/{mint_address}/report/summary"
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json() or {}
    except requests.RequestException as e:
        raise RugCheckError(f"RugCheck request failed: {e}")
    except ValueError as e:
        raise RugCheckError(f"RugCheck returned unparseable JSON: {e}")


def derive_lp_lock_status(summary: Dict) -> Optional[bool]:
    """
    Look through the summary's reported markets for LP-lock percentage data.
    Returns True/False if we found usable data, or None if the response
    didn't include anything we recognize as LP-lock info.
    """
    markets = summary.get("markets") or summary.get("liquidity") or []
    if not isinstance(markets, list) or not markets:
        return None

    best_locked_pct = None
    for market in markets:
        if not isinstance(market, dict):
            continue
        lp = market.get("lp") or market
        pct = (
            lp.get("lpLockedPct")
            or lp.get("lockedPct")
            or lp.get("lpLockedPercent")
        )
        if pct is not None:
            try:
                pct = float(pct)
                # Some responses report 0-1, others 0-100 — normalize to 0-1.
                if pct > 1:
                    pct = pct / 100.0
                if best_locked_pct is None or pct > best_locked_pct:
                    best_locked_pct = pct
            except (TypeError, ValueError):
                continue

    if best_locked_pct is None:
        return None
    return best_locked_pct >= LP_LOCKED_THRESHOLD


def derive_honeypot_proxy(summary: Dict) -> Optional[bool]:
    """
    Proxy for "is this token sellable" based on RugCheck's own aggregated
    risk flags, since we don't run a real sell-simulation here. Returns
    False (flagged) if any high-severity risk is present, True if RugCheck
    reported risks but none were high-severity, or None if no risk list was
    present at all (i.e. we genuinely don't know).
    """
    risks = summary.get("risks")
    if risks is None:
        return None
    if not isinstance(risks, list):
        return None

    for risk in risks:
        if not isinstance(risk, dict):
            continue
        level = str(risk.get("level", "")).lower()
        if level in HIGH_SEVERITY_LEVELS:
            return False

    return True


def get_lp_lock_and_honeypot(mint_address: str) -> Dict:
    """
    Convenience wrapper: fetches the RugCheck summary once and returns both
    derived signals plus the raw risk list (for display), so the UI can
    show *why* something was flagged, not just a bare pass/fail.

    On any failure, returns all-None values with an `error` message instead
    of raising, so a flaky third-party API never crashes the app — the
    safety gate already treats None as "status unknown" and blocks
    accordingly.
    """
    try:
        summary = get_token_summary(mint_address)
    except RugCheckError as e:
        return {
            "lp_locked": None,
            "honeypot_proxy": None,
            "risks": [],
            "score": None,
            "error": str(e),
        }

    return {
        "lp_locked": derive_lp_lock_status(summary),
        "honeypot_proxy": derive_honeypot_proxy(summary),
        "risks": summary.get("risks") or [],
        "score": summary.get("score"),
        "error": None,
}
