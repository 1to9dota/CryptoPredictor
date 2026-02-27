"""Telegram Bot — 推送预测 + 交互命令"""

import logging
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes
from predictor.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, COINS, TIMEFRAMES
from predictor.storage.database import (
    get_accuracy_stats, get_recent_predictions, get_latest_rules,
    get_last_prediction, get_daily_stats,
)
from predictor.ai.predictor import predict
from predictor.tracker.validator import validate_predictions

logger = logging.getLogger(__name__)

_app: Application | None = None


def get_app() -> Application:
    """获取 Telegram Bot Application 单例"""
    global _app
    if _app is None:
        _app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        _app.add_handler(CommandHandler("start", cmd_start))
        _app.add_handler(CommandHandler("stats", cmd_stats))
        _app.add_handler(CommandHandler("history", cmd_history))
        _app.add_handler(CommandHandler("rules", cmd_rules))
        _app.add_handler(CommandHandler("predict", cmd_predict))
    return _app


async def _send_text(text: str):
    """发送消息到 Telegram"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text)
    except Exception as e:
        logger.error(f"Telegram 推送失败: {e}")


async def send_alert(msg: str):
    """发送告警消息到 Telegram（带 ⚠️ 前缀）"""
    await _send_text(f"\u26a0\ufe0f 系统告警\n\n{msg}")


async def send_price_alert(alert: dict):
    """推送价格告警"""
    text = (
        f"{alert['emoji']} {alert['coin']} 价格告警\n\n"
        f"类型：{alert['type']}\n"
        f"详情：{alert['detail']}\n"
        f"信号：{alert['signal']}"
    )
    await _send_text(text)


async def send_prediction(result: dict):
    """推送预测结果到 Telegram，附带上次预测的验证结果"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram 未配置，跳过推送")
        return

    coin_name = "BTC" if "BTC" in result["coin"] else "ETH"
    tf = result["timeframe"].upper()
    direction_emoji = "\U0001f7e2 涨" if result["direction"] == "up" else "\U0001f534 跌"
    stars = "\u2b50" * result["confidence"] + "\u2606" * (5 - result["confidence"])

    ind = result["indicators"]
    macd_arrow = "\u25b2" if ind.get("macd_histogram", 0) > 0 else "\u25bc"

    # 市场情绪摘要
    market = ind.get("market_sentiment", {})
    sentiment_lines = []
    if "funding_rate" in market:
        fr = market["funding_rate"]["funding_rate"]
        sentiment_lines.append(f"费率 {fr:+.4%}")
    if "fear_greed" in market:
        fg = market["fear_greed"]
        sentiment_lines.append(f"恐贪 {fg['value']}")
    if "long_short_ratio" in market:
        ls = market["long_short_ratio"]
        sentiment_lines.append(f"多空比 {ls['ratio']:.2f}")
    if "open_interest" in market:
        oi = market["open_interest"]["open_interest"]
        oi_b = oi / 1e9
        sentiment_lines.append(f"持仓 {oi_b:.1f}B")
    if "hashrate" in market:
        hr = market["hashrate"]
        hr_text = f"算力 {hr['hashrate_ehs']}EH"
        if hr.get("change_7d_pct") is not None:
            hr_text += f"({hr['change_7d_pct']:+.1f}%)"
        sentiment_lines.append(hr_text)
    sentiment_text = " | ".join(sentiment_lines) if sentiment_lines else "暂无"

    # 准确率
    stats = await get_accuracy_stats()
    acc_text = f"{stats['accuracy']}% ({stats['correct']}/{stats['total']})" if stats["total"] > 0 else "暂无数据"

    # 上次预测结果
    last = await get_last_prediction(result["coin"], result["timeframe"])
    last_text = ""
    if last:
        last_dir = "\U0001f7e2涨" if last["direction"] == "up" else "\U0001f534跌"
        if last["is_correct"]:
            last_result = "\u2705 正确"
        else:
            last_result = "\u274c 错误"
        change_pct = (last["price_at_validate"] - last["price_at_predict"]) / last["price_at_predict"] * 100
        last_text = f"\n\U0001f519 上次预测：{last_dir} → {last_result} ({change_pct:+.2f}%)\n"

    text = (
        f"\U0001f52e {coin_name} {tf} 预测\n\n"
        f"方向：{direction_emoji}\n"
        f"置信度：{stars} ({result['confidence']}/5)\n"
        f"依据：{result['reasoning']}\n\n"
        f"当前价格：${result['price']:,.2f}\n"
        f"技术指标：RSI {ind.get('rsi', 0)} | MACD {macd_arrow} | BB %B {ind.get('bb_percent_b', 0)}%\n"
        f"\U0001f4a1 市场情绪：{sentiment_text}\n"
        f"{last_text}\n"
        f"\U0001f4ca 近期准确率：{acc_text}"
    )

    await _send_text(text)
    logger.info(f"推送成功: {coin_name} {tf}")


