"""AI 预测引擎 — 调用 GPT-4o-mini 预测涨跌"""

import asyncio
import json
import logging
from openai import AsyncOpenAI
from predictor.config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
from predictor.data.fetcher import fetch_klines
from predictor.data.indicators import calc_all
from predictor.data.market_data import fetch_market_data
from predictor.storage.database import (
    save_prediction, get_latest_rules, get_recent_predictions
)

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
    return _client


def _build_market_section(market: dict) -> str:
    """构建市场情绪数据段落"""
    if not market:
        return ""

    lines = ["\n## 市场情绪数据"]

    if "funding_rate" in market:
        fr = market["funding_rate"]
        rate = fr["funding_rate"]
        signal = "多头拥挤" if rate > 0.0005 else "空头拥挤" if rate < -0.0005 else "中性"
        lines.append(f"- 资金费率: {rate:.6f} ({signal})")

    if "fear_greed" in market:
        fg = market["fear_greed"]
        lines.append(f"- 恐惧贪婪指数: {fg['value']}/100 ({fg['classification']})")
        lines.append("  提示: <25极度恐惧(可能反弹), >75极度贪婪(可能回调)")

    if "long_short_ratio" in market:
        ls = market["long_short_ratio"]
        lines.append(f"- 多空持仓人数比: 多{ls['long_ratio']:.2%} / 空{ls['short_ratio']:.2%}")
        lines.append("  提示: 散户过度看多常为反向信号")

    if "open_interest" in market:
        oi = market["open_interest"]
        lines.append(f"- 合约持仓量: {oi['open_interest']:.2f}, 交易量: {oi['volume']:.2f}")
        lines.append("  提示: 持仓量激增+价格不动=大户布局")

    if "hashrate" in market:
        hr = market["hashrate"]
        trend = ""
        if hr.get("change_7d_pct") is not None:
            trend = f", 7日变化: {hr['change_7d_pct']:+.2f}%"
        lines.append(f"- BTC算力: {hr['hashrate_ehs']} EH/s{trend}")
        lines.append("  提示: 算力持续上升=矿工看好后市，算力骤降=矿工投降可能见底")

    return "\n".join(lines) if len(lines) > 1 else ""


def _build_prompt(coin: str, timeframe: str, indicators: dict,
                  recent_klines: list[dict], rules: list[str],
                  recent_perf: list[dict], market: dict | None = None) -> str:
    """构建预测 prompt"""
    # 最近 10 根 K线的 OHLCV
    kline_summary = []
    for k in recent_klines[-10:]:
        change = (k["close"] - k["open"]) / k["open"] * 100
        kline_summary.append(
            f"  O:{k['open']:.2f} H:{k['high']:.2f} L:{k['low']:.2f} "
            f"C:{k['close']:.2f} V:{k['volume']:.0f} ({change:+.2f}%)"
        )

    # 最近预测表现
    perf_lines = []
    for p in recent_perf[:10]:
        if p.get("validated_at"):
            mark = "correct" if p["is_correct"] else "wrong"
            perf_lines.append(
                f"  {p['coin']} {p['timeframe']}: predicted {p['direction']}, "
                f"actual {p.get('actual_direction', '?')} → {mark}"
            )

    # 规则
    rules_text = "\n".join(f"  - {r}" for r in rules) if rules else "  (暂无历史规则，首次运行)"

    # 市场情绪数据
    market_section = _build_market_section(market or {})

    tf_label = "1小时" if timeframe == "1h" else "4小时"
    coin_name = "BTC" if "BTC" in coin else "ETH"

    return f"""你是一个加密货币价格预测分析师。根据以下技术指标和市场情绪数据，预测 {coin_name} 在未来 {tf_label} 的涨跌方向。

## 当前技术指标
{json.dumps(indicators, indent=2, ensure_ascii=False)}
{market_section}

## 最近价格走势（{timeframe} K线，从旧到新）
{chr(10).join(kline_summary)}

## 历史学习规则
{rules_text}

## 最近预测表现
{chr(10).join(perf_lines) if perf_lines else "  (暂无历史表现)"}

请综合技术指标和市场情绪数据进行判断。输出：
1. 预测方向：涨 或 跌
2. 置信度：1-5（5最高）
3. 关键依据：简要说明判断理由（50字内）

严格按 JSON 格式输出，不要其他内容：
{{"direction": "up 或 down", "confidence": 1-5, "reasoning": "..."}}"""


async def predict(coin: str, timeframe: str) -> dict | None:
    """执行一次预测

    Returns:
        {"id": int, "coin": str, "timeframe": str, "direction": str,
         "confidence": int, "reasoning": str, "price": float, "indicators": dict}
        或 None（失败时）
    """
    try:
        # 1. 获取 K线数据
        klines = await fetch_klines(coin, timeframe, limit=100)
        if len(klines) < 30:
            logger.warning(f"K线数据不足: {coin} {timeframe}, 只有 {len(klines)} 根")
            return None

        closes = [k["close"] for k in klines]
        volumes = [k["volume"] for k in klines]

        # 2. 计算技术指标
        indicators = calc_all(closes, volumes)

        # 3. 并行获取历史规则、近期表现、市场情绪数据
        rules, recent, market = await asyncio.gather(
            get_latest_rules(),
            get_recent_predictions(limit=20),
            fetch_market_data(coin, timeframe),
        )

        # 市场数据合并到 indicators 快照中（便于存库回溯）
        if market:
            indicators["market_sentiment"] = market

        # 4. 构建 prompt 并调用 LLM
        prompt = _build_prompt(coin, timeframe, indicators, klines, rules, recent, market)
        client = _get_client()
        response = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=200,
        )

        content = response.choices[0].message.content.strip()
        # 清理可能的 markdown 代码块
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        result = json.loads(content)
        direction = result["direction"].lower()
        confidence = int(result["confidence"])
        reasoning = result.get("reasoning", "")

        # 5. 保存到数据库
        pred_id = await save_prediction(
            coin=coin, timeframe=timeframe, direction=direction,
            confidence=confidence, reasoning=reasoning,
            price=closes[-1], indicators=indicators,
        )

        logger.info(f"预测完成: {coin} {timeframe} → {direction} (置信度 {confidence})")
        return {
            "id": pred_id, "coin": coin, "timeframe": timeframe,
            "direction": direction, "confidence": confidence,
            "reasoning": reasoning, "price": closes[-1],
            "indicators": indicators,
        }

    except Exception as e:
        logger.error(f"预测失败 {coin} {timeframe}: {e}", exc_info=True)
        return None
