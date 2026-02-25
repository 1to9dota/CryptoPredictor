"""自我学习模块 — 分析历史预测对错，生成/更新规则"""

import json
import logging
from openai import AsyncOpenAI
from predictor.config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
from predictor.storage.database import (
    get_validated_predictions, get_latest_rules,
    get_accuracy_stats, save_learned_rules,
)

logger = logging.getLogger(__name__)


async def learn() -> list[str]:
    """执行一次学习循环

    1. 取最近 7 天已验证的预测
    2. 统计准确率
    3. 找出错误模式
    4. 让 LLM 总结规则
    5. 保存新规则

    Returns:
        新的规则列表
    """
    # 1. 获取数据
    validated = await get_validated_predictions(days=7)
    if len(validated) < 5:
        logger.info(f"已验证预测不足 5 条（当前 {len(validated)}），跳过学习")
        return await get_latest_rules()

    # 2. 统计
    stats = await get_accuracy_stats()
    total = stats["total"]
    correct = stats["correct"]
    accuracy = stats["accuracy"]

    # 分组统计
    group_stats = {}
    for g in stats["groups"]:
        key = f"{g['coin']} {g['timeframe']}"
        g_acc = round(g["correct"] / g["total"] * 100, 1) if g["total"] > 0 else 0
        group_stats[key] = f"{g_acc}% ({g['correct']}/{g['total']})"

    # 3. 提取错误案例（最有学习价值）
    wrong_cases = []
    for p in validated:
        if not p["is_correct"]:
            indicators = json.loads(p["indicators_snapshot"]) if p["indicators_snapshot"] else {}
            wrong_cases.append({
                "coin": p["coin"],
                "timeframe": p["timeframe"],
                "predicted": p["direction"],
                "actual": p["actual_direction"],
                "reasoning": p["reasoning"],
                "price_at_predict": p["price_at_predict"],
                "price_at_validate": p["price_at_validate"],
                "rsi": indicators.get("rsi"),
                "macd_histogram": indicators.get("macd_histogram"),
                "bb_percent_b": indicators.get("bb_percent_b"),
                "volume_ratio": indicators.get("volume_ratio"),
            })

    # 4. 获取当前规则
    current_rules = await get_latest_rules()

    # 5. 构建学习 prompt
    prompt = f"""你是一个交易策略优化师。以下是最近7天的预测记录：

## 统计概览
- 总预测: {total}, 正确: {correct}, 准确率: {accuracy}%
- 分组: {json.dumps(group_stats, ensure_ascii=False)}

## 错误案例（最有价值的学习材料）
{json.dumps(wrong_cases[:15], indent=2, ensure_ascii=False)}

## 当前规则
{json.dumps(current_rules, ensure_ascii=False) if current_rules else "暂无规则"}

请分析错误模式，更新规则列表。每条规则格式：
- 条件 → 判断（基于数据，不是猜测）
- 删除已被证伪的旧规则
- 规则数量控制在 5-10 条

输出 JSON，不要其他内容：
{{"rules": ["规则1", "规则2", ...], "analysis": "总结分析（100字内）"}}"""

    try:
        client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
        response = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
            max_tokens=800,
        )

        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        result = json.loads(content)
        new_rules = result["rules"]
        analysis = result.get("analysis", "")

        # 6. 保存
        await save_learned_rules(new_rules, accuracy, analysis)
        logger.info(f"学习完成: 准确率 {accuracy}%, 生成 {len(new_rules)} 条规则")
        logger.info(f"分析: {analysis}")

        return new_rules

    except Exception as e:
        logger.error(f"学习失败: {e}", exc_info=True)
        return current_rules
