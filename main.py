"""
AstrBot 签到插件 

功能描述：
- 每日签到、连续签到、积分加成
- 积分排行榜
- 积分商店
- 道具使用系统
- 积分转账
- 抽奖系统

作者: HamLJYH
版本: 1.2.0
日期: 2026-07-08
"""

import os
import json
import random
import re
import functools
import fcntl
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, AsyncGenerator, Optional, Tuple

from astrbot.api.star import Context, Star
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api import logger


# 北京时间时区
TZ_BEIJING = timezone(timedelta(hours=8))

# 常量
MAX_NICKNAME_LENGTH = 15
SHOP_ITEMS = {
    "1": {"name": "🎁 神秘礼盒", "price": 50, "desc": "随机获得 10-100 积分"},
    "2": {"name": "🍀 幸运符", "price": 30, "desc": "下次签到积分翻倍（限1次）"},
    "3": {"name": "🔮 占卜卡", "price": 20, "desc": "查看今日运势"},
    "4": {"name": "💎 改名卡", "price": 100, "desc": "修改在排行榜中的显示名称"},
    "5": {"name": "🛡️ 补签卡", "price": 80, "desc": "补签昨天，保持连续签到"},
    "6": {"name": "🎲 抽奖券", "price": 20, "desc": "参与积分抽奖，大奖等你拿"},
}

FORTUNES = {
    "大吉": ["鸿运当头", "万事如意", "心想事成", "财运亨通"],
    "吉": ["顺风顺水", "好事将近", "贵人相助", "小有收获"],
    "中": ["平平淡淡", "稳如老狗", "无功无过", "维持现状"],
    "凶": ["小心为上", "诸事不宜", "低调行事", "注意身体"],
}

MILESTONES = [7, 30, 100, 365]

# 转账配置常量
TRANSFER_MIN_AMOUNT = 10
TRANSFER_FEE_RATE = 0.05
TRANSFER_COOLDOWN = 300  # 5分钟


@dataclass
class SignInConfig:
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
    def from_dict(cls, config: Dict[str, Any]) -> "SignInConfig":
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


def handle_errors(func):
    """统一错误处理装饰器"""
    @functools.wraps(func)
    async def wrapper(self, event: AstrMessageEvent, *args, **kwargs):
        try:
            async for result in func(self, event, *args, **kwargs):
                yield result
        except ValueError as e:
            logger.warning(f"[{func.__name__}] 参数错误: {e}")
            yield event.plain_result(f"❌ 参数错误: {str(e)}")
        except KeyError as e:
            logger.warning(f"[{func.__name__}] 数据缺失: {e}")
            yield event.plain_result("❌ 操作失败: 数据缺失")
        except PermissionError as e:
            logger.error(f"[{func.__name__}] 文件权限错误: {e}")
            yield event.plain_result("❌ 数据保存失败，请检查文件权限")
        except Exception as e:
            error_type = type(e).__name__
            logger.error(f"[{func.__name__}] 执行失败 [{error_type}]: {e}", exc_info=True)
            yield event.plain_result("❌ 操作失败，请稍后重试")
    return wrapper


