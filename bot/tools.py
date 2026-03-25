import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

API_BASE = "https://api.tonscan.com/api/bt"
API_HEADERS = {}

TETHER_JETTON_MASTER = "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs"
PROXYTON_JETTON_MASTER = "EQBnGWMCf3-FZZq1W4IWcWiGAc3PHuZ0_H-7sad2oY00o83S"

DEX_NAMES = {
    "stonfi_pool": "STON.fi v1",
    "stonfi_pool_v2": "STON.fi v2",
    "dedust_pool": "DeDust",
    "tonco_pool": "TonCo",
    "coffee_pool": "Coffee",
}


def calc(
    price: float, n: float, dir: str, asset0_decimals: int, asset1_decimals: int
) -> float:
    if dir == "left":
        return (10**asset1_decimals * n * 10_000_000) / price
    else:
        return (10**asset0_decimals * n * price) / 10_000_000


def calc_jetton_price_in_usd(pool, balance, ton_price, master_addr, is_official=False):
    if balance is None or ton_price is None or master_addr is None:
        return None

    # if not is_official:
    #     return None

    try:
        balance = int(balance)
    except Exception:
        return None

    # tether stablecoin
    if master_addr == TETHER_JETTON_MASTER:
        return balance / 10**6

    # pTON
    if master_addr == PROXYTON_JETTON_MASTER:
        return (balance / 10**9) * ton_price

    if pool is None or not pool.get("price"):
        return None

    asset0_decimals = pool.get("asset0_decimals") or pool.get("token0_decimals") or 9
    asset1_decimals = pool.get("asset1_decimals") or pool.get("token1_decimals") or 9

    try:
        if pool["direction"] == "left":
            result = calc(
                pool["price"], balance, "left", asset0_decimals, asset1_decimals
            )
            result = result / (10**asset1_decimals)
        else:
            result = calc(
                pool["price"], balance, "right", asset0_decimals, asset1_decimals
            )
            result = result / (10**asset0_decimals)
    except Exception as e:
        logger.error(f"Calculation failed: {e}")
        return None

    if pool["direction"] == "left":
        result = result / (10**asset0_decimals)
    else:
        result = result / (10**asset1_decimals)

    if pool["pool_type"] == "pton":
        return result * ton_price

    return result


async def get_ton_price_usd() -> float:
    try:
        async with httpx.AsyncClient(timeout=5, headers=API_HEADERS) as client:
            resp = await client.get(f"{API_BASE}/getMarketInfo")
            return float(resp.json()["json"]["data"][0]["quote"]["2781"]["price"])
    except Exception:
        return 1.0  # fallback


async def search_token(query: str) -> Optional[dict]:
    """Find a jetton by name or ticker from the top 150 ranked tokens."""
    all_jettons = []
    async with httpx.AsyncClient(timeout=10, headers=API_HEADERS) as client:
        for offset in [0, 50, 100]:
            resp = await client.get(
                f"{API_BASE}/listJettons", params={"limit": 50, "offset": offset}
            )
            batch = resp.json().get("json", {}).get("data", {}).get("jettons", [])
            all_jettons.extend(batch)

    q = query.lower().strip()
    for j in all_jettons:
        c = j.get("content") or {}
        symbol = (c.get("symbol") or "").lower()
        name = (c.get("name") or "").lower()
        if q == symbol or q in name:
            return {
                "address": j["address"],
                "symbol": c.get("symbol"),
                "name": c.get("name"),
                "price_usd": j.get("price"),
                "volume_7d_usd": j.get("volume"),
            }
    return None


async def get_dex_prices(jetton_master: str) -> list[dict]:
    """Get per-DEX prices for a jetton master address."""
    async with httpx.AsyncClient(timeout=10, headers=API_HEADERS) as client:
        resp = await client.get(
            f"{API_BASE}/getTradingPoolsForAddress",
            params={"address": jetton_master},
        )
        pools = resp.json().get("json", {}).get("data", {}).get("pools", [])

    if not pools:
        return []

    ton_price = await get_ton_price_usd()

    results = []
    for pool in pools:
        # only USD-anchored pools give meaningful price comparisons
        if pool.get("pool_type") not in ("tether", "pton"):
            continue
        if not pool.get("asset0_symbol") or not pool.get("asset1_symbol"):
            continue

        direction = pool.get("direction")
        a0_dec = int(pool.get("asset0_decimals") or 9)
        a1_dec = int(pool.get("asset1_decimals") or 9)
        balance = 10 ** (a1_dec if direction == "left" else a0_dec)
        usd = calc_jetton_price_in_usd(pool, balance, ton_price, jetton_master)
        if not usd:
            continue

        results.append(
            {
                "dex": DEX_NAMES.get(pool.get("dex"), pool.get("dex")),
                "pair": f"{pool.get('asset0_symbol')}/{pool.get('asset1_symbol')}",
                "price_usd": round(usd, 8),
                "pool_address": pool.get("pool"),
            }
        )

    results.sort(key=lambda x: x["price_usd"], reverse=True)
    return results


