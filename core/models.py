"""
AstrBot 签到插件 - 数据模型模块

版本: 2.0.0
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, Optional, List

from .constants import TZ_BEIJING


@dataclass
class UserData:
    """用户数据模型"""
    user_id: str
    name: str = "匿名用户"
    custom_name: Optional[str] = None
    total_points: int = 0
    total_signins: int = 0
    streak: int = 0
    last_signin: str = ""
    fortune_today: Optional[Dict[str, Any]] = None
    created_at: str = field(default_factory=lambda: datetime.now(TZ_BEIJING).isoformat())

    @property
    def display_name(self) -> str:
        """获取显示名称"""
        return self.custom_name or self.name or "匿名用户"

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "user_id": self.user_id,
            "name": self.name,
            "custom_name": self.custom_name,
            "total_points": self.total_points,
            "total_signins": self.total_signins,
            "streak": self.streak,
            "last_signin": self.last_signin,
            "fortune_today": self.fortune_today,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserData":
        """从字典创建"""
        return cls(
            user_id=data.get("user_id", ""),
            name=data.get("name", "匿名用户"),
            custom_name=data.get("custom_name"),
            total_points=data.get("total_points", 0),
            total_signins=data.get("total_signins", 0),
            streak=data.get("streak", 0),
            last_signin=data.get("last_signin", ""),
            fortune_today=data.get("fortune_today"),
            created_at=data.get("created_at", datetime.now(TZ_BEIJING).isoformat()),
        )


@dataclass
class SigninRecord:
    """签到记录模型"""
    id: Optional[int] = None
    user_id: str = ""
    signin_date: str = ""
    points_earned: int = 0
    is_continuous: bool = False
    is_makeup: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(TZ_BEIJING).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "signin_date": self.signin_date,
            "points_earned": self.points_earned,
            "is_continuous": self.is_continuous,
            "is_makeup": self.is_makeup,
            "created_at": self.created_at,
        }


@dataclass
class InventoryItem:
    """背包道具模型"""
    id: Optional[int] = None
    user_id: str = ""
    item_id: str = ""
    quantity: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "item_id": self.item_id,
            "quantity": self.quantity,
        }


@dataclass
class TransferRecord:
    """转账记录模型"""
    id: Optional[int] = None
    from_user: str = ""
    to_user: str = ""
    amount: int = 0
    fee: int = 0
    transfer_time: str = field(default_factory=lambda: datetime.now(TZ_BEIJING).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "from_user": self.from_user,
            "to_user": self.to_user,
            "amount": self.amount,
            "fee": self.fee,
            "transfer_time": self.transfer_time,
        }


@dataclass
class OperationResult:
    """操作结果模型"""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "message": self.message,
            "data": self.data,
        }


@dataclass
class SigninResult:
    """签到结果模型"""
    success: bool
    total_points: int = 0
    base_points: int = 0
    streak_bonus: int = 0
    lucky_points: int = 0
    streak: int = 0
    total_signins: int = 0
    is_first_signin: bool = False
    milestone: Optional[int] = None
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "total_points": self.total_points,
            "base_points": self.base_points,
            "streak_bonus": self.streak_bonus,
            "lucky_points": self.lucky_points,
            "streak": self.streak,
            "total_signins": self.total_signins,
            "is_first_signin": self.is_first_signin,
            "milestone": self.milestone,
            "message": self.message,
        }


@dataclass
class GlobalStats:
    """全局统计数据"""
    total_users: int = 0
    today_signin: int = 0
    total_points: int = 0
    active_7d: int = 0
    active_30d: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_users": self.total_users,
            "today_signin": self.today_signin,
            "total_points": self.total_points,
            "active_7d": self.active_7d,
            "active_30d": self.active_30d,
        }
