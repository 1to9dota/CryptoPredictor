"""CryptoPredictor 主入口 — 启动 Telegram Bot + 调度器"""

import asyncio
import logging
import signal
from predictor.config import TELEGRAM_BOT_TOKEN
from predictor.bot.telegram_bot import get_app
from predictor.scheduler.jobs import create_scheduler
from predictor.storage.database import get_db, close_db
from predictor.web.server import start_web_server

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("predictor")


async def main():
    """主函数：初始化数据库 → 启动调度器 → 启动 Bot"""
    logger.info("CryptoPredictor 启动中...")

    # 初始化数据库
    await get_db()
    logger.info("数据库初始化完成")

    # 启动调度器
    scheduler = create_scheduler()
    scheduler.start()
    logger.info("调度器启动完成，已注册任务：")
    for job in scheduler.get_jobs():
        logger.info(f"  - {job.name} ({job.id}): {job.trigger}")

    # 启动 Telegram Bot
    if TELEGRAM_BOT_TOKEN:
        app = get_app()
        logger.info("Telegram Bot 启动中...")
        # 使用 polling 模式（长轮询，适合自用）
        await app.initialize()
        await app.start()
        await app.updater.start_polling(
            drop_pending_updates=True,
            allowed_updates=["message", "callback_query"],
        )
        logger.info("Telegram Bot 已启动")
    else:
        logger.warning("TELEGRAM_BOT_TOKEN 未配置，Bot 不启动")

    # 启动 Web 面板
    web_runner = await start_web_server(port=8088)

    # 保持运行
    stop_event = asyncio.Event()

    def _signal_handler():
        logger.info("收到停止信号")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    logger.info("CryptoPredictor 运行中，按 Ctrl+C 停止")
    await stop_event.wait()

    # 优雅关闭
    logger.info("正在关闭...")
    scheduler.shutdown(wait=False)
    if TELEGRAM_BOT_TOKEN:
        app = get_app()
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
    await web_runner.cleanup()
    await close_db()
    logger.info("CryptoPredictor 已停止")


if __name__ == "__main__":
    asyncio.run(main())
