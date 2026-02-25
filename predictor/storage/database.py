"""SQLite 异步数据库操作"""

import json
import aiosqlite
from datetime import datetime, timezone
from predictor.config import DB_PATH

_db: aiosqlite.Connection | None = None


async def get_db() -> aiosqlite.Connection:
    """获取数据库连接（单例）"""
    global _db
    if _db is None:
        _db = await aiosqlite.connect(str(DB_PATH))
        _db.row_factory = aiosqlite.Row
        await _db.execute("PRAGMA journal_mode=WAL")
        await _init_tables(_db)
    return _db


async def close_db():
    """关闭数据库连接"""
    global _db
    if _db:
        await _db.close()
        _db = None


async def _init_tables(db: aiosqlite.Connection):
    """初始化数据库表"""
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            coin TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            direction TEXT NOT NULL,
            confidence INTEGER NOT NULL,
            reasoning TEXT,
            price_at_predict REAL,
            indicators_snapshot TEXT,
            price_at_validate REAL,
            actual_direction TEXT,
            is_correct INTEGER,
            validated_at TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS learned_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rules_json TEXT NOT NULL,
            accuracy_at_learn REAL,
            analysis TEXT,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_predictions_validate
            ON predictions(validated_at, coin, timeframe);
        CREATE INDEX IF NOT EXISTS idx_predictions_created
            ON predictions(created_at);
    """)
    await db.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def save_prediction(coin: str, timeframe: str, direction: str,
                          confidence: int, reasoning: str,
                          price: float, indicators: dict) -> int:
    """保存一条预测记录，返回 ID"""
    db = await get_db()
    cursor = await db.execute(
        """INSERT INTO predictions
           (coin, timeframe, direction, confidence, reasoning,
            price_at_predict, indicators_snapshot, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (coin, timeframe, direction, confidence, reasoning,
         price, json.dumps(indicators, ensure_ascii=False), _now())
    )
    await db.commit()
    return cursor.lastrowid


async def get_pending_validations(timeframe: str) -> list[dict]:
    """获取待验证的预测（未 validated 且已过验证时间）"""
    db = await get_db()
    # 1h 预测在 1 小时后验证，4h 预测在 4 小时后验证
    hours = 1 if timeframe == "1h" else 4
    cursor = await db.execute(
        """SELECT id, coin, timeframe, direction, price_at_predict, created_at
           FROM predictions
           WHERE validated_at IS NULL AND timeframe = ?
             AND datetime(created_at) <= datetime('now', ?)""",
        (timeframe, f"-{hours} hours")
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def update_validation(pred_id: int, price_at_validate: float,
                            actual_direction: str, is_correct: bool):
    """更新预测验证结果"""
    db = await get_db()
    await db.execute(
        """UPDATE predictions
           SET price_at_validate = ?, actual_direction = ?,
               is_correct = ?, validated_at = ?
           WHERE id = ?""",
        (price_at_validate, actual_direction, int(is_correct), _now(), pred_id)
    )
    await db.commit()


async def get_last_prediction(coin: str, timeframe: str) -> dict | None:
    """获取某币种某周期的上一条已验证预测"""
    db = await get_db()
    cursor = await db.execute(
        """SELECT * FROM predictions
           WHERE coin = ? AND timeframe = ? AND validated_at IS NOT NULL
           ORDER BY created_at DESC LIMIT 1""",
        (coin, timeframe)
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def get_recent_predictions(limit: int = 20, coin: str = None) -> list[dict]:
    """获取最近的预测记录"""
    db = await get_db()
    query = "SELECT * FROM predictions"
    params = []
    if coin:
        query += " WHERE coin = ?"
        params.append(coin)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_validated_predictions(days: int = 7) -> list[dict]:
    """获取最近 N 天已验证的预测"""
    db = await get_db()
    cursor = await db.execute(
        """SELECT * FROM predictions
           WHERE validated_at IS NOT NULL
             AND datetime(created_at) >= datetime('now', ?)
           ORDER BY created_at DESC""",
        (f"-{days} days",)
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_accuracy_stats() -> dict:
    """获取准确率统计"""
    db = await get_db()
    # 总体
    cursor = await db.execute(
        """SELECT COUNT(*) as total,
                  SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) as correct
           FROM predictions WHERE validated_at IS NOT NULL"""
    )
    row = await cursor.fetchone()
    total, correct = row["total"], row["correct"] or 0

    # 分组统计
    cursor = await db.execute(
        """SELECT coin, timeframe,
                  COUNT(*) as total,
                  SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) as correct
           FROM predictions WHERE validated_at IS NOT NULL
           GROUP BY coin, timeframe"""
    )
    groups = [dict(r) for r in await cursor.fetchall()]

    return {
        "total": total,
        "correct": correct,
        "accuracy": round(correct / total * 100, 1) if total > 0 else 0,
        "groups": groups,
    }


async def save_learned_rules(rules: list[str], accuracy: float, analysis: str):
    """保存学习到的规则"""
    db = await get_db()
    await db.execute(
        """INSERT INTO learned_rules (rules_json, accuracy_at_learn, analysis, created_at)
           VALUES (?, ?, ?, ?)""",
        (json.dumps(rules, ensure_ascii=False), accuracy, analysis, _now())
    )
    await db.commit()


async def get_latest_rules() -> list[str]:
    """获取最新的学习规则"""
    db = await get_db()
    cursor = await db.execute(
        "SELECT rules_json FROM learned_rules ORDER BY created_at DESC LIMIT 1"
    )
    row = await cursor.fetchone()
    if row:
        return json.loads(row["rules_json"])
    return []
