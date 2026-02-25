"""轻量 Web 面板 — aiohttp 服务器"""

import json
import logging
from pathlib import Path
from aiohttp import web
from predictor.storage.database import (
    get_accuracy_stats, get_recent_predictions, get_latest_rules,
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
