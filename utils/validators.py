"""
AstrBot 签到插件 - 输入验证模块 

版本: 2.0.2
"""

import re
from typing import Optional, Tuple

from astrbot.api.event import AstrMessageEvent

from ..core.constants import QQ_NUMBER_PATTERN, NUMBERS_PATTERN, MAX_NICKNAME_LENGTH


def extract_target_qq(event: AstrMessageEvent) -> Optional[str]:
    """从消息中提取目标QQ号"""
    message_text = event.message_str or ""
    if hasattr(event.message_obj, "at") and event.message_obj.at:
        return str(event.message_obj.at[0])
    match = QQ_NUMBER_PATTERN.search(message_text)
    if match:
        return match.group(1)
    return None


def extract_amount(event: AstrMessageEvent) -> Optional[int]:
    """从消息中提取金额"""
    message_text = event.message_str or ""
    numbers = NUMBERS_PATTERN.findall(message_text)
    if len(numbers) >= 2:
        return int(numbers[-1])
    elif len(numbers) == 1:
        val = int(numbers[0])
        if val > 100000:
            return None
        return val
    return None


def validate_nickname(name: str) -> Tuple[bool, str]:
    """验证昵称有效性"""
    if not name or not name.strip():
        return False, "名称不能为空"
    if len(name) > MAX_NICKNAME_LENGTH:
        return False, f"名称不能超过{MAX_NICKNAME_LENGTH}个字符"
    return True, ""


def validate_positive_int(value: any, field_name: str = "数值") -> Tuple[bool, str]:
    """验证正整数"""
    try:
        val = int(value)
        if val <= 0:
            return False, f"{field_name}必须大于0"
        return True, ""
    except (ValueError, TypeError):
        return False, f"{field_name}必须是有效的数字"


def format_amount_change(before: int, after: int, label: str) -> str:
    """格式化金额变化显示"""
    change = after - before
    if change > 0:
        return f"{label}: {before} → {after} (+{change})"
    elif change < 0:
        return f"{label}: {before} → {after} ({change})"
    else:
        return f"{label}: {before} → {after} (无变化)"
