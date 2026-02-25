"""预测结果验证 — 回看实际价格判断对错"""

import logging
from predictor.data.fetcher import get_current_price
from predictor.storage.database import get_pending_validations, update_validation

logger = logging.getLogger(__name__)


async def validate_predictions() -> list[dict]:
    """验证所有已到期的预测

    Returns:
        本轮验证的结果列表（用于推送通知）
    """
    validated = []

    for timeframe in ["1h", "4h"]:
        pending = await get_pending_validations(timeframe)
        if not pending:
            continue

        for pred in pending:
            try:
                current_price = await get_current_price(pred["coin"])
                predict_price = pred["price_at_predict"]

                if current_price > predict_price:
                    actual_direction = "up"
                elif current_price < predict_price:
                    actual_direction = "down"
                else:
                    actual_direction = "up"

                is_correct = (actual_direction == pred["direction"])

                await update_validation(
                    pred_id=pred["id"],
                    price_at_validate=current_price,
                    actual_direction=actual_direction,
                    is_correct=is_correct,
                )

                change_pct = (current_price - predict_price) / predict_price * 100
                mark = "correct" if is_correct else "wrong"
                logger.info(
                    f"验证: {pred['coin']} {pred['timeframe']} "
                    f"预测={pred['direction']} 实际={actual_direction} "
                    f"({change_pct:+.2f}%) → {mark}"
                )

                validated.append({
                    "coin": pred["coin"],
                    "timeframe": pred["timeframe"],
                    "direction": pred["direction"],
                    "actual_direction": actual_direction,
                    "is_correct": is_correct,
                    "price_at_predict": predict_price,
                    "price_at_validate": current_price,
                })

            except Exception as e:
                logger.error(f"验证失败 prediction#{pred['id']}: {e}")

    if validated:
        logger.info(f"本轮验证完成: {len(validated)} 条")
    return validated
