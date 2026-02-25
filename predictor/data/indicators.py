"""独立技术指标库（复用 TradeGotchi）"""


def calc_ema(data: list[float], period: int) -> list[float]:
    """指数移动平均线（EMA）"""
    if not data:
        return []
    ema = [data[0]]
    multiplier = 2 / (period + 1)
    for price in data[1:]:
        ema.append(price * multiplier + ema[-1] * (1 - multiplier))
    return ema


def calc_sma(data: list[float], period: int) -> float:
    """简单移动平均线（SMA），返回最近一个周期的值"""
    if len(data) < period:
        return 0.0
    return sum(data[-period:]) / period


def calc_rsi(closes: list[float], period: int = 14) -> float:
    """相对强弱指数（RSI）"""
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(0, diff))
        losses.append(max(0, -diff))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))


def calc_macd(closes: list[float]) -> dict:
    """MACD 指标（12, 26, 9）"""
    if len(closes) < 26:
        return {"line": 0, "signal": 0, "histogram": 0,
                "golden_cross": False, "death_cross": False}
    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)
    macd_line_series = [e12 - e26 for e12, e26 in zip(ema12, ema26)]
    signal_series = calc_ema(macd_line_series, 9)
    macd_line = macd_line_series[-1]
    signal_line = signal_series[-1]
    histogram = macd_line - signal_line

    golden_cross = False
    death_cross = False
    if len(macd_line_series) >= 2 and len(signal_series) >= 2:
        prev_hist = macd_line_series[-2] - signal_series[-2]
        if prev_hist <= 0 and histogram > 0:
            golden_cross = True
        elif prev_hist >= 0 and histogram < 0:
            death_cross = True

    return {
        "line": macd_line, "signal": signal_line, "histogram": histogram,
        "golden_cross": golden_cross, "death_cross": death_cross,
    }


def calc_bollinger(closes: list[float], period: int = 20) -> dict:
    """布林带（默认 20 周期，2 倍标准差）"""
    if len(closes) < period:
        return {"upper": 0, "middle": 0, "lower": 0, "bandwidth": 0, "percent_b": 50}
    sma = sum(closes[-period:]) / period
    std = (sum((c - sma) ** 2 for c in closes[-period:]) / period) ** 0.5
    upper = sma + 2 * std
    lower = sma - 2 * std
    bandwidth = (upper - lower) / sma * 100 if sma else 0
    percent_b = (closes[-1] - lower) / (upper - lower) * 100 if (upper - lower) else 50
    return {
        "upper": upper, "middle": sma, "lower": lower,
        "bandwidth": bandwidth, "percent_b": percent_b,
    }


def calc_ma_alignment(closes: list[float]) -> bool:
    """均线多头排列：MA7 > MA14 > MA30"""
    if len(closes) < 30:
        return False
    ma7 = sum(closes[-7:]) / 7
    ma14 = sum(closes[-14:]) / 14
    ma30 = sum(closes[-30:]) / 30
    return ma7 > ma14 > ma30


def calc_volume_ratio(volumes: list[float], lookback: int = 7) -> float:
    """量比 = 最新成交量 / 近 N 期平均成交量"""
    if not volumes or len(volumes) < lookback:
        return 1.0
    avg_vol = sum(volumes[-lookback:]) / lookback
    if avg_vol == 0:
        return 1.0
    return volumes[-1] / avg_vol


def calc_support_resistance(closes: list[float], lookback: int = 14) -> dict:
    """支撑/阻力位（近 N 周期最低/最高）"""
    lookback = min(lookback, len(closes))
    if lookback < 2:
        return {"support": 0, "resistance": 0}
    recent = closes[-lookback:]
    return {"support": min(recent), "resistance": max(recent)}


def calc_all(closes: list[float], volumes: list[float]) -> dict:
    """一次性计算所有指标，返回完整快照"""
    rsi = calc_rsi(closes)
    macd = calc_macd(closes)
    bollinger = calc_bollinger(closes)
    ma_alignment = calc_ma_alignment(closes)
    volume_ratio = calc_volume_ratio(volumes)
    support_resistance = calc_support_resistance(closes)
    ma7 = calc_sma(closes, 7)
    ma14 = calc_sma(closes, 14)
    ma30 = calc_sma(closes, 30)

    return {
        "price": closes[-1] if closes else 0,
        "rsi": round(rsi, 2),
        "macd_line": round(macd["line"], 4),
        "macd_signal": round(macd["signal"], 4),
        "macd_histogram": round(macd["histogram"], 4),
        "macd_golden_cross": macd["golden_cross"],
        "macd_death_cross": macd["death_cross"],
        "bb_upper": round(bollinger["upper"], 2),
        "bb_middle": round(bollinger["middle"], 2),
        "bb_lower": round(bollinger["lower"], 2),
        "bb_bandwidth": round(bollinger["bandwidth"], 2),
        "bb_percent_b": round(bollinger["percent_b"], 2),
        "ma7": round(ma7, 2),
        "ma14": round(ma14, 2),
        "ma30": round(ma30, 2),
        "ma_alignment": ma_alignment,
        "volume_ratio": round(volume_ratio, 2),
        "support": round(support_resistance["support"], 2),
        "resistance": round(support_resistance["resistance"], 2),
    }