async def get_address_full(address: str) -> dict:
    """Get complete address data: balance/flags (getAddressInformation), contract state/interfaces (getAddressState), and jetton holdings (getJettonsForAddress) — all in parallel."""
    import asyncio

    async def _info():
        async with httpx.AsyncClient(timeout=10, headers=API_HEADERS) as client:
            resp = await client.get(
                f"{API_BASE}/getAddressInformation", params={"address": address}
            )
            return resp.json().get("json", {}).get("data", {}).get("detail", {})

    async def _state():
        async with httpx.AsyncClient(timeout=10, headers=API_HEADERS) as client:
            resp = await client.get(
                f"{API_BASE}/getAddressState", params={"address": address}
            )
            return resp.json().get("json", {}).get("data", {}).get("detail", {})

    async def _jettons():
        async with httpx.AsyncClient(timeout=10, headers=API_HEADERS) as client:
            resp = await client.get(
                f"{API_BASE}/getJettonsForAddress", params={"address": address}
            )
            data = resp.json().get("json", {}).get("data", {})
            return {
                "jettons": data.get("jetton_wallets", []),
                "total_balance": data.get("total_balance", 0),
            }

    info, state, jettons_data = await asyncio.gather(_info(), _state(), _jettons())
    return {
        "info": info,
        "state": state,
        "jettons": jettons_data["jettons"],
        "total_balance_usd": jettons_data["total_balance"],
    }


async def get_whale_profile(address: str) -> dict:
    """Get a full profile for a whale address: portfolio (jettons held) + related addresses (who they transact with)."""
    import asyncio

    async def _portfolio():
        async with httpx.AsyncClient(timeout=10, headers=API_HEADERS) as client:
            resp = await client.get(
                f"{API_BASE}/getJettonsForAddress", params={"address": address}
            )
            return resp.json().get("json", {}).get("data", {}).get("jettons", [])

    async def _related():
        async with httpx.AsyncClient(timeout=10, headers=API_HEADERS) as client:
            resp = await client.get(
                f"{API_BASE}/getRelatedAddresses", params={"address": address}
            )
            return (
                resp.json().get("json", {}).get("data", {}).get("related_addresses", [])
            )

    portfolio, related = await asyncio.gather(_portfolio(), _related())
    return {"address": address, "portfolio": portfolio, "related_addresses": related}


async def get_address_information(address: str) -> dict:
    """Get balance, friendly name, and account flags (validator, nominator, staking, official, scam) for a TON address."""
    async with httpx.AsyncClient(timeout=10, headers=API_HEADERS) as client:
        resp = await client.get(
            f"{API_BASE}/getAddressInformation", params={"address": address}
        )
        return resp.json().get("json", {}).get("data", {}).get("detail", {})


async def get_address_state(address: str) -> dict:
    """Get the contract state, wallet type, and interfaces for a TON address."""
    async with httpx.AsyncClient(timeout=10, headers=API_HEADERS) as client:
        resp = await client.get(
            f"{API_BASE}/getAddressState", params={"address": address}
        )
        return resp.json().get("json", {}).get("data", {}).get("detail", {})


async def get_token_holders(jetton_master: str, limit: int = 20) -> list[dict]:
    """Get the top holders of a specific jetton, ordered by balance descending."""
    async with httpx.AsyncClient(timeout=10, headers=API_HEADERS) as client:
        resp = await client.get(
            f"{API_BASE}/getJettonsForMaster",
            params={"address": jetton_master, "limit": min(limit, 50)},
        )
        return resp.json().get("json", {}).get("data", {}).get("jetton_wallets", [])


async def get_jetton_flows(jetton_master: str) -> list[dict]:
    """Get raw buy/sell flow snapshot for a specific jetton — who is sending/receiving and how much."""
    async with httpx.AsyncClient(timeout=10, headers=API_HEADERS) as client:
        resp = await client.get(
            f"{API_BASE}/getJettonFlows", params={"jetton_master": jetton_master}
        )
        return resp.json().get("json", {}).get("data", [])


async def get_jetton_volumes(jetton_address: str, period: str = "1w") -> list[dict]:
    """Get daily trading volume history for a jetton. period: '1w', '1m', or '1y'."""
    async with httpx.AsyncClient(timeout=10, headers=API_HEADERS) as client:
        resp = await client.get(
            f"{API_BASE}/getJettonVolumes",
            params={"jetton_address": jetton_address, "period": period},
        )
        return resp.json().get("json", {}).get("data", [])


