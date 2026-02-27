"""价格告警 — 突破支撑/阻力、均线等关键价位时即时推送"""

import logging
from datetime import datetime, timezone, timedelta
from predictor.data.fetcher import fetch_klines
from predictor.data.indicators import calc_all

logger = logging.getLogger(__name__)

# 已触发告警的记录 {(coin, alert_type, level): datetime}
# 同一告警 4 小时内不重复推送
_alert_history: dict[tuple, datetime] = {}
_COOLDOWN = timedelta(hours=4)


def _should_alert(coin: str, alert_type: str, level: float) -> bool:
    """检查告警是否在冷却期内"""
    key = (coin, alert_type, round(level, 2))
    now = datetime.now(timezone.utc)
    last = _alert_history.get(key)
    if last and (now - last) < _COOLDOWN:
        return False
    _alert_history[key] = now
    return True


def _cleanup_history():
    """清理过期的告警历史"""
    now = datetime.now(timezone.utc)
    expired = [k for k, v in _alert_history.items() if (now - v) > _COOLDOWN * 2]
    for k in expired:
        del _alert_history[k]


async def check_price_alerts(coin: str) -> list[dict]:
    """检查一个币种的价格告警，返回触发的告警列表"""
    alerts = []

    try:
        # 取 1H K线计算指标
        klines = await fetch_klines(coin, "1h", limit=50)
        if len(klines) < 30:
            return []

        closes = [k["close"] for k in klines]
        volumes = [k["volume"] for k in klines]
        ind = calc_all(closes, volumes)

        price = ind["price"]
        coin_name = "BTC" if "BTC" in coin else "ETH"

        # 1. 突破阻力位
        resistance = ind["resistance"]
        if price > resistance and _should_alert(coin, "break_resistance", resistance):
            alerts.append({
                "coin": coin_name,
                "type": "突破阻力位",
                "emoji": "\U0001f680",
                "detail": f"当前 ${price:,.2f} 突破 14 周期高点 ${resistance:,.2f}",
                "signal": "看涨",
            })

        # 2. 跌破支撑位
        support = ind["support"]
        if price < support and _should_alert(coin, "break_support", support):
            alerts.append({
                "coin": coin_name,
                "type": "跌破支撑位",
                "emoji": "\U0001f4a5",
                "detail": f"当前 ${price:,.2f} 跌破 14 周期低点 ${support:,.2f}",
                "signal": "看跌",
            })

        # 3. 布林带突破（超买/超卖）
        if ind["bb_percent_b"] > 100 and _should_alert(coin, "bb_upper", ind["bb_upper"]):
            alerts.append({
                "coin": coin_name,
                "type": "突破布林带上轨",
                "emoji": "\U0001f525",
                "detail": f"BB %B = {ind['bb_percent_b']:.1f}%，超买警告",
                "signal": "注意回调风险",
            })
        elif ind["bb_percent_b"] < 0 and _should_alert(coin, "bb_lower", ind["bb_lower"]):
            alerts.append({
                "coin": coin_name,
                "type": "跌破布林带下轨",
                "emoji": "\u2744\ufe0f",
                "detail": f"BB %B = {ind['bb_percent_b']:.1f}%，超卖警告",
                "signal": "注意反弹机会",
            })

        # 4. MACD 金叉/死叉
        if ind["macd_golden_cross"] and _should_alert(coin, "golden_cross", 0):
            alerts.append({
                "coin": coin_name,
                "type": "MACD 金叉",
                "emoji": "\u2728",
                "detail": f"MACD 线上穿信号线，柱状 {ind['macd_histogram']:+.4f}",
                "signal": "看涨信号",
            })
        elif ind["macd_death_cross"] and _should_alert(coin, "death_cross", 0):
            alerts.append({
                "coin": coin_name,
                "type": "MACD 死叉",
                "emoji": "\U0001f480",
                "detail": f"MACD 线下穿信号线，柱状 {ind['macd_histogram']:+.4f}",
                "signal": "看跌信号",
            })

        # 5. RSI 极端值
        if ind["rsi"] > 80 and _should_alert(coin, "rsi_overbought", 80):
            alerts.append({
                "coin": coin_name,
                "type": "RSI 超买",
                "emoji": "\U0001f6a8",
                "detail": f"RSI = {ind['rsi']:.1f}，严重超买",
                "signal": "注意回调风险",
            })
        elif ind["rsi"] < 20 and _should_alert(coin, "rsi_oversold", 20):
            alerts.append({
                "coin": coin_name,
                "type": "RSI 超卖",
                "emoji": "\U0001f6a8",
                "detail": f"RSI = {ind['rsi']:.1f}，严重超卖",
                "signal": "注意反弹机会",
            })

        # 6. 成交量异常（量比 > 3）
        if ind["volume_ratio"] > 3 and _should_alert(coin, "volume_spike", 0):
            alerts.append({
                "coin": coin_name,
                "type": "成交量异常放大",
                "emoji": "\U0001f4ca",
                "detail": f"量比 = {ind['volume_ratio']:.1f}x（正常 7 周期均量的 {ind['volume_ratio']:.1f} 倍）",
                "signal": "关注后续方向",
            })

    except Exception as e:
        logger.error(f"价格告警检查失败 {coin}: {e}", exc_info=True)

    _cleanup_history()
    return alerts
