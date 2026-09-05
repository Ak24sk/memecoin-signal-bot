"""
modules/buy_sell.py
-----------
Heuristic buy/sell detection from a wallet's parsed transaction history.

We don't have a perfect ground-truth label for "this was a buy" vs "this was
a sell" without decoding every DEX program individually. Instead we use a
practical proxy that works across most Solana DEX swaps (Jupiter, Raydium,
Pump.fun, Orca, etc.):

  - Look at SOL balance change and target-token balance change for the
    wallet within the same transaction.
  - SOL decreases + token increases  -> BUY
  - SOL increases + token decreases  -> SELL
  - Otherwise                        -> UNKNOWN (transfer, airdrop, etc.)

This is intentionally conservative. It will misclassify some edge cases
(e.g. multi-hop routes, LP deposits) but is a solid signal for "does this
wallet appear to be accumulating or distributing this token".
"""

from dataclasses import dataclass
from typing import Optional, List, Dict

LAMPORTS_PER_SOL = 1_000_000_000


@dataclass
class TradeEvent:
    signature: str
    slot: int
    block_time: Optional[int]
    action: str          # "BUY", "SELL", or "UNKNOWN"
    sol_delta: float      # positive = SOL gained, negative = SOL spent
    token_delta: float    # positive = tokens gained, negative = tokens spent


def _find_owner_balances(tx: Dict, owner: str, mint: str):
    """Extract pre/post SOL and target-token balances for `owner` in a tx."""
    meta = tx.get("meta") or {}
    message = (tx.get("transaction") or {}).get("message") or {}
    account_keys = message.get("accountKeys") or []

    sol_pre = sol_post = None
    for idx, key in enumerate(account_keys):
        pubkey = key.get("pubkey") if isinstance(key, dict) else key
        if pubkey == owner:
            pre_balances = meta.get("preBalances") or []
            post_balances = meta.get("postBalances") or []
            if idx < len(pre_balances) and idx < len(post_balances):
                sol_pre = pre_balances[idx] / LAMPORTS_PER_SOL
                sol_post = post_balances[idx] / LAMPORTS_PER_SOL
            break

    token_pre = token_post = 0.0
    for bal in meta.get("preTokenBalances") or []:
        if bal.get("owner") == owner and bal.get("mint") == mint:
            token_pre = float(bal.get("uiTokenAmount", {}).get("uiAmount") or 0)
    for bal in meta.get("postTokenBalances") or []:
        if bal.get("owner") == owner and bal.get("mint") == mint:
            token_post = float(bal.get("uiTokenAmount", {}).get("uiAmount") or 0)

    return sol_pre, sol_post, token_pre, token_post


def classify_transaction(tx: Dict, owner: str, mint: str) -> Optional[TradeEvent]:
    """Classify a single parsed transaction as BUY / SELL / UNKNOWN for a
    given wallet + token mint. Returns None if the tx can't be parsed."""
    if not tx or not tx.get("meta"):
        return None

    signature = None
    sigs = ((tx.get("transaction") or {}).get("signatures")) or []
    if sigs:
        signature = sigs[0]

    sol_pre, sol_post, token_pre, token_post = _find_owner_balances(tx, owner, mint)
    if sol_pre is None:
        return None

    sol_delta = sol_post - sol_pre
    token_delta = token_post - token_pre

    if sol_delta < 0 and token_delta > 0:
        action = "BUY"
    elif sol_delta > 0 and token_delta < 0:
        action = "SELL"
    else:
        action = "UNKNOWN"

    return TradeEvent(
        signature=signature or "unknown",
        slot=tx.get("slot", 0),
        block_time=tx.get("blockTime"),
        action=action,
        sol_delta=round(sol_delta, 6),
        token_delta=round(token_delta, 6),
    )


def summarize_trades(trades: List[TradeEvent]) -> Dict:
    """Roll up a list of TradeEvents into wallet-level stats used by scoring."""
    buys = [t for t in trades if t.action == "BUY"]
    sells = [t for t in trades if t.action == "SELL"]
    return {
        "total_trades": len(trades),
        "buy_count": len(buys),
        "sell_count": len(sells),
        "unknown_count": len(trades) - len(buys) - len(sells),
        "total_sol_spent_on_buys": round(-sum(t.sol_delta for t in buys), 6),
        "total_sol_received_on_sells": round(sum(t.sol_delta for t in sells), 6),
        "first_trade_time": min((t.block_time for t in trades if t.block_time), default=None),
        "last_trade_time": max((t.block_time for t in trades if t.block_time), default=None),
    }
