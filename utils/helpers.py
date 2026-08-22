"""
AstrBot 签到插件 - 通用工具模块

版本: 2.0.0
"""

import random
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from astrbot.api.event import AstrMessageEvent

from ..core.constants import (
    TZ_BEIJING, FORTUNES, FORTUNE_WEIGHTS, FORTUNE_EMOJIS,
    LUCKY_COLORS, LUCKY_DIRECTIONS, RANK_EMOJIS
)


def get_today(reset_hour: int = 5) -> str:
    """获取当前日期（考虑重置时间）

    Args:
        reset_hour: 每日重置时间（小时）

    Returns:
        日期字符串 YYYY-MM-DD
    """
    now = datetime.now(TZ_BEIJING)
    if now.hour < reset_hour:
        now = now - timedelta(days=1)
    return now.strftime("%Y-%m-%d")


def get_yesterday(reset_hour: int = 5) -> str:
    """获取昨天日期

    Args:
        reset_hour: 每日重置时间（小时）

    Returns:
        昨天日期字符串 YYYY-MM-DD
    """
    today = datetime.strptime(get_today(reset_hour), "%Y-%m-%d").replace(tzinfo=TZ_BEIJING)
    yesterday = today - timedelta(days=1)
    return yesterday.strftime("%Y-%m-%d")


def get_before_yesterday(reset_hour: int = 5) -> str:
    """获取前天日期

    Args:
        reset_hour: 每日重置时间（小时）

    Returns:
        前天日期字符串 YYYY-MM-DD
    """
    today = datetime.strptime(get_today(reset_hour), "%Y-%m-%d").replace(tzinfo=TZ_BEIJING)
    before_yesterday = today - timedelta(days=2)
    return before_yesterday.strftime("%Y-%m-%d")


def get_user_id(event: AstrMessageEvent) -> str:
    """获取用户唯一ID

    格式: platform:sender_id

    Args:
        event: 消息事件对象

    Returns:
        用户唯一ID
    """
    sender_id = event.get_sender_id()
    platform = event.get_platform_name()
    return f"{platform}:{sender_id}"


def get_user_name(event: AstrMessageEvent) -> str:
    """获取用户名称

    Args:
        event: 消息事件对象

    Returns:
        用户名称
    """
    return event.get_sender_name() or "匿名用户"


def get_rank_emoji(rank: int) -> str:
    """获取排名对应的表情

    Args:
        rank: 排名

    Returns:
        排名表情或编号
    """
    return RANK_EMOJIS.get(rank, f"#{rank}")


def generate_fortune() -> Dict[str, Any]:
    """生成今日运势

    Returns:
        运势数据字典
    """
    levels = list(FORTUNES.keys())
    weights = [FORTUNE_WEIGHTS[level] for level in levels]
    level = random.choices(levels, weights=weights)[0]
    desc = random.choice(FORTUNES[level])

    return {
        "date": get_today(),
        "level": level,
        "desc": desc,
        "lucky_num": random.randint(1, 99),
        "lucky_color": random.choice(LUCKY_COLORS),
        "lucky_dir": random.choice(LUCKY_DIRECTIONS),
        "emoji": FORTUNE_EMOJIS[level],
    }


def format_fortune_message(fortune: Dict[str, Any], display_name: str) -> str:
    """格式化运势消息

    Args:
        fortune: 运势数据
        display_name: 显示名称

    Returns:
        格式化后的运势消息
    """
    return (
        f"🔮 {display_name} 的今日运势\n\n"
        f"{fortune['emoji']} 运势: {fortune['level']} - {fortune['desc']}\n"
        f"🔢 幸运数字: {fortune['lucky_num']}\n"
        f"🎨 幸运色: {fortune['lucky_color']}\n"
        f"🧭 幸运方位: {fortune['lucky_dir']}"
    )


def calculate_signin_points(
    base_points: int,
    streak: int,
    streak_bonus_enabled: bool,
    streak_bonus_rate: float,
    max_streak_bonus: float,
    lucky_draw_enabled: bool,
    lucky_draw_max: int,
    double_next: bool = False
) -> Dict[str, int]:
    """计算签到积分

    Args:
        base_points: 基础积分
        streak: 连续签到天数
        streak_bonus_enabled: 是否启用连续加成
        streak_bonus_rate: 连续加成比例
        max_streak_bonus: 最大加成倍数
        lucky_draw_enabled: 是否启用幸运抽奖
        lucky_draw_max: 幸运奖励上限
        double_next: 是否触发双倍积分

    Returns:
        积分明细字典
    """
    streak_bonus = 0
    if streak_bonus_enabled and streak > 1:
        multiplier = 1 + min((streak - 1) * streak_bonus_rate, max_streak_bonus - 1)
        streak_bonus = int(base_points * (multiplier - 1))

    lucky_points = 0
    if lucky_draw_enabled:
        if random.random() < 0.2:
            lucky_points = random.randint(1, lucky_draw_max)

    total = base_points + streak_bonus + lucky_points

    if double_next:
        total *= 2

    return {
        "total": total,
        "base": base_points,
        "streak_bonus": streak_bonus,
        "lucky": lucky_points,
    }


def check_milestone(streak: int) -> Optional[int]:
    """检查是否达到里程碑

    Args:
        streak: 连续签到天数

    Returns:
        达到的里程碑天数，未达成为 None
    """
    from ..core.constants import MILESTONES
    if streak in MILESTONES:
        return streak
    return None
