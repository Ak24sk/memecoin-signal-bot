"""
gecko_price.py
--------------
Real historical Solana DEX prices via GeckoTerminal's free public API.
No API key required for the base endpoints used here.
"""

import time
from typing import Dict, List, Optional
import requests

GECKO_BASE_URL = "https://api.geckoterminal.com/api/v2"
REQUEST_TIMEOUT = 10
MIN_SECONDS_BETWEEN_CALLS = 6.5

_last_call_time = 0.0


class GeckoPriceError(Exception):
    pass


def _throttled_get(url, params=None):
    global _last_call_time
    elapsed = time.time() - _last_call_time
    if elapsed < MIN_SECONDS_BETWEEN_CALLS:
        time.sleep(MIN_SECONDS_BETWEEN_CALLS - elapsed)
    try:
        resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        _last_call_time = time.time()
        resp.raise_for_status()
        return resp.json() or {}
    except requests.RequestException as e:
        _last_call_time = time.time()
        raise GeckoPriceError(f"GeckoTerminal request failed: {e}")
    except ValueError as e:
        raise GeckoPriceError(f"GeckoTerminal returned unparseable JSON: {e}")


def get_best_pool_for_token(mint_address, network="solana"):
    url = f"{GECKO_BASE_URL}/networks/{network}/tokens/{mint_address}/pools"
    try:
        data = _throttled_get(url)
    except GeckoPriceError:
        return None
    pools = data.get("data") or []
    if not pools:
        return None
    def _liquidity(pool):
        try:
            return float(pool.get("attributes", {}).get("reserve_in_usd") or 0)
        except (TypeError, ValueError):
            return 0.0
    best = max(pools, key=_liquidity)
    return best.get("id", "").split("_", 1)[-1] if best.get("id") else None

def get_ohlcv(pool_address, timeframe="minute", aggregate=1,
              before_timestamp=None, limit=100, network="solana"):
    url = f"{GECKO_BASE_URL}/networks/{network}/pools/{pool_address}/ohlcv/{timeframe}"
    params = {"aggregate": aggregate, "limit": limit, "currency": "usd"}
    if before_timestamp:
        params["before_timestamp"] = before_timestamp
    try:
        data = _throttled_get(url, params=params)
    except GeckoPriceError:
        return []
    ohlcv_list = data.get("data", {}).get("attributes", {}).get("ohlcv_list", [])
    return [
        {
            "timestamp": row[0],
            "open": row[1],
            "high": row[2],
            "low": row[3],
            "close": row[4],
            "volume": row[5],
        }
        for row in ohlcv_list
        if isinstance(row, list) and len(row) >= 6
    ]


def get_price_near_time(mint_address, unix_time, pool_address=None):
    pool_address = pool_address or get_best_pool_for_token(mint_address)
    if not pool_address:
        return None
    candles = get_ohlcv(
        pool_address, timeframe="minute", aggregate=1,
        before_timestamp=unix_time + 3600, limit=100,
    )
    if not candles:
        return None
    closest = min(candles, key=lambda c: abs(c["timestamp"] - unix_time))
    return closest.get("close")


def compute_forward_return(mint_address, entry_unix_time, horizon_seconds, pool_address=None):
    pool_address = pool_address or get_best_pool_for_token(mint_address)
    if not pool_address:
        return None
    entry_price = get_price_near_time(mint_address, entry_unix_time, pool_address)
    if entry_price is None or entry_price == 0:
        return None
    exit_price = get_price_near_time(mint_address, entry_unix_time + horizon_seconds, pool_address)
    if exit_price is None:
        return None
    return round(((exit_price - entry_price) / entry_price) * 100, 2)
