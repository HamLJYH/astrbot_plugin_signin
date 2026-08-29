"""
AstrBot 签到插件 - 常量定义模块 

版本: 2.0.1
"""

import re
from dataclasses import dataclass
from datetime import timezone, timedelta
from typing import Dict, Pattern

# 时区
TZ_BEIJING = timezone(timedelta(hours=8))

# 基础常量
MAX_NICKNAME_LENGTH = 15
MAX_HISTORY_LENGTH = 100
MAX_TRANSFER_HISTORY = 20

# 里程碑天数
MILESTONES = [7, 30, 100, 365]

# 商店商品定义
SHOP_ITEMS: Dict[str, Dict[str, any]] = {
    "1": {"name": "🎁 神秘礼盒", "price": 50, "desc": "随机获得 10-100 积分"},
    "2": {"name": "🍀 幸运符", "price": 30, "desc": "下次签到积分翻倍（限1次）"},
    "3": {"name": "🔮 占卜卡", "price": 20, "desc": "查看今日运势"},
    "4": {"name": "💎 改名卡", "price": 100, "desc": "修改在排行榜中的显示名称"},
    "5": {"name": "🛡️ 补签卡", "price": 80, "desc": "补签昨天，保持连续签到"},
    "6": {"name": "🎲 抽奖券", "price": 20, "desc": "参与积分抽奖，大奖等你拿"},
}

# 每日限购商品
DAILY_LIMIT_ITEMS = {"1", "6"}

# 运势等级与描述
FORTUNES: Dict[str, list] = {
    "大吉": ["鸿运当头", "万事如意", "心想事成", "财运亨通"],
    "吉": ["顺风顺水", "好事将近", "贵人相助", "小有收获"],
    "中": ["平平淡淡", "稳如老狗", "无功无过", "维持现状"],
    "凶": ["小心为上", "诸事不宜", "低调行事", "注意身体"],
}

# 运势权重
FORTUNE_WEIGHTS = {"大吉": 15, "吉": 35, "中": 40, "凶": 10}

# 运势表情
FORTUNE_EMOJIS = {"大吉": "🌟", "吉": "✨", "中": "☁️", "凶": "⚡"}

# 幸运颜色
LUCKY_COLORS = ["红", "黄", "蓝", "绿", "紫", "黑", "白"]

# 幸运方位
LUCKY_DIRECTIONS = ["东", "南", "西", "北", "东南", "西北", "东北", "西南"]

# 抽奖奖品定义
LOTTERY_PRIZES = [
    ("💸 谢谢参与", 0, 0.25),
    ("🪙 小奖", (5, 20), 0.30),
    ("💰 中奖", (30, 80), 0.20),
    ("💎 大奖", (100, 200), 0.04),
    ("👑 特等奖", (300, 500), 0.01),
    ("⚡ 小惩罚", (-15, -5), 0.12),
    ("💀 大惩罚", (-50, -20), 0.08),
]

# 排行榜表情
RANK_EMOJIS = {1: "🥇", 2: "🥈", 3: "🥉"}

# 消息表情
class MessageEmoji:
    """消息表情符号"""
    ERROR = "❌"
    SUCCESS = "✅"
    WARNING = "⚠️"
    INFO = "ℹ️"
    COIN = "💰"
    FIRE = "🔥"
    STAR = "⭐"
    SHOP = "🏪"
    TROPHY = "🏆"
    CALENDAR = "📅"
    CHART = "📊"
    GIFT = "🎁"
    DICE = "🎲"
    SHIELD = "🛡️"
    CRYSTAL = "💎"
    MAGIC = "🔮"
    CLOVER = "🍀"
    CLOCK = "⏰"
    MONEY = "💸"
    ARROW_RIGHT = "📤"
    ARROW_LEFT = "📥"
    TRASH = "🗑️"
    BOOK = "📖"
    BAG = "🎒"

# 编译正则表达式
QQ_NUMBER_PATTERN: Pattern = re.compile(r"(?:@|QQ|qq)?\s*(\d{5,12})")
NUMBERS_PATTERN: Pattern = re.compile(r"\b(\d+)\b")

# 数据库表名
DB_TABLES = {
    "users": "users",
    "signin_records": "signin_records",
    "inventory": "inventory",
    "transfers": "transfers",
}

# 旧数据文件名（用于迁移）
LEGACY_DATA_FILENAME = "signin_data.json"
