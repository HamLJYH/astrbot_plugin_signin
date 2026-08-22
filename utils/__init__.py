"""
AstrBot 签到插件 - 工具模块

版本: 2.0.0
"""

from .decorators import handle_errors
from .validators import (
    extract_target_qq,
    extract_amount,
    validate_nickname,
    validate_positive_int,
    format_amount_change,
)
from .helpers import (
    get_today,
    get_yesterday,
    get_before_yesterday,
    get_user_id,
    get_user_name,
    get_rank_emoji,
    generate_fortune,
    format_fortune_message,
    calculate_signin_points,
    check_milestone,
)

__all__ = [
    "handle_errors",
    "extract_target_qq",
    "extract_amount",
    "validate_nickname",
    "validate_positive_int",
    "format_amount_change",
    "get_today",
    "get_yesterday",
    "get_before_yesterday",
    "get_user_id",
    "get_user_name",
    "get_rank_emoji",
    "generate_fortune",
    "format_fortune_message",
    "calculate_signin_points",
    "check_milestone",
]