async def get_trading_pools(address: str) -> list[dict]:
    """Get all DEX pools for a jetton master address with liquidity, price, and pool type details."""
    async with httpx.AsyncClient(timeout=10, headers=API_HEADERS) as client:
        resp = await client.get(
            f"{API_BASE}/getTradingPoolsForAddress", params={"address": address}
        )
        return resp.json().get("json", {}).get("data", {}).get("pools", [])


async def get_stonfi_trades(pool_address: str, period: str = "1w") -> list[dict]:
    """Get OHLCV candle data for a STON.fi pool. period: '1w', '1m', or '1y'."""
    async with httpx.AsyncClient(timeout=10, headers=API_HEADERS) as client:
        resp = await client.get(
            f"{API_BASE}/getStonfiTradesVolumes",
            params={"pool_address": pool_address, "period": period},
        )
        return resp.json().get("json", {}).get("data", [])


async def get_market_info() -> list[dict]:
    """Get TON historical price, volume, and market cap data (96 data points)."""
    async with httpx.AsyncClient(timeout=10, headers=API_HEADERS) as client:
        resp = await client.get(f"{API_BASE}/getMarketInfo")
        return resp.json().get("json", {}).get("data", [])


async def get_misc_info() -> dict:
    """Get TON network stats: tx volume/count, active addresses, new accounts, election stake, market cap."""
    async with httpx.AsyncClient(timeout=10, headers=API_HEADERS) as client:
        resp = await client.get(f"{API_BASE}/getMiscInfo")
        return resp.json().get("json", {}).get("data", {})


async def get_network_overview(threshold: float = 2.0) -> dict:
    """Combined network snapshot: misc stats + 24h price + top whales + whale anomalies + recent unstake events."""
    import asyncio

    misc, market, top_whales, anomalies, unstakes, large_txns = await asyncio.gather(
        get_misc_info(),
        get_market_info(),
        get_top_whales(limit=10),
        get_whale_anomalies(threshold=threshold),
        get_unstake_events(hours=24),
        get_transactions_large(),
    )
    return {
        "stats": misc,
        "price_24h": market,
        "top_whales": top_whales,
        "whale_anomalies": anomalies,
        "unstake_events": unstakes,
        "large_transactions": large_txns,
    }


async def get_top_whales(limit: int = 10) -> list[dict]:
    """Get the top TON whale accounts by transaction volume."""
    async with httpx.AsyncClient(timeout=10, headers=API_HEADERS) as client:
        resp = await client.get(f"{API_BASE}/getWhaleAccounts")
        accounts = resp.json().get("json", {}).get("data", [])
    return accounts[:limit]


async def get_accounts_top(limit: int = 20) -> list[dict]:
    """Get the top N TON accounts by balance — the richest wallets on the network."""
    async with httpx.AsyncClient(timeout=10, headers=API_HEADERS) as client:
        resp = await client.get(
            f"{API_BASE}/getAccountsTop", params={"limit": min(limit, 100)}
        )
        return resp.json().get("json", {}).get("data", {}).get("list", [])


async def get_transactions_large() -> list[dict]:
    """Get the most recent large transactions on TON."""
    async with httpx.AsyncClient(timeout=10, headers=API_HEADERS) as client:
        resp = await client.get(f"{API_BASE}/getTransactionsLarge")
        return resp.json().get("json", {}).get("data", {}).get("list", [])


async def get_whale_trends(days: int = 7) -> list[dict]:
    """Get top whale accounts with daily volume breakdown over the last N days."""
    async with httpx.AsyncClient(timeout=10, headers=API_HEADERS) as client:
        resp = await client.get(f"{API_BASE}/getWhaleTrends", params={"days": days})
        return resp.json().get("json", {}).get("data", [])


async def get_whale_anomalies(threshold: float = 2.0) -> list[dict]:
    """Get TON whale accounts with unusual activity (z-score >= threshold vs 24h baseline)."""
    async with httpx.AsyncClient(timeout=10, headers=API_HEADERS) as client:
        resp = await client.get(
            f"{API_BASE}/getWhaleAnomalies",
            params={"threshold": threshold},
        )
        return resp.json().get("json", {}).get("data", [])


async def get_jetton_anomalies(
    jetton_master: str, threshold: float = 2.0
) -> list[dict]:
    """Get accounts with unusual flow activity for a specific jetton."""
    async with httpx.AsyncClient(timeout=10, headers=API_HEADERS) as client:
        resp = await client.get(
            f"{API_BASE}/getJettonAnomalies",
            params={"jetton_master": jetton_master, "threshold": threshold},
        )
        return resp.json().get("json", {}).get("data", [])


