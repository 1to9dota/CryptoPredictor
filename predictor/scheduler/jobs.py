"""APScheduler 定时任务"""

import logging
import traceback
from datetime import datetime, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from predictor.config import COINS, TIMEFRAMES, MIN_CONFIDENCE
from predictor.ai.predictor import predict
from predictor.ai.learner import learn
from predictor.tracker.validator import validate_predictions
from predictor.bot.telegram_bot import (
    send_prediction, send_validation_report, send_alert,
    send_price_alert, send_daily_report,
)
from predictor.tracker.price_alert import check_price_alerts

logger = logging.getLogger(__name__)

# 连续失败计数器（达到阈值时告警）
_fail_counts: dict[str, int] = {}
_FAIL_THRESHOLD = 2  # 连续失败 2 次触发告警


def _reset_fail(key: str):
    _fail_counts[key] = 0


def _inc_fail(key: str) -> int:
    _fail_counts[key] = _fail_counts.get(key, 0) + 1
    return _fail_counts[key]


async def job_validate():
    """验证已到期预测，并推送结果"""
    logger.info("=== 验证任务开始 ===")
    try:
        results = await validate_predictions()
        if results:
            await send_validation_report(results)
        _reset_fail("validate")
    except Exception as e:
        logger.error(f"验证任务异常: {e}", exc_info=True)
        count = _inc_fail("validate")
        if count >= _FAIL_THRESHOLD:
            await send_alert(f"验证任务连续失败 {count} 次\n错误: {e}")


async def job_predict_1h():
    """每小时预测任务（先验证上一轮，再预测新一轮）"""
    logger.info("=== 1H 预测任务开始 ===")
    try:
        # 先验证到期的预测
        results = await validate_predictions()
        if results:
            await send_validation_report(results)
    except Exception as e:
        logger.error(f"1H 验证异常: {e}", exc_info=True)

    # 再做新预测
    fail_coins = []
    for coin in COINS:
        try:
            result = await predict(coin, "1h")
            if result and result["confidence"] >= MIN_CONFIDENCE:
                await send_prediction(result)
                _reset_fail(f"predict_1h_{coin}")
            elif result is None:
                fail_coins.append(coin)
                count = _inc_fail(f"predict_1h_{coin}")
                if count >= _FAIL_THRESHOLD:
                    await send_alert(f"1H 预测连续失败 {count} 次: {coin}")
        except Exception as e:
            fail_coins.append(coin)
            logger.error(f"1H 预测异常 {coin}: {e}", exc_info=True)
            count = _inc_fail(f"predict_1h_{coin}")
            if count >= _FAIL_THRESHOLD:
                await send_alert(f"1H 预测异常 {coin} (连续 {count} 次)\n{e}")


async def job_predict_4h():
    """每4小时预测任务"""
    logger.info("=== 4H 预测任务开始 ===")
    for coin in COINS:
        try:
            result = await predict(coin, "4h")
            if result and result["confidence"] >= MIN_CONFIDENCE:
                await send_prediction(result)
                _reset_fail(f"predict_4h_{coin}")
            elif result is None:
                count = _inc_fail(f"predict_4h_{coin}")
                if count >= _FAIL_THRESHOLD:
                    await send_alert(f"4H 预测连续失败 {count} 次: {coin}")
        except Exception as e:
            logger.error(f"4H 预测异常 {coin}: {e}", exc_info=True)
            count = _inc_fail(f"predict_4h_{coin}")
            if count >= _FAIL_THRESHOLD:
                await send_alert(f"4H 预测异常 {coin} (连续 {count} 次)\n{e}")


async def job_learn():
    """每日学习任务"""
    logger.info("=== 每日学习任务开始 ===")
    try:
        rules = await learn()
        logger.info(f"学习完成，当前规则数: {len(rules)}")
        _reset_fail("learn")
    except Exception as e:
        logger.error(f"学习任务异常: {e}", exc_info=True)
        count = _inc_fail("learn")
        if count >= _FAIL_THRESHOLD:
            await send_alert(f"每日学习任务连续失败 {count} 次\n{e}")


async def job_daily_report():
    """每日报告 — UTC 23:55 发送当天汇总"""
    logger.info("=== 每日报告任务开始 ===")
    try:
        await send_daily_report()
        _reset_fail("daily_report")
    except Exception as e:
        logger.error(f"每日报告异常: {e}", exc_info=True)
        count = _inc_fail("daily_report")
        if count >= _FAIL_THRESHOLD:
            await send_alert(f"每日报告连续失败 {count} 次\n{e}")


async def job_price_alert():
    """每 5 分钟检查价格告警"""
    for coin in COINS:
        try:
            alerts = await check_price_alerts(coin)
            for alert in alerts:
                await send_price_alert(alert)
                logger.info(f"价格告警: {alert['coin']} {alert['type']}")
        except Exception as e:
            logger.error(f"价格告警任务异常 {coin}: {e}", exc_info=True)


async def job_heartbeat():
    """心跳检测 — 每 6 小时发一次，证明系统还活着"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    await send_alert(f"\U0001f49a 系统心跳正常\n时间: {now}\n连续失败计数: {dict(_fail_counts) or '全部正常'}")


def create_scheduler() -> AsyncIOScheduler:
    """创建并配置调度器"""
    scheduler = AsyncIOScheduler(timezone="UTC")

    # 每小时 :05 — 先验证再预测
    scheduler.add_job(
        job_predict_1h, CronTrigger(minute=5),
        id="predict_1h", name="1H预测",
        misfire_grace_time=300,
    )

    # 每4小时（0/4/8/12/16/20 点）:05
    scheduler.add_job(
        job_predict_4h, CronTrigger(hour="0,4,8,12,16,20", minute=5),
        id="predict_4h", name="4H预测",
        misfire_grace_time=300,
    )

    # 每小时 :30 额外验证（兜底）
    scheduler.add_job(
        job_validate, CronTrigger(minute=30),
        id="validate", name="预测验证",
        misfire_grace_time=300,
    )

    # 每天 UTC 0:00 学习
    scheduler.add_job(
        job_learn, CronTrigger(hour=0, minute=0),
        id="learn", name="每日学习",
        misfire_grace_time=3600,
    )

    # 每天 UTC 23:55 每日报告
    scheduler.add_job(
        job_daily_report, CronTrigger(hour=23, minute=55),
        id="daily_report", name="每日报告",
        misfire_grace_time=600,
    )

    # 每 5 分钟价格告警检查
    scheduler.add_job(
        job_price_alert, CronTrigger(minute="*/5"),
        id="price_alert", name="价格告警",
        misfire_grace_time=120,
    )

    # 每 6 小时心跳（UTC 3/9/15/21 点）
    scheduler.add_job(
        job_heartbeat, CronTrigger(hour="3,9,15,21", minute=0),
        id="heartbeat", name="心跳检测",
        misfire_grace_time=600,
    )

    return scheduler
