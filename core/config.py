"""
AstrBot 签到插件 - 配置模型模块 

版本: 2.0.1
"""

from dataclasses import dataclass
from typing import Dict, Any


@dataclass
class PluginConfig:
    """插件配置模型"""
    base_points: int = 10
    streak_bonus: bool = True
    streak_bonus_rate: float = 0.1
    max_streak_bonus: float = 2.0
    top_limit: int = 10
    reset_hour: int = 5
    enable_rank: bool = True
    lucky_draw: bool = True
    lucky_draw_points_max: int = 50
    enable_shop: bool = True
    enable_transfer: bool = True
    transfer_min_amount: int = 10
    transfer_fee_rate: float = 0.05
    transfer_cooldown: int = 300

    @classmethod
    def from_dict(cls, config: Dict[str, Any]) -> "PluginConfig":
        return cls(
            base_points=config.get("base_points", 10),
            streak_bonus=config.get("streak_bonus", True),
            streak_bonus_rate=config.get("streak_bonus_rate", 0.1),
            max_streak_bonus=config.get("max_streak_bonus", 2.0),
            top_limit=config.get("top_limit", 10),
            reset_hour=config.get("reset_hour", 5),
            enable_rank=config.get("enable_rank", True),
            lucky_draw=config.get("lucky_draw", True),
            lucky_draw_points_max=config.get("lucky_draw_points_max", 50),
            enable_shop=config.get("enable_shop", True),
            enable_transfer=config.get("enable_transfer", True),
            transfer_min_amount=config.get("transfer_min_amount", 10),
            transfer_fee_rate=config.get("transfer_fee_rate", 0.05),
            transfer_cooldown=config.get("transfer_cooldown", 300),
        )

    def validate(self) -> bool:
        if self.base_points < 0:
            raise ValueError("基础积分不能为负数")
        if self.streak_bonus_rate < 0:
            raise ValueError("加成比例不能为负数")
        if self.max_streak_bonus < 1:
            raise ValueError("最大加成倍数不能小于1")
        if self.top_limit < 1:
            raise ValueError("排行榜数量至少为1")
        if not (0 <= self.reset_hour <= 23):
            raise ValueError("重置时间必须在0-23之间")
        if self.transfer_min_amount < 1:
            raise ValueError("最低转账金额至少为1")
        if not (0 <= self.transfer_fee_rate < 1):
            raise ValueError("手续费率必须在0-1之间")
        if self.transfer_cooldown < 0:
            raise ValueError("转账冷却时间不能为负数")
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "base_points": self.base_points,
            "streak_bonus": self.streak_bonus,
            "streak_bonus_rate": self.streak_bonus_rate,
            "max_streak_bonus": self.max_streak_bonus,
            "top_limit": self.top_limit,
            "reset_hour": self.reset_hour,
            "enable_rank": self.enable_rank,
            "lucky_draw": self.lucky_draw,
            "lucky_draw_points_max": self.lucky_draw_points_max,
            "enable_shop": self.enable_shop,
            "enable_transfer": self.enable_transfer,
            "transfer_min_amount": self.transfer_min_amount,
            "transfer_fee_rate": self.transfer_fee_rate,
            "transfer_cooldown": self.transfer_cooldown,
        }
