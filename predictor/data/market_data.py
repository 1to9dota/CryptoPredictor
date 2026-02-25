"""市场情绪数据源 — 资金费率、恐惧贪婪指数、多空比、大户持仓"""

import asyncio
import logging
import aiohttp

logger = logging.getLogger(__name__)

# OKX 公开 API
OKX_PUBLIC = "https://www.okx.com/api/v5/public"
OKX_RUBIK = "https://www.okx.com/api/v5/rubik/stat/contracts"

# 币种映射（与 fetcher.py 一致）
COIN_MAP = {
    "BTCUSDT": "BTC-USDT",
    "ETHUSDT": "ETH-USDT",
}

# 周期映射（多空比用）
PERIOD_MAP = {
    "1h": "1H",
    "4h": "4H",
}


async def fetch_funding_rate(coin: str) -> dict | None:
    """获取当前资金费率（永续合约）

    正高 = 多头拥挤，负 = 空头拥挤
    """
    inst_id = COIN_MAP.get(coin, coin).replace("-USDT", "-USDT-SWAP")
    url = f"{OKX_PUBLIC}/funding-rate"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params={"instId": inst_id}) as resp:
                if resp.status != 200:
                    logger.warning(f"资金费率 API {resp.status}")
                    return None
                result = await resp.json()

        if result.get("code") != "0" or not result.get("data"):
            logger.warning(f"资金费率返回异常: {result.get('msg')}")
            return None

        data = result["data"][0]
        return {
            "funding_rate": float(data["fundingRate"]),
            "next_funding_time": data.get("nextFundingTime", ""),
        }
    except Exception as e:
        logger.warning(f"获取资金费率失败: {e}")
        return None


async def fetch_fear_greed() -> dict | None:
    """获取恐惧贪婪指数（alternative.me）

    0-25 极度恐惧, 26-46 恐惧, 47-54 中立, 55-75 贪婪, 76-100 极度贪婪
    """
    url = "https://api.alternative.me/fng/"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params={"limit": "1"}) as resp:
                if resp.status != 200:
                    logger.warning(f"恐惧贪婪指数 API {resp.status}")
                    return None
                result = await resp.json()

        data = result.get("data", [])
        if not data:
            return None

        return {
            "value": int(data[0]["value"]),
            "classification": data[0]["value_classification"],
        }
    except Exception as e:
        logger.warning(f"获取恐惧贪婪指数失败: {e}")
        return None


async def fetch_long_short_ratio(coin: str, timeframe: str) -> dict | None:
    """获取多空持仓人数比（OKX Rubik）

    反映散户情绪倾向
    """
    ccy = "BTC" if "BTC" in coin else "ETH"
    period = PERIOD_MAP.get(timeframe, "1H")
    url = f"{OKX_RUBIK}/long-short-account-ratio"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params={"ccy": ccy, "period": period}) as resp:
                if resp.status != 200:
                    logger.warning(f"多空比 API {resp.status}")
                    return None
                result = await resp.json()

        if result.get("code") != "0" or not result.get("data"):
            logger.warning(f"多空比返回异常: {result.get('msg')}")
            return None

        # data 是 [[ts, ratio], ...]，ratio = 多头人数/空头人数
        latest = result["data"][0]
        ratio = float(latest[1])
        long_pct = ratio / (1 + ratio)
        short_pct = 1 / (1 + ratio)
        return {
            "ratio": ratio,
            "long_ratio": long_pct,
            "short_ratio": short_pct,
        }
    except Exception as e:
        logger.warning(f"获取多空比失败: {e}")
        return None


async def fetch_open_interest(coin: str) -> dict | None:
    """获取合约持仓量和交易量（OKX Rubik）

    反映机构/大户动向
    """
    ccy = "BTC" if "BTC" in coin else "ETH"
    url = f"{OKX_RUBIK}/open-interest-volume"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params={"ccy": ccy, "period": "1H"}) as resp:
                if resp.status != 200:
                    logger.warning(f"持仓量 API {resp.status}")
                    return None
                result = await resp.json()

        if result.get("code") != "0" or not result.get("data"):
            logger.warning(f"持仓量返回异常: {result.get('msg')}")
            return None

        # data 是 [[ts, oi, vol], ...]，取最新一条
        latest = result["data"][0]
        return {
            "open_interest": float(latest[1]),
            "volume": float(latest[2]),
        }
    except Exception as e:
        logger.warning(f"获取持仓量失败: {e}")
        return None


async def fetch_market_data(coin: str, timeframe: str) -> dict:
    """并行获取所有市场情绪数据，任一失败不影响其他

    Returns:
        合并的 dict，失败的字段不包含
    """
    results = await asyncio.gather(
        fetch_funding_rate(coin),
        fetch_fear_greed(),
        fetch_long_short_ratio(coin, timeframe),
        fetch_open_interest(coin),
        return_exceptions=True,
    )

    market = {}
    labels = ["funding_rate", "fear_greed", "long_short_ratio", "open_interest"]

    for label, result in zip(labels, results):
        if isinstance(result, Exception):
            logger.warning(f"市场数据 {label} 异常: {result}")
        elif result is not None:
            market[label] = result

    return market
