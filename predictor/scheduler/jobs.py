"""APScheduler 定时任务"""

import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from predictor.config import COINS, TIMEFRAMES, MIN_CONFIDENCE
from predictor.ai.predictor import predict
from predictor.ai.learner import learn
from predictor.tracker.validator import validate_predictions
from predictor.bot.telegram_bot import send_prediction, send_validation_report

logger = logging.getLogger(__name__)


async def job_validate():
    """验证已到期预测，并推送结果"""
    logger.info("=== 验证任务开始 ===")
    results = await validate_predictions()
    if results:
        await send_validation_report(results)


async def job_predict_1h():
    """每小时预测任务（先验证上一轮，再预测新一轮）"""
    logger.info("=== 1H 预测任务开始 ===")
    # 先验证到期的预测
    results = await validate_predictions()
    if results:
        await send_validation_report(results)

    # 再做新预测
    for coin in COINS:
        result = await predict(coin, "1h")
        if result and result["confidence"] >= MIN_CONFIDENCE:
            await send_prediction(result)


async def job_predict_4h():
    """每4小时预测任务"""
    logger.info("=== 4H 预测任务开始 ===")
    for coin in COINS:
        result = await predict(coin, "4h")
        if result and result["confidence"] >= MIN_CONFIDENCE:
            await send_prediction(result)


async def job_learn():
    """每日学习任务"""
    logger.info("=== 每日学习任务开始 ===")
    rules = await learn()
    logger.info(f"学习完成，当前规则数: {len(rules)}")


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

    return scheduler
