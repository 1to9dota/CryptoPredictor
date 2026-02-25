"""OKX 公开 K线 API 获取（无需 API Key）"""

import aiohttp

# OKX 公开 API（无需认证）
OKX_API_URL = "https://www.okx.com/api/v5/market"

# 币种映射：内部名 → OKX instId
COIN_MAP = {
    "BTCUSDT": "BTC-USDT",
    "ETHUSDT": "ETH-USDT",
}

# 周期映射：内部名 → OKX bar 参数
BAR_MAP = {
    "1h": "1H",
    "4h": "4H",
}


async def fetch_klines(symbol: str, interval: str, limit: int = 100) -> list[dict]:
    """从 OKX 获取 K线数据

    Args:
        symbol: 交易对，如 "BTCUSDT"
        interval: K线周期，如 "1h", "4h"
        limit: K线数量（最多 300）

    Returns:
        按时间升序排列的 K线列表
    """
    inst_id = COIN_MAP.get(symbol, symbol)
    bar = BAR_MAP.get(interval, interval)

    url = f"{OKX_API_URL}/candles"
    params = {"instId": inst_id, "bar": bar, "limit": str(min(limit, 300))}

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"OKX API 错误 {resp.status}: {text}")
            result = await resp.json()

    if result.get("code") != "0":
        raise RuntimeError(f"OKX API 错误: {result.get('msg', '未知')}")

    # OKX K线格式：[ts, open, high, low, close, vol, volCcy, volCcyQuote, confirm]
    candles = []
    for k in result.get("data", []):
        candles.append({
            "ts": int(k[0]),
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
        })

    # OKX 返回按时间倒序，反转为升序
    candles.reverse()
    return candles


async def get_current_price(symbol: str) -> float:
    """获取最新价格"""
    inst_id = COIN_MAP.get(symbol, symbol)
    url = f"{OKX_API_URL}/ticker"

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params={"instId": inst_id}) as resp:
            if resp.status != 200:
                raise RuntimeError(f"OKX 价格 API 错误: {resp.status}")
            result = await resp.json()

    if result.get("code") != "0" or not result.get("data"):
        raise RuntimeError(f"OKX 价格 API 错误: {result.get('msg', '未知')}")

    return float(result["data"][0]["last"])
