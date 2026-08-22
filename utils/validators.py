"""
AstrBot 签到插件 - 输入验证模块

版本: 2.0.0
"""

import re
from typing import Optional, Tuple

from astrbot.api.event import AstrMessageEvent

from ..core.constants import QQ_NUMBER_PATTERN, NUMBERS_PATTERN, MAX_NICKNAME_LENGTH


def extract_target_qq(event: AstrMessageEvent) -> Optional[str]:
    """从消息中提取目标QQ号

    优先检查消息中的 at 提及，其次正则匹配数字。

    Args:
        event: 消息事件对象

    Returns:
        提取到的QQ号，未找到则返回 None
    """
    message_text = event.message_str or ""

    # 优先检查消息中的 at
    if hasattr(event.message_obj, "at") and event.message_obj.at:
        return str(event.message_obj.at[0])

    # 正则匹配QQ号（5-12位数字）
    match = QQ_NUMBER_PATTERN.search(message_text)
    if match:
        return match.group(1)

    return None


def extract_amount(event: AstrMessageEvent) -> Optional[int]:
    """从消息中提取金额

    匹配消息中的数字，智能区分QQ号和金额。

    Args:
        event: 消息事件对象

    Returns:
        提取到的金额，未找到则返回 None
    """
    message_text = event.message_str or ""
    numbers = NUMBERS_PATTERN.findall(message_text)

    if len(numbers) >= 2:
        # 如果有多个数字，取最后一个作为金额（第一个是QQ号）
        return int(numbers[-1])
    elif len(numbers) == 1:
        val = int(numbers[0])
        # 如果只有一个数字且大于10000，可能是QQ号
        if val > 100000:
            return None
        return val

    return None


def validate_nickname(name: str) -> Tuple[bool, str]:
    """验证昵称有效性

    Args:
        name: 待验证的昵称

    Returns:
        (是否有效, 错误信息)
    """
    if not name or not name.strip():
        return False, "名称不能为空"
    if len(name) > MAX_NICKNAME_LENGTH:
        return False, f"名称不能超过{MAX_NICKNAME_LENGTH}个字符"
    return True, ""


def validate_positive_int(value: any, field_name: str = "数值") -> Tuple[bool, str]:
    """验证正整数

    Args:
        value: 待验证的值
        field_name: 字段名称（用于错误提示）

    Returns:
        (是否有效, 错误信息)
    """
    try:
        val = int(value)
        if val <= 0:
            return False, f"{field_name}必须大于0"
        return True, ""
    except (ValueError, TypeError):
        return False, f"{field_name}必须是有效的数字"


def format_amount_change(before: int, after: int, label: str) -> str:
    """格式化金额变化显示

    Args:
        before: 变化前金额
        after: 变化后金额
        label: 标签名称

    Returns:
        格式化后的字符串
    """
    change = after - before
    if change > 0:
        return f"{label}: {before} → {after} (+{change})"
    elif change < 0:
        return f"{label}: {before} → {after} ({change})"
    else:
        return f"{label}: {before} → {after} (无变化)"