class SignInPlugin(Star):
    """签到插件主类"""

    def __init__(self, context: Context, config: dict = None):
        """初始化插件

        Args:
            context: AstrBot 上下文
            config: 插件配置（由 AstrBot 根据 _conf_schema.json 自动传入）
        """
        super().__init__(context)

        # 加载插件配置（AstrBot 自动传入）
        self.plugin_config = self._parse_config(config or {})
        logger.info(f"[SignIn] 配置加载成功: base_points={self.plugin_config.base_points}, reset_hour={self.plugin_config.reset_hour}")

        # 数据持久化目录
        self.data_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "data", "plugin_data", "astrbot_plugin_signin"
        )
        os.makedirs(self.data_dir, exist_ok=True)
        self.data_file = os.path.join(self.data_dir, "signin_data.json")
        self.lock_file = os.path.join(self.data_dir, ".data.lock")

        # 确保锁文件存在
        open(self.lock_file, "a").close()

        self.user_data = self._load_data()

        logger.info("签到插件 v1.2.0 已加载")

    def _parse_config(self, config: dict) -> SignInConfig:
        """解析插件配置"""
        try:
            cfg = SignInConfig.from_dict(config)
            cfg.validate()
            logger.info(f"[SignIn] 使用 WebUI 配置: {config}")
            return cfg
        except Exception as e:
            logger.warning(f"[SignIn] 配置解析失败，使用默认配置: {e}")
            return SignInConfig()

    def _load_data(self) -> Dict[str, Any]:
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"加载签到数据失败: {e}")
                return {}
        return {}

    def _save_data(self):
        """保存数据（带文件锁保护）"""
        try:
            with open(self.lock_file, "r+") as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                try:
                    with open(self.data_file, "w", encoding="utf-8") as f:
                        json.dump(self.user_data, f, ensure_ascii=False, indent=2)
                finally:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        except IOError as e:
            logger.error(f"保存签到数据失败: {e}")
            raise PermissionError(f"数据保存失败: {e}")

    def _get_user_id(self, event: AstrMessageEvent) -> str:
        sender_id = event.get_sender_id()
        platform = event.get_platform_name()
        return f"{platform}:{sender_id}"

    def _get_user_name(self, event: AstrMessageEvent) -> str:
        return event.get_sender_name() or "匿名用户"

    def _get_today(self) -> str:
        now = datetime.now(TZ_BEIJING)
        if now.hour < self.plugin_config.reset_hour:
            now = now - timedelta(days=1)
        return now.strftime("%Y-%m-%d")

    def _get_yesterday(self) -> str:
        today = datetime.strptime(self._get_today(), "%Y-%m-%d").replace(tzinfo=TZ_BEIJING)
        yesterday = today - timedelta(days=1)
        return yesterday.strftime("%Y-%m-%d")

    def _ensure_user(self, user_id: str, user_name: str) -> Dict[str, Any]:
        if user_id not in self.user_data:
            self.user_data[user_id] = {
                "name": user_name,
                "total_points": 0,
                "total_signins": 0,
                "streak": 0,
                "last_signin": "",
                "history": [],
                "items": {},
                "buffs": {},
                "custom_name": None,
                "fortune_today": None,
                "daily_buy": {},
                "transfer_cooldown": 0,
                "transfer_history": [],
            }
        # 兼容性：为旧数据添加新字段
        user = self.user_data[user_id]
        for key, default in [
            ("daily_buy", {}),
            ("transfer_cooldown", 0),
            ("transfer_history", []),
            ("items", {}),
            ("buffs", {}),
        ]:
            if key not in user:
                user[key] = default
        return user

    def _get_display_name(self, user_id: str) -> str:
        user = self.user_data.get(user_id, {})
        return user.get("custom_name") or user.get("name", "匿名用户")

    def _calculate_points(self, streak: int, user: Dict[str, Any]) -> tuple:
        base_points = self.plugin_config.base_points
        streak_bonus = 0
        if self.plugin_config.streak_bonus and streak > 1:
            rate = self.plugin_config.streak_bonus_rate
            max_multiplier = self.plugin_config.max_streak_bonus
            multiplier = 1 + min((streak - 1) * rate, max_multiplier - 1)
            streak_bonus = int(base_points * (multiplier - 1))
        lucky_points = 0
        if self.plugin_config.lucky_draw:
            if random.random() < 0.2:
                lucky_points = random.randint(1, self.plugin_config.lucky_draw_points_max)
        total = base_points + streak_bonus + lucky_points
        buffs = user.get("buffs", {})
        if buffs.get("double_next", False):
            total *= 2
            buffs["double_next"] = False
            user["buffs"] = buffs
        return total, base_points, streak_bonus, lucky_points

    def _get_rank_emoji(self, rank: int) -> str:
        emojis = {1: "🥇", 2: "🥈", 3: "🥉"}
        return emojis.get(rank, f"#{rank}")

    def _check_daily_limit(self, user: Dict[str, Any], item_id: str) -> bool:
        today = self._get_today()
        daily_buy = user.get("daily_buy", {})
        last_buy_date = daily_buy.get(item_id, "")
        return last_buy_date != today

    def _record_daily_buy(self, user: Dict[str, Any], item_id: str):
        today = self._get_today()
        if "daily_buy" not in user:
            user["daily_buy"] = {}
        user["daily_buy"][item_id] = today

    def _is_admin(self, event: AstrMessageEvent) -> bool:
        sender_id = event.get_sender_id()
        try:
            cfg = self.context.get_config()
            if cfg and hasattr(cfg, "admins_id"):
                admins = cfg.admins_id
                if isinstance(admins, list):
                    return sender_id in admins
                elif isinstance(admins, str):
                    return sender_id == admins
        except Exception:
            pass
        return False

    def _deduct_points(self, user: Dict[str, Any], amount: int) -> bool:
        """安全扣除积分，返回是否成功"""
        if user["total_points"] < amount:
            return False
        user["total_points"] -= amount
        return True

    def _check_transfer_cooldown(self, user: Dict[str, Any]) -> Tuple[bool, int]:
        """检查转账冷却，返回 (是否在冷却中, 剩余秒数)"""
        last_transfer = user.get("transfer_cooldown", 0)
        cooldown = self.plugin_config.transfer_cooldown
        now = int(time.time())
        if now - last_transfer < cooldown:
            return True, cooldown - (now - last_transfer)
        return False, 0

    def _set_transfer_cooldown(self, user: Dict[str, Any]):
        """设置转账冷却时间"""
        user["transfer_cooldown"] = int(time.time())

    def _format_amount_change(self, before: int, after: int, label: str) -> str:
        """格式化金额变化显示"""
        change = after - before
        if change > 0:
            return f"{label}: {before} → {after} (+{change})"
        elif change < 0:
            return f"{label}: {before} → {after} ({change})"
        else:
            return f"{label}: {before} → {after} (无变化)"

    def _extract_target_qq(self, event: AstrMessageEvent) -> Optional[str]:
        """从消息中提取目标QQ号"""
        message_text = event.message_str or ""
        # 尝试匹配 @提及 或 纯数字QQ号
        # 优先检查消息中的at
        if hasattr(event.message_obj, "at") and event.message_obj.at:
            return str(event.message_obj.at[0])
        # 正则匹配QQ号（5-12位数字）
        match = re.search(r"(?:@|QQ|qq)?\s*(\d{5,12})", message_text)
        if match:
            return match.group(1)
        return None

    def _extract_amount(self, event: AstrMessageEvent) -> Optional[int]:
        """从消息中提取金额"""
        message_text = event.message_str or ""
        # 匹配数字（支持在消息末尾或中间）
        numbers = re.findall(r"\b(\d+)\b", message_text)
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

    @filter.command("签到")
    @handle_errors
    async def signin(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        user_id = self._get_user_id(event)
        user_name = self._get_user_name(event)
        today = self._get_today()
        user = self._ensure_user(user_id, user_name)
        user["name"] = user_name
        if user["last_signin"] == today:
            yield event.plain_result(
                f"⏰ {self._get_display_name(user_id)}，你今天已经签到过了！\n"
                f"📊 当前积分: {user['total_points']}\n"
                f"🔥 连续签到: {user['streak']} 天"
            )
            return
        yesterday = self._get_yesterday()
        if user["last_signin"] == yesterday:
            user["streak"] += 1
        else:
            if user["streak"] > 0:
                logger.info(f"用户 {user_name} 连续签到中断")
            user["streak"] = 1
        total_points, base, streak_bonus, lucky = self._calculate_points(user["streak"], user)
        user["total_points"] += total_points
        user["total_signins"] += 1
        user["last_signin"] = today
        user["history"].append({"date": today, "points": total_points, "streak": user["streak"]})
        # 限制历史记录长度
        if len(user["history"]) > 100:
            user["history"] = user["history"][-100:]
        user["fortune_today"] = None
        self._save_data()
        msg_parts = [
            f"✅ 签到成功！{self._get_display_name(user_id)}",
            "",
            f"📅 今日日期: {today}",
            f"⭐ 获得积分: +{total_points}",
            f"   ├ 基础积分: +{base}",
        ]
        if streak_bonus > 0:
            msg_parts.append(f"   ├ 连续加成: +{streak_bonus} (连续{user['streak']}天)")
        if lucky > 0:
            msg_parts.append(f"   └ 🎉 幸运奖励: +{lucky}")
        msg_parts.extend([
            "",
            f"💰 总积分: {user['total_points']}",
            f"🔥 连续签到: {user['streak']} 天",
            f"📈 累计签到: {user['total_signins']} 天"
        ])
        for m in MILESTONES:
            if user["streak"] == m:
                msg_parts.extend(["", f"🎊 恭喜！你已连续签到 {m} 天！"])
                break
        yield event.plain_result("\n".join(msg_parts))

    @filter.command("签到信息")
    @handle_errors
    async def signin_info(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        user_id = self._get_user_id(event)
        user_name = self._get_user_name(event)
        today = self._get_today()
        user = self._ensure_user(user_id, user_name)
        signed_today = user["last_signin"] == today
        all_users = sorted(self.user_data.items(), key=lambda x: x[1]["total_points"], reverse=True)
        rank = next((i + 1 for i, (uid, _) in enumerate(all_users) if uid == user_id), "-")
        current_month = today[:7]
        month_count = sum(1 for h in user["history"] if h["date"].startswith(current_month))
        items = user.get("items", {})
        item_str = ""
        if items:
            item_list = []
            for item_id, count in items.items():
                if count > 0:
                    item_name = SHOP_ITEMS.get(item_id, {}).get("name", f"道具{item_id}")
                    item_list.append(f"{item_name} x{count}")
            if item_list:
                item_str = "\n🎒 背包: " + ", ".join(item_list)
        status = "✅ 已签到" if signed_today else "❌ 未签到"
        msg = (
            f"📋 {self._get_display_name(user_id)} 的签到信息\n\n"
            f"📊 签到状态: {status}\n"
            f"💰 总积分: {user['total_points']}\n"
            f"🏆 积分排名: 第 {rank} 名\n"
            f"🔥 连续签到: {user['streak']} 天\n"
            f"📈 累计签到: {user['total_signins']} 天\n"
            f"📅 本月签到: {month_count} 天\n"
            f"🗓️  最后签到: {user['last_signin'] or '无记录'}"
            f"{item_str}"
        )
        yield event.plain_result(msg)

    @filter.command("签到排行")
    @handle_errors
    async def signin_rank(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        if not self.plugin_config.enable_rank:
            yield event.plain_result("排行榜功能已关闭。")
            return
        if not self.user_data:
            yield event.plain_result("暂无签到数据，快来成为第一个签到的人吧！")
            return
        limit = self.plugin_config.top_limit
        sorted_users = sorted(self.user_data.items(), key=lambda x: x[1]["total_points"], reverse=True)[:limit]
        msg_lines = ["🏆 签到积分排行榜 🏆", ""]
        for i, (user_id, user) in enumerate(sorted_users, 1):
            emoji = self._get_rank_emoji(i)
            name = self._get_display_name(user_id)[:10]
            msg_lines.append(f"{emoji} {name:<12} 积分: {user['total_points']:>6}  连续: {user['streak']:>3}天")
        msg_lines.extend(["", f"📊 共 {len(self.user_data)} 位用户参与签到"])
        yield event.plain_result("\n".join(msg_lines))

    @filter.command("商店")
    @handle_errors
    async def shop(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        if not self.plugin_config.enable_shop:
            yield event.plain_result("积分商店功能已关闭。")
            return
        msg_lines = ["🏪 积分商店 🏪", ""]
        limit_items = {"1": "【每日限购1个】", "6": "【每日限购1个】"}
        for item_id, item in SHOP_ITEMS.items():
            limit_tag = limit_items.get(item_id, "")
            msg_lines.append(f"[{item_id}] {item['name']} {limit_tag}\n    💰 价格: {item['price']} 积分\n    📖 {item['desc']}")
        msg_lines.extend(["", "使用 /购买 <编号> 来购买商品"])
        yield event.plain_result("\n".join(msg_lines))

    @filter.command("购买")
    @handle_errors
    async def buy(self, event: AstrMessageEvent, item_id: int = None) -> AsyncGenerator[Any, None]:
        if not self.plugin_config.enable_shop:
            yield event.plain_result("积分商店功能已关闭。")
            return
        user_id = self._get_user_id(event)
        user_name = self._get_user_name(event)
        user = self._ensure_user(user_id, user_name)

        # 如果 AstrBot 参数解析失败，尝试正则回退
        if item_id is None:
            message_text = event.message_str or ""
            match = re.search(r"/购买\s+(\d+)", message_text)
            if match:
                item_id = int(match.group(1))

        if item_id is None:
            yield event.plain_result("❌ 请指定商品编号，如 /购买 1")
            return

        item_id_str = str(item_id)
        item = SHOP_ITEMS.get(item_id_str)
        if not item:
            yield event.plain_result("❌ 商品编号不存在，请使用 /商店 查看商品列表。")
            return

        limit_items = {"1": "神秘礼盒", "6": "抽奖券"}
        if item_id_str in limit_items:
            if not self._check_daily_limit(user, item_id_str):
                yield event.plain_result(
                    f"🚫 今日已购买过 {limit_items[item_id_str]} 了！\n"
                    f"每天限购1个，凌晨{self.plugin_config.reset_hour}点刷新。"
                )
                return

        # 使用安全扣除
        if not self._deduct_points(user, item["price"]):
            yield event.plain_result(
                f"❌ 积分不足！\n商品: {item['name']} (需要 {item['price']} 积分)\n"
                f"你的积分: {user['total_points']}"
            )
            return

        if item_id_str in limit_items:
            self._record_daily_buy(user, item_id_str)

        result_msg = f"✅ 购买成功！\n\n{item['name']}\n"
        if item_id_str == "1":
            reward = random.randint(10, 100)
            user["total_points"] += reward
            result_msg += f"🎁 打开礼盒获得 {reward} 积分！"
        elif item_id_str == "2":
            buffs = user.get("buffs", {})
            buffs["double_next"] = True
            user["buffs"] = buffs
            result_msg += "🍀 下次签到积分翻倍已生效！"
        elif item_id_str == "3":
            result_msg += "🔮 请使用 /占卜 查看今日运势"
            items = user.get("items", {})
            items["3"] = items.get("3", 0) + 1
            user["items"] = items
        elif item_id_str == "4":
            result_msg += "💎 请使用 /改名 <新名称> 修改显示名"
            items = user.get("items", {})
            items["4"] = items.get("4", 0) + 1
            user["items"] = items
        elif item_id_str == "5":
            result_msg += "🛡️ 请使用 /补签 来补签昨天"
            items = user.get("items", {})
            items["5"] = items.get("5", 0) + 1
            user["items"] = items
        elif item_id_str == "6":
            result_msg += "🎲 请使用 /抽奖 参与积分抽奖"
            items = user.get("items", {})
            items["6"] = items.get("6", 0) + 1
            user["items"] = items

        self._save_data()
        result_msg += f"\n\n💰 剩余积分: {user['total_points']}"
        yield event.plain_result(result_msg)

    @filter.command("占卜")
    @handle_errors
    async def fortune(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        user_id = self._get_user_id(event)
        user_name = self._get_user_name(event)
        user = self._ensure_user(user_id, user_name)
        items = user.get("items", {})
        if items.get("3", 0) <= 0:
            yield event.plain_result("🔮 你没有占卜卡，去 /商店 购买一张吧！")
            return
        items["3"] -= 1
        if items["3"] <= 0:
            del items["3"]
        user["items"] = items
        today = self._get_today()
        if user.get("fortune_today") and user["fortune_today"].get("date") == today:
            fortune = user["fortune_today"]
        else:
            level = random.choices(["大吉", "吉", "中", "凶"], weights=[15, 35, 40, 10])[0]
            desc = random.choice(FORTUNES[level])
            fortune = {
                "date": today,
                "level": level,
                "desc": desc,
                "lucky_num": random.randint(1, 99),
                "lucky_color": random.choice(["红", "黄", "蓝", "绿", "紫", "黑", "白"]),
                "lucky_dir": random.choice(["东", "南", "西", "北", "东南", "西北", "东北", "西南"])
            }
            user["fortune_today"] = fortune
        self._save_data()
        emojis = {"大吉": "🌟", "吉": "✨", "中": "☁️", "凶": "⚡"}
        msg = (
            f"🔮 {self._get_display_name(user_id)} 的今日运势\n\n"
            f"{emojis[fortune['level']]} 运势: {fortune['level']} - {fortune['desc']}\n"
            f"🔢 幸运数字: {fortune['lucky_num']}\n"
            f"🎨 幸运色: {fortune['lucky_color']}\n"
            f"🧭 幸运方位: {fortune['lucky_dir']}"
        )
        yield event.plain_result(msg)

    @filter.command("改名")
    @handle_errors
    async def rename(self, event: AstrMessageEvent, new_name: str = None) -> AsyncGenerator[Any, None]:
        user_id = self._get_user_id(event)
        user_name = self._get_user_name(event)
        user = self._ensure_user(user_id, user_name)

        # 如果 AstrBot 参数解析失败，尝试正则回退
        if new_name is None:
            message_text = event.message_str or ""
            match = re.search(r"/改名\s+(.+)", message_text)
            if match:
                new_name = match.group(1).strip()

        items = user.get("items", {})
        if items.get("4", 0) <= 0:
            yield event.plain_result("💎 你没有改名卡，去 /商店 购买一张吧！")
            return
        if not new_name or len(new_name) > MAX_NICKNAME_LENGTH:
            yield event.plain_result(f"❌ 名称不能为空，且不能超过{MAX_NICKNAME_LENGTH}个字符。")
            return
        items["4"] -= 1
        if items["4"] <= 0:
            del items["4"]
        user["items"] = items
        old_name = user.get("custom_name") or user["name"]
        user["custom_name"] = new_name
        self._save_data()
        yield event.plain_result(f"💎 改名成功！\n{old_name} → {new_name}\n排行榜中已更新显示。")

    @filter.command("补签")
    @handle_errors
    async def makeup_sign(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        user_id = self._get_user_id(event)
        user_name = self._get_user_name(event)
        user = self._ensure_user(user_id, user_name)
        items = user.get("items", {})
        if items.get("5", 0) <= 0:
            yield event.plain_result("🛡️ 你没有补签卡，去 /商店 购买一张吧！")
            return
        today = self._get_today()
        yesterday = self._get_yesterday()
        if user["last_signin"] == today:
            yield event.plain_result("✅ 你今天已经签到了，不需要补签！")
            return
        if user["last_signin"] == yesterday:
            yield event.plain_result("✅ 你昨天已经签到了，不需要补签！")
            return

        items["5"] -= 1
        if items["5"] <= 0:
            del items["5"]
        user["items"] = items

        # 修复：更严谨的补签逻辑
        # 如果上次签到是前天，则连续天数+1；否则重置为1（因为补签的是昨天）
        before_yesterday_dt = datetime.strptime(yesterday, "%Y-%m-%d").replace(tzinfo=TZ_BEIJING) - timedelta(days=1)
        before_yesterday = before_yesterday_dt.strftime("%Y-%m-%d")

        if user.get("last_signin") == before_yesterday:
            user["streak"] = user.get("streak", 0) + 1
        elif user.get("last_signin") == "":
            # 从未签到过，补签后连续为1
            user["streak"] = 1
        else:
            # 断签超过一天，补签昨天后连续为1（因为前天没签）
            user["streak"] = 1

        user["last_signin"] = yesterday
        user["total_signins"] += 1
        user["history"].append({"date": yesterday, "points": 0, "streak": user["streak"], "makeup": True})
        if len(user["history"]) > 100:
            user["history"] = user["history"][-100:]
        self._save_data()
        yield event.plain_result(
            f"🛡️ 补签成功！\n📅 补签日期: {yesterday}\n"
            f"🔥 当前连续: {user['streak']} 天\n"
            f"⚠️ 补签不获得积分，仅保持连续天数"
        )

    @filter.command("抽奖")
    @handle_errors
    async def lottery(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        user_id = self._get_user_id(event)
        user_name = self._get_user_name(event)
        user = self._ensure_user(user_id, user_name)
        items = user.get("items", {})
        if items.get("6", 0) <= 0:
            yield event.plain_result("🎲 你没有抽奖券，去 /商店 购买一张吧！")
            return
        items["6"] -= 1
        if items["6"] <= 0:
            del items["6"]
        user["items"] = items
        prizes = [
            ("💸 谢谢参与", 0, 0.25),
            ("🪙 小奖", random.randint(5, 20), 0.30),
            ("💰 中奖", random.randint(30, 80), 0.20),
            ("💎 大奖", random.randint(100, 200), 0.04),
            ("👑 特等奖", random.randint(300, 500), 0.01),
            ("⚡ 小惩罚", -random.randint(5, 15), 0.12),
            ("💀 大惩罚", -random.randint(20, 50), 0.08),
        ]
        r = random.random()
        cumulative = 0
        prize = prizes[0]
        for p in prizes:
            cumulative += p[2]
            if r <= cumulative:
                prize = p
                break
        name, points, _ = prize
        old_points = user["total_points"]
        user["total_points"] += points
        # 确保积分不会为负
        if user["total_points"] < 0:
            user["total_points"] = 0
        self._save_data()
        msg_lines = ["🎲 抽奖结果", ""]
        if points > 0:
            msg_lines.append(f"🎁 {name} +{points} 积分！")
        elif points < 0:
            actual_deducted = old_points - user["total_points"]
            msg_lines.append(f"💥 {name} -{actual_deducted} 积分！")
            if user["total_points"] == 0:
                msg_lines.append("😱 积分被扣光了！")
        else:
            msg_lines.append(f"🎁 {name}")
        msg_lines.append("")
        msg_lines.append(f"💰 当前积分: {user['total_points']}")
        yield event.plain_result("\n".join(msg_lines))

    @filter.command("转账")
    @handle_errors
    async def transfer(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """转账给其他用户（通过QQ号）"""
        if not self.plugin_config.enable_transfer:
            yield event.plain_result("💸 转账功能已关闭。")
            return

        user_id = self._get_user_id(event)
        user_name = self._get_user_name(event)
        sender = self._ensure_user(user_id, user_name)

        # 解析目标QQ号和金额
        target_qq = self._extract_target_qq(event)
        amount = self._extract_amount(event)

        if not target_qq:
            yield event.plain_result(
                "❌ 请指定转账目标。\n"
                "用法: /转账 @用户 积分\n"
                "或: /转账 QQ号 积分"
            )
            return

        if not amount or amount <= 0:
            yield event.plain_result("❌ 请指定有效的转账金额。用法: /转账 QQ号 积分")
            return

        # 构建目标用户的完整ID（假设同平台）
        platform = event.get_platform_name()
        target_id = f"{platform}:{target_qq}"

        if target_id == user_id:
            yield event.plain_result("❌ 不能转账给自己。")
            return

        # 检查最低转账金额
        min_amount = self.plugin_config.transfer_min_amount
        if amount < min_amount:
            yield event.plain_result(f"❌ 最低转账金额为 {min_amount} 积分。")
            return

        # 检查冷却
        in_cooldown, remain = self._check_transfer_cooldown(sender)
        if in_cooldown:
            mins = remain // 60
            secs = remain % 60
            yield event.plain_result(f"⏰ 转账冷却中，剩余 {mins}分{secs}秒。")
            return

        # 计算手续费
        fee_rate = self.plugin_config.transfer_fee_rate
        fee = int(amount * fee_rate)
        total_cost = amount + fee

        if sender["total_points"] < total_cost:
            yield event.plain_result(
                f"❌ 积分不足。\n"
                f"转账积分: {amount}\n"
                "手续费: {fee} ({int(fee_rate * 100)}%)\n"
                f"总计需要: {total_cost} 积分\n"
                f"你的积分: {sender['total_points']}"
            )
            return

        # 确保目标用户存在
        target = self._ensure_user(target_id, f"用户{target_qq}")

        # 执行转账
        sender_before = sender["total_points"]
        target_before = target["total_points"]
        sender["total_points"] -= total_cost
        target["total_points"] += amount
        self._set_transfer_cooldown(sender)

        # 记录转账历史
        timestamp = int(time.time())
        sender_transfer = {
            "type": "send",
            "target": target_qq,
            "amount": amount,
            "fee": fee,
            "timestamp": timestamp
        }
        target_transfer = {
            "type": "receive",
            "target": event.get_sender_id(),
            "amount": amount,
            "fee": 0,
            "timestamp": timestamp
        }

        sender.setdefault("transfer_history", []).insert(0, sender_transfer)
        target.setdefault("transfer_history", []).insert(0, target_transfer)

        # 保留最近20条记录
        sender["transfer_history"] = sender["transfer_history"][:20]
        target["transfer_history"] = target["transfer_history"][:20]

        self._save_data()

        sender_name = self._get_display_name(user_id)
        target_name = self._get_display_name(target_id)

        yield event.plain_result(
            f"✅ 转账成功！\n"
            f"💸 从 {sender_name} 转给 {target_name}\n"
            f"💰 转账积分: {amount}\n"
            f"💵 手续费: {fee} 积分 ({int(fee_rate * 100)}%)\n"
            f"{self._format_amount_change(sender_before, sender['total_points'], '📊 你的余额')}\n"
            f"{self._format_amount_change(target_before, target['total_points'], '📊 对方余额')}"
        )

    @filter.command("转账记录")
    @handle_errors
    async def transfer_history(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """查看转账记录"""
        user_id = self._get_user_id(event)
        user_name = self._get_user_name(event)
        user = self._ensure_user(user_id, user_name)
        history = user.get("transfer_history", [])
        if not history:
            yield event.plain_result("📭 暂无转账记录。")
            return
        msg_lines = [f"📋 {self._get_display_name(user_id)} 的转账记录", ""]
        for i, record in enumerate(history[:10], 1):
            ts = record.get("timestamp", 0)
            date_str = datetime.fromtimestamp(ts, TZ_BEIJING).strftime("%m-%d %H:%M") if ts else "未知时间"
            if record["type"] == "send":
                msg_lines.append(
                    f"{i}. 📤 {date_str} 转给 {record['target']} {record['amount']}积分"
                    f" (手续费{record.get('fee', 0)})"
                )
            else:
                msg_lines.append(
                    f"{i}. 📥 {date_str} 来自 {record['target']} {record['amount']}积分"
                )
        yield event.plain_result("\n".join(msg_lines))

    @filter.command("重置数据")
    @filter.permission_type(filter.PermissionType.ADMIN)  # ✅ 框架自动处理权限
    @handle_errors
    async def reset_data(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        if not self.user_data:
            yield event.plain_result("📭 当前没有任何签到数据。")
            return
        user_count = len(self.user_data)
        self.user_data.clear()
        self._save_data()
        yield event.plain_result(
            f"🗑️ 数据重置成功！\n已清除 {user_count} 位用户的签到记录。\n"
            f"所有积分、连续天数、道具已归零。"
        )

    @filter.command("签到帮助")
    @handle_errors
    async def signin_help(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        msg = (
            "📖 签到插件 v1.2.0 使用帮助\n\n"
            "📝 签到指令:\n"
            "  /签到          - 每日签到，获取积分\n"
            "  /签到信息      - 查看个人签到详情\n"
            "  /签到排行      - 查看积分排行榜\n\n"
            "🛒 商店指令:\n"
            "  /商店          - 查看积分商店商品\n"
            "  /购买 <编号>   - 购买商品（如 /购买 1）\n\n"
            "🎮 道具指令:\n"
            "  /占卜          - 使用占卜卡查看今日运势\n"
            "  /改名 <名称>   - 使用改名卡修改显示名\n"
            "  /补签          - 使用补签卡补签昨天\n"
            "  /抽奖          - 使用抽奖券参与积分抽奖\n\n"
            "💸 转账指令:\n"
            "  /转账 QQ号 金额  - 转账积分给其他用户\n"
            "  /转账记录       - 查看转账历史\n\n"
            "🔧 管理指令:\n"
            "  /重置数据        - 清除所有签到数据（管理员）\n\n"
            "✨ 功能说明:\n"
            "  • 每日签到可获得基础积分 + 连续加成 + 幸运奖励\n"
            "  • 积分可在商店购买道具\n"
            "  • 神秘礼盒和抽奖券每日限购1个\n"
            "  • 抽奖有概率触发惩罚（扣分，但不会扣到负数）\n"
            "  • 连续签到加成有上限，断签会重置天数\n"
            "  • 转账有手续费和冷却时间\n"
            "  • 数据自动保存，重启不丢失"
        )
        yield event.plain_result(msg)

    async def terminate(self):
        self._save_data()
        logger.info("签到插件已卸载，数据已保存")