async def get_unstake_events(
    hours: int = 24, event_type: Optional[str] = None
) -> list[dict]:
    """Get recent large unstaking events. event_type: 'elector' or 'liquid_staking'."""
    params: dict = {"hours": hours}
    if event_type:
        params["event_type"] = event_type
    async with httpx.AsyncClient(timeout=10, headers=API_HEADERS) as client:
        resp = await client.get(f"{API_BASE}/getUnstakeEvents", params=params)
        return resp.json().get("json", {}).get("data", [])


async def get_usdt_pool_liquidity() -> list[dict]:
    """Get USDT pool liquidity across all DEXes with delta vs previous snapshot and z-score baseline."""
    async with httpx.AsyncClient(timeout=10, headers=API_HEADERS) as client:
        resp = await client.get(f"{API_BASE}/getUsdtPoolLiquidity")
        return resp.json().get("json", {}).get("data", [])


async def get_jetton_pool_liquidity(jetton_master: str) -> list[dict]:
    """Get pool liquidity snapshots for a specific jetton (pTON and USDT pairs) with delta and z-score anomaly detection."""
    async with httpx.AsyncClient(timeout=10, headers=API_HEADERS) as client:
        resp = await client.get(
            f"{API_BASE}/getJettonPoolLiquidity",
            params={"jetton_master": jetton_master},
        )
        return resp.json().get("json", {}).get("data", [])


async def get_historical_day(date: str) -> dict:
    """Get on-chain activity summary for a specific historical date (YYYY-MM-DD)."""
    async with httpx.AsyncClient(timeout=15, headers=API_HEADERS) as client:
        resp = await client.get(f"{API_BASE}/getHistoricalDay", params={"date": date})
        return resp.json().get("json", {}).get("data", {})


async def get_staking_apy() -> dict:
    """Get the current TON validator staking APY, calculated from recent election reward/stake data."""
    async with httpx.AsyncClient(timeout=10, headers=API_HEADERS) as client:
        resp = await client.get(f"{API_BASE}/apy")
        return resp.json().get("json", {}).get("data", {})


LOCKER_ADDRESS = "EQDtFpEwcFAEcRe5mLVh2N6C0x-_hJEM7W61_JLnSF74p4q2"


def _compute_vesting_schedule(nft: dict) -> dict:
    import math
    import time

    locker_data = (nft.get("locker") or nft.get("wallet_vesting") or {}).get("data", {})
    if not locker_data:
        return {}

    vesting_start = locker_data.get("vesting_start_time", 0)
    total_duration = locker_data.get("vesting_total_duration", 0)
    unlock_period = locker_data.get("unlock_period", 0)
    total_reward = locker_data.get("total_reward", 0)
    total_amount = locker_data.get("vesting_total_amount") or locker_data.get(
        "total_coins_locked", 0
    )

    if not unlock_period or not total_duration:
        return {}

    periods = math.floor(total_duration / unlock_period)
    amount_per_period = (total_amount + total_reward) / periods if periods else 0

    now = time.time()
    elapsed_periods = math.ceil((now - vesting_start) / unlock_period)
    next_release_ts = vesting_start + elapsed_periods * unlock_period
    final_release_ts = vesting_start + unlock_period * periods
    periods_elapsed = max(0, math.floor((now - vesting_start) / unlock_period))
    released_so_far = min(
        periods_elapsed * amount_per_period, total_amount + total_reward
    )

    return {
        "vesting_start_time": vesting_start,
        "total_periods": periods,
        "unlock_period_secs": unlock_period,
        "total_amount_nanoton": total_amount,
        "total_reward_nanoton": total_reward,
        "amount_per_period_nanoton": amount_per_period,
        "released_so_far_nanoton": released_so_far,
        "next_release_timestamp": next_release_ts,
        "final_release_timestamp": final_release_ts,
        "periods_elapsed": periods_elapsed,
    }


async def get_locker_vesting() -> dict:
    """Get the Believers Fund (The Locker) vesting schedule combined with contract metadata."""
    import asyncio

    async def _vested():
        async with httpx.AsyncClient(timeout=10, headers=API_HEADERS) as client:
            resp = await client.get(
                f"{API_BASE}/getVestedParticipants", params={"address": LOCKER_ADDRESS}
            )
            return resp.json().get("json", {}).get("data", {})

    async def _nft():
        async with httpx.AsyncClient(timeout=10, headers=API_HEADERS) as client:
            resp = await client.get(
                f"{API_BASE}/getNftData", params={"address": LOCKER_ADDRESS}
            )
            return resp.json().get("json", {}).get("data", {})

    vested, nft = await asyncio.gather(_vested(), _nft())
    schedule = _compute_vesting_schedule(nft)
    return {**vested, "schedule": schedule}
