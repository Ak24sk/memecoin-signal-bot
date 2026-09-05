"""
demo_data.py
------------
Generates believable synthetic data so the whole app can be explored on
Streamlit Community Cloud with zero API keys and zero live RPC calls. Also
provides CSV loaders for the "bring your own data" mode.
"""

import random
from datetime import datetime, timedelta, timezone
from typing import Dict, List
import pandas as pd

FAKE_TICKERS = ["WOJAK2", "FROGGY", "MOONCAT", "BONKZ", "PEPESOL",
                "TURBOAPE", "RUGCHECK", "SOLDOGE", "NANOFOX", "ZKPUP"]


def _fake_address(rnd: random.Random, prefix: str = "") -> str:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    return prefix + "".join(rnd.choice(alphabet) for _ in range(40))


def generate_demo_wallets(n: int = 12, seed: int = 42) -> pd.DataFrame:
    rnd = random.Random(seed)
    rows = []
    for i in range(n):
        buy_count = rnd.randint(2, 40)
        sell_count = rnd.randint(0, buy_count)
        rows.append({
            "wallet": _fake_address(rnd, "W"),
            "total_trades": buy_count + sell_count + rnd.randint(0, 5),
            "buy_count": buy_count,
            "sell_count": sell_count,
            "unknown_count": rnd.randint(0, 3),
            "first_trade_time": int((datetime.now(timezone.utc) -
                                      timedelta(days=rnd.randint(5, 400))).timestamp()),
        })
    return pd.DataFrame(rows)


def generate_demo_tokens(n: int = 8, seed: int = 7) -> pd.DataFrame:
    rnd = random.Random(seed)
    rows = []
    for i in range(n):
        ticker = FAKE_TICKERS[i % len(FAKE_TICKERS)]
        mint = _fake_address(rnd, "T")
        top10_share = round(rnd.uniform(0.08, 0.55), 3)
        rows.append({
            "token_mint": mint,
            "ticker": ticker,
            "total_supply": rnd.choice([1_000_000_000, 100_000_000, 1_000_000_000_000]),
            "top10_holder_share": top10_share,
            "mint_authority_renounced": rnd.random() > 0.3,
            "freeze_authority_renounced": rnd.random() > 0.2,
            "lp_locked": rnd.random() > 0.35,
            "sell_simulation_ok": rnd.random() > 0.1,
            "created_minutes_ago": rnd.randint(10, 600),
        })
    return pd.DataFrame(rows)


def generate_demo_buy_events(wallets_df: pd.DataFrame, tokens_df: pd.DataFrame,
                              seed: int = 99) -> pd.DataFrame:
    """Synthetic buy events used to feed the convergence detector — some
    tokens get a cluster of near-simultaneous buys from several wallets."""
    rnd = random.Random(seed)
    rows = []
    now = datetime.now(timezone.utc)

    for _, token in tokens_df.iterrows():
        cluster_size = rnd.choice([0, 0, 1, 2, 4, 6])
        anchor_time = now - timedelta(minutes=rnd.randint(5, 500))
        chosen_wallets = wallets_df.sample(min(cluster_size, len(wallets_df)), random_state=rnd.randint(0, 9999))
        for _, w in chosen_wallets.iterrows():
            jitter = timedelta(minutes=rnd.randint(-15, 15))
            rows.append({
                "wallet": w["wallet"],
                "token_mint": token["token_mint"],
                "ticker": token["ticker"],
                "block_time": int((anchor_time + jitter).timestamp()),
            })
    return pd.DataFrame(rows)


def load_csv(path_or_buffer) -> pd.DataFrame:
    return pd.read_csv(path_or_buffer)
