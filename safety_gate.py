"""
safety_gate.py
--------------
Hard safety checks on a token, and the logic that unifies every signal
(wallet scores, convergence, X attention, safety) into one status:

    BLOCKED   - a hard safety check failed (mint authority live, frozen,
                extreme concentration). We recommend never alerting on
                these regardless of how good the other signals look.
    WATCH     - passes safety, but wallet/attention signals are weak/early.
    BUILDING  - passes safety, multiple signals trending up but not yet
                at alert threshold.
    ALERT     - passes safety, strong convergence + attention acceleration.

This app never executes trades and never claims a token is "safe to buy" —
it only reports what is observable on-chain. Always DYOR.
"""

from typing import Dict, List, Optional


def check_mint_authority(mint_account_info: Optional[Dict]) -> Dict:
    """A live mint authority means the deployer can mint unlimited new
    supply at will — a classic rug vector."""
    if not mint_account_info or not mint_account_info.get("value"):
        return {"passed": False, "reason": "Could not read mint account"}

    parsed = (
        mint_account_info["value"]
        .get("data", {})
        .get("parsed", {})
        .get("info", {})
    )
    mint_authority = parsed.get("mintAuthority")
    return {
        "passed": mint_authority is None,
        "reason": "Mint authority renounced" if mint_authority is None
                   else "Mint authority still active — supply can be inflated",
    }


def check_freeze_authority(mint_account_info: Optional[Dict]) -> Dict:
    """A live freeze authority lets the deployer freeze holder wallets,
    preventing them from ever selling."""
    if not mint_account_info or not mint_account_info.get("value"):
        return {"passed": False, "reason": "Could not read mint account"}

    parsed = (
        mint_account_info["value"]
        .get("data", {})
        .get("parsed", {})
        .get("info", {})
    )
    freeze_authority = parsed.get("freezeAuthority")
    return {
        "passed": freeze_authority is None,
        "reason": "Freeze authority renounced" if freeze_authority is None
                   else "Freeze authority still active — holders can be frozen",
    }


def check_holder_concentration(largest_accounts: List[Dict], total_supply: float,
                                max_top10_share: float = 0.35) -> Dict:
    """Flags tokens where the top 10 holders (excluding the LP itself, which
    the caller should filter out beforehand) control a large share of supply."""
    if not largest_accounts or not total_supply:
        return {"passed": False, "reason": "Could not read holder data", "top10_share": None}

    top10 = largest_accounts[:10]
    top10_amount = sum(float(a.get("uiAmount") or 0) for a in top10)
    share = top10_amount / total_supply if total_supply else 1.0

    return {
        "passed": share <= max_top10_share,
        "reason": f"Top 10 holders control {share:.0%} of supply",
        "top10_share": round(share, 4),
    }


def check_lp_lock(lp_locked: Optional[bool], lp_lock_source: str = "unknown") -> Dict:
    """
    LP lock status typically isn't derivable from raw RPC calls alone —
    it requires reading the specific locker program's state (e.g. Streamflow,
    Team Finance) or a token-safety API. This function takes the answer as
    an input so it can be wired up to whichever source you trust; in demo
    mode the caller supplies a simulated value.
    """
    if lp_locked is None:
        return {"passed": False, "reason": "LP lock status unknown", "source": lp_lock_source}
    return {
        "passed": bool(lp_locked),
        "reason": "LP appears locked" if lp_locked else "LP does not appear locked — rug risk",
        "source": lp_lock_source,
    }


def check_honeypot_risk(simulated_sell_ok: Optional[bool]) -> Dict:
    """
    True honeypot detection requires simulating a sell transaction against
    the DEX program (or calling a dedicated honeypot-check API) — this
    function takes that result as an input so it can be wired to whichever
    checker you trust. In demo mode the caller supplies a simulated value.
    """
    if simulated_sell_ok is None:
        return {"passed": False, "reason": "Sell simulation unavailable"}
    return {
        "passed": bool(simulated_sell_ok),
        "reason": "Sell simulation succeeded" if simulated_sell_ok
                   else "Sell simulation failed — possible honeypot",
    }


def run_safety_gate(mint_account_info, largest_accounts, total_supply,
                     lp_locked, simulated_sell_ok) -> Dict:
    checks = {
        "mint_authority": check_mint_authority(mint_account_info),
        "freeze_authority": check_freeze_authority(mint_account_info),
        "holder_concentration": check_holder_concentration(largest_accounts, total_supply),
        "lp_lock": check_lp_lock(lp_locked),
        "honeypot": check_honeypot_risk(simulated_sell_ok),
    }
    all_passed = all(c["passed"] for c in checks.values())
    failed = [name for name, c in checks.items() if not c["passed"]]
    return {"passed": all_passed, "failed_checks": failed, "checks": checks}


def unified_status(safety_result: Dict, convergence_wallet_count: int,
                    attention_label: str, avg_wallet_score: float) -> str:
    """
    Combine the safety gate result with convergence + attention signals into
    one of BLOCKED / WATCH / BUILDING / ALERT.
    """
    if not safety_result.get("passed", False):
        return "BLOCKED"

    strong_convergence = convergence_wallet_count >= 3
    good_wallets = avg_wallet_score >= 60
    hot_attention = attention_label in ("SPIKING", "BUILDING")

    if strong_convergence and good_wallets and attention_label == "SPIKING":
        return "ALERT"

    if (strong_convergence and good_wallets) or (good_wallets and hot_attention):
        return "BUILDING"

    return "WATCH"
