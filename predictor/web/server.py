"""轻量 Web 面板 — aiohttp 服务器"""

import json
import logging
from pathlib import Path
from aiohttp import web
from predictor.storage.database import (
    get_accuracy_stats, get_recent_predictions, get_latest_rules,
    get_db,
)

logger = logging.getLogger(__name__)


async def api_stats(request):
    """准确率统计"""
    stats = await get_accuracy_stats()
    return web.json_response(stats)


async def api_predictions(request):
    """预测历史"""
    limit = int(request.query.get("limit", "50"))
    preds = await get_recent_predictions(limit=limit)
    return web.json_response(preds)


async def api_rules(request):
    """学习规则"""
    rules = await get_latest_rules()
    return web.json_response({"rules": rules})


async def api_klines(request):
    """K线 + 技术指标"""
    coin = request.query.get("coin", "BTCUSDT")
    tf = request.query.get("tf", "1h")
    limit = int(request.query.get("limit", "50"))
    try:
        from predictor.data.fetcher import fetch_klines
        from predictor.data.indicators import calc_all
        klines = await fetch_klines(coin, tf, limit)
        if not klines:
            return web.json_response({"error": "获取K线失败"}, status=500)
        closes = [k["close"] for k in klines]
        volumes = [k["volume"] for k in klines]
        indicators = calc_all(closes, volumes)
        return web.json_response({
            "coin": coin,
            "timeframe": tf,
            "klines": klines[-10:],
            "indicators": indicators,
        })
    except Exception as e:
        logger.error(f"klines API 错误: {e}", exc_info=True)
        return web.json_response({"error": str(e)}, status=500)


async def api_market(request):
    """市场情绪数据"""
    coin = request.query.get("coin", "BTCUSDT")
    tf = request.query.get("tf", "1h")
    try:
        from predictor.data.market_data import fetch_market_data
        market = await fetch_market_data(coin, tf)
        return web.json_response({"coin": coin, "market": market or {}})
    except Exception as e:
        logger.error(f"market API 错误: {e}", exc_info=True)
        return web.json_response({"error": str(e)}, status=500)


async def api_predict_latest(request):
    """最近一次预测"""
    coin = request.query.get("coin", "")
    try:
        db = await get_db()
        if coin:
            row = await db.execute(
                "SELECT * FROM predictions WHERE coin = ? ORDER BY created_at DESC LIMIT 1",
                (coin,),
            )
        else:
            row = await db.execute(
                "SELECT * FROM predictions ORDER BY created_at DESC LIMIT 1"
            )
        row = await row.fetchone()
        if not row:
            return web.json_response({"error": "暂无预测"}, status=404)
        return web.json_response(dict(row))
    except Exception as e:
        logger.error(f"predict/latest API 错误: {e}", exc_info=True)
        return web.json_response({"error": str(e)}, status=500)


async def index(request):
    """首页"""
    html_path = Path(__file__).parent / "index.html"
    return web.FileResponse(html_path)


def create_web_app() -> web.Application:
    """创建 Web 应用"""
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/api/stats", api_stats)
    app.router.add_get("/api/predictions", api_predictions)
    app.router.add_get("/api/rules", api_rules)
    app.router.add_get("/api/klines", api_klines)
    app.router.add_get("/api/market", api_market)
    app.router.add_get("/api/predict/latest", api_predict_latest)
    return app


async def start_web_server(port: int = 8088):
    """启动 Web 服务器"""
    app = create_web_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Web 面板启动: http://localhost:{port}")
    return runner