async def send_validation_report(results: list[dict]):
    """推送验证结果汇总到 Telegram"""
    if not results or not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    lines = ["\U0001f50d 预测验证结果\n"]
    correct_count = sum(1 for r in results if r["is_correct"])

    for r in results:
        coin = "BTC" if "BTC" in r["coin"] else "ETH"
        mark = "\u2705" if r["is_correct"] else "\u274c"
        dir_text = "\U0001f7e2涨" if r["direction"] == "up" else "\U0001f534跌"
        actual_text = "\U0001f7e2涨" if r["actual_direction"] == "up" else "\U0001f534跌"
        change_pct = (r["price_at_validate"] - r["price_at_predict"]) / r["price_at_predict"] * 100
        lines.append(
            f"{mark} {coin} {r['timeframe']}: "
            f"预测{dir_text} 实际{actual_text} ({change_pct:+.2f}%)"
        )

    lines.append(f"\n本轮：{correct_count}/{len(results)} 正确")
    await _send_text("\n".join(lines))


async def send_daily_report():
    """推送每日报告"""
    stats = await get_daily_stats()
    if stats["total"] == 0:
        return  # 今天没有预测，不发报告

    # 准确率颜色标记
    acc = stats["accuracy"]
    acc_emoji = "\U0001f7e2" if acc >= 60 else "\U0001f7e1" if acc >= 50 else "\U0001f534"

    lines = [
        "\U0001f4cb 每日预测报告\n",
        f"预测总数: {stats['total']}",
        f"已验证: {stats['correct'] + stats['wrong']} ({acc_emoji} 准确率 {acc}%)",
        f"  \u2705 正确: {stats['correct']}  \u274c 错误: {stats['wrong']}",
        f"  \u23f3 待验证: {stats['pending']}",
    ]

    # 最佳预测
    if stats["best"]:
        b = stats["best"]
        coin = "BTC" if "BTC" in b["coin"] else "ETH"
        d = "\U0001f7e2涨" if b["direction"] == "up" else "\U0001f534跌"
        lines.append(f"\n\U0001f3c6 最佳预测: {coin} {b['timeframe']} {d} ({b['change_pct']:+.2f}%)")

    # 最差预测
    if stats["worst"]:
        w = stats["worst"]
        coin = "BTC" if "BTC" in w["coin"] else "ETH"
        d = "\U0001f7e2涨" if w["direction"] == "up" else "\U0001f534跌"
        lines.append(f"\U0001f4a2 最差预测: {coin} {w['timeframe']} {d} ({w['change_pct']:+.2f}%)")

    # 总体准确率
    overall = await get_accuracy_stats()
    if overall["total"] > 0:
        lines.append(f"\n\U0001f4ca 累计准确率: {overall['accuracy']}% ({overall['correct']}/{overall['total']})")

    await _send_text("\n".join(lines))


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "\U0001f52e CryptoPredictor Bot\n\n"
        "自动预测 BTC/ETH 涨跌，AI 自我学习越用越准。\n\n"
        "命令列表：\n"
        "/stats - 查看准确率统计\n"
        "/history - 最近预测记录\n"
        "/rules - 查看学习到的规则\n"
        "/predict - 手动触发预测"
    )


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = await get_accuracy_stats()
    if stats["total"] == 0:
        await update.message.reply_text("暂无预测数据，等待第一次预测...")
        return

    lines = [
        f"\U0001f4ca 预测准确率统计\n",
        f"总计：{stats['correct']}/{stats['total']} ({stats['accuracy']}%)\n",
    ]
    for g in stats["groups"]:
        coin = "BTC" if "BTC" in g["coin"] else "ETH"
        acc = round(g["correct"] / g["total"] * 100, 1) if g["total"] > 0 else 0
        lines.append(f"  {coin} {g['timeframe']}: {g['correct']}/{g['total']} ({acc}%)")

    await update.message.reply_text("\n".join(lines))


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    preds = await get_recent_predictions(limit=10)
    if not preds:
        await update.message.reply_text("暂无预测记录")
        return

    lines = ["\U0001f4dc 最近 10 条预测\n"]
    for p in preds:
        coin = "BTC" if "BTC" in p["coin"] else "ETH"
        d_emoji = "\U0001f7e2" if p["direction"] == "up" else "\U0001f534"
        result_mark = ""
        if p["validated_at"]:
            result_mark = " \u2705" if p["is_correct"] else " \u274c"
        time_str = p["created_at"][:16].replace("T", " ")
        lines.append(f"{d_emoji} {coin} {p['timeframe']} | {p['direction']} | ${p['price_at_predict']:,.0f}{result_mark} | {time_str}")

    await update.message.reply_text("\n".join(lines))


async def cmd_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rules = await get_latest_rules()
    if not rules:
        await update.message.reply_text("暂无学习规则，需要累积一些预测后才会开始学习。")
        return

    lines = ["\U0001f9e0 当前学习规则\n"]
    for i, rule in enumerate(rules, 1):
        lines.append(f"{i}. {rule}")
    await update.message.reply_text("\n".join(lines))


async def cmd_predict(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("\u23f3 正在验证上轮 + 预测新一轮...")

    # 先验证到期的预测
    val_results = await validate_predictions()
    if val_results:
        await send_validation_report(val_results)

    # /predict 只做 1H，4H 交给调度器（避免重复预测拉崩准确率）
    results = []
    for coin in COINS:
        result = await predict(coin, "1h")
        if result:
            results.append(result)
            await send_prediction(result)

    if not results:
        await update.message.reply_text("\u274c 预测失败，请检查日志")
    else:
        await update.message.reply_text(f"\u2705 完成 {len(results)} 条 1H 预测（4H 由调度器自动运行）")
