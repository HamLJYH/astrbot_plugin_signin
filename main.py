"""
AstrBot 签到插件 v1.1.2

功能描述：
- 每日签到、连续签到、积分加成
- 积分排行榜
- 积分商店（神秘礼盒、幸运符、占卜卡、改名卡、补签卡、抽奖券）
- 道具使用系统
- 积分转账（通过QQ号）

作者: HamLJYH
版本: 1.1.2
日期: 2026-07-06
"""

import os
import json
import random
import re
import functools
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, AsyncGenerator

# 北京时间时区
TZ_BEIJING = timezone(timedelta(hours=8))

from astrbot.api.star import Context, Star
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api import logger


# ==================== 常量定义 ====================

MAX_NICKNAME_LENGTH = 15
SHOP_ITEMS = {
    "1": {"name": "🎁 神秘礼盒", "price": 50, "desc": "随机获得 10-100 积分"},
    "2": {"name": "🍀 幸运符", "price": 30, "desc": "下次签到积分翻倍（限1次）"},
    "3": {"name": "🔮 占卜卡", "price": 20, "desc": "查看今日运势"},
    "4": {"name": "💎 改名卡", "price": 100, "desc": "修改在排行榜中的显示名称"},
    "5": {"name": "🛡️  补签卡", "price": 80, "desc": "补签昨天，保持连续签到"},
    "6": {"name": "🎲 抽奖券", "price": 20, "desc": "参与积分抽奖，大奖等你拿"},
}

FORTUNES = {
    "大吉": ["鸿运当头", "万事如意", "心想事成", "财运亨通"],
    "吉": ["顺风顺水", "好事将近", "贵人相助", "小有收获"],
    "中": ["平平淡淡", "稳如老狗", "无功无过", "维持现状"],
    "凶": ["小心为上", "诸事不宜", "低调行事", "注意身体"],
}

MILESTONES = [7, 30, 100, 365]


# ==================== 配置模型 ====================

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
    lucky_draw_max: int = 50
    enable_shop: bool = True
    enable_transfer: bool = True

    @classmethod
    def from_dict(cls, config: Dict[str, Any]) -> "SignInConfig":
        """从字典创建配置实例"""
        return cls(
            base_points=config.get("base_points", 10),
            streak_bonus=config.get("streak_bonus", True),
            streak_bonus_rate=config.get("streak_bonus_rate", 0.1),
            max_streak_bonus=config.get("max_streak_bonus", 2.0),
            top_limit=config.get("top_limit", 10),
            reset_hour=config.get("reset_hour", 5),
            enable_rank=config.get("enable_rank", True),
            lucky_draw=config.get("lucky_draw", True),
            lucky_draw_max=config.get("lucky_draw_max", 50),
            enable_shop=config.get("enable_shop", True),
            enable_transfer=config.get("enable_transfer", True),
        )

    def validate(self) -> bool:
        """验证配置有效性"""
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
        return True


# ==================== 错误处理装饰器 ====================

def handle_errors(func):
    """统一错误处理装饰器

    捕获并处理函数执行过程中的各种异常，向用户返回友好的错误提示。
    """
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
            yield event.plain_result(f"❌ 操作失败: 数据缺失")
        except Exception as e:
            error_type = type(e).__name__
            logger.error(f"[{func.__name__}] 执行失败 [{error_type}]: {e}", exc_info=True)
            yield event.plain_result("❌ 操作失败，请稍后重试或联系管理员")
    return wrapper


# ==================== 插件主类 ====================

class SignInPlugin(Star):
    """签到插件主类"""

    def __init__(self, context: Context):
        super().__init__(context)

        # 数据持久化目录
        self.data_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "data", "plugin_data", "astrbot_plugin_signin"
        )
        os.makedirs(self.data_dir, exist_ok=True)

        self.data_file = os.path.join(self.data_dir, "signin_data.json")
        self.user_data = self._load_data()

        # 加载并验证配置
        self.config = self._load_config()

        logger.info("签到插件 v3.0 已加载")

    def _load_config(self) -> SignInConfig:
        """安全加载插件配置"""
        default_config = SignInConfig()
        try:
            cfg = self.context.get_config()
            if cfg is None:
                return default_config

            plugin_conf = getattr(cfg, "plugin_config", {})
            if isinstance(plugin_conf, dict):
                conf = plugin_conf.get("astrbot_plugin_signin", {})
                if isinstance(conf, dict):
                    merged = SignInConfig.from_dict(conf)
                    merged.validate()
                    return merged
        except Exception as e:
            logger.warning(f"加载配置失败，使用默认配置: {e}")

        return default_config

    def _load_data(self) -> Dict[str, Any]:
        """加载签到数据"""
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"加载签到数据失败: {e}")
                return {}
        return {}

    def _save_data(self):
        """保存签到数据"""
        try:
            with open(self.data_file, "w", encoding="utf-8") as f:
                json.dump(self.user_data, f, ensure_ascii=False, indent=2)
        except IOError as e:
            logger.error(f"保存签到数据失败: {e}")

    def _get_user_id(self, event: AstrMessageEvent) -> str:
        """获取用户唯一标识"""
        sender_id = event.get_sender_id()
        platform = event.get_platform_name()
        return f"{platform}:{sender_id}"

    def _get_user_name(self, event: AstrMessageEvent) -> str:
        """获取用户显示名称"""
        return event.get_sender_name() or "匿名用户"

    def _get_today(self) -> str:
        """获取当前日期（考虑重置时间，使用北京时间）"""
        now = datetime.now(TZ_BEIJING)
        if now.hour < self.config.reset_hour:
            now = now - timedelta(days=1)
        return now.strftime("%Y-%m-%d")

    def _get_yesterday(self) -> str:
        """获取昨天日期（使用北京时间）"""
        today = datetime.strptime(self._get_today(), "%Y-%m-%d").replace(tzinfo=TZ_BEIJING)
        yesterday = today - timedelta(days=1)
        return yesterday.strftime("%Y-%m-%d")

    def _ensure_user(self, user_id: str, user_name: str) -> Dict[str, Any]:
        """确保用户数据存在，返回用户数据"""
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
            }
        return self.user_data[user_id]

    def _get_display_name(self, user_id: str) -> str:
        """获取用户显示名称"""
        user = self.user_data.get(user_id, {})
        return user.get("custom_name") or user.get("name", "匿名用户")

    def _calculate_points(self, streak: int, user: Dict[str, Any]) -> tuple:
        """计算签到积分"""
        base_points = self.config.base_points

        # 连续签到加成
        streak_bonus = 0
        if self.config.streak_bonus and streak > 1:
            rate = self.config.streak_bonus_rate
            max_multiplier = self.config.max_streak_bonus
            multiplier = 1 + min((streak - 1) * rate, max_multiplier - 1)
            streak_bonus = int(base_points * (multiplier - 1))

        # 幸运抽奖
        lucky_points = 0
        if self.config.lucky_draw:
            if random.random() < 0.2:
                lucky_points = random.randint(1, self.config.lucky_draw_max)

        total = base_points + streak_bonus + lucky_points

        # buff：积分翻倍
        buffs = user.get("buffs", {})
        if buffs.get("double_next", False):
            total *= 2
            buffs["double_next"] = False
            user["buffs"] = buffs

        return total, base_points, streak_bonus, lucky_points

    def _get_rank_emoji(self, rank: int) -> str:
        """获取排名对应的emoji"""
        emojis = {1: "🥇", 2: "🥈", 3: "🥉"}
        return emojis.get(rank, f"#{rank}")

    # ==================== 签到指令 ====================

    @filter.command("签到")
    @handle_errors
    async def signin(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """每日签到"""
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
                logger.info(f"用户 {user_name} 连续签到中断，之前 {user['streak']} 天")
            user["streak"] = 1

        total_points, base, streak_bonus, lucky = self._calculate_points(
            user["streak"], user
        )

        user["total_points"] += total_points
        user["total_signins"] += 1
        user["last_signin"] = today
        user["history"].append({
            "date": today,
            "points": total_points,
            "streak": user["streak"]
        })

        # 限制历史记录
        if len(user["history"]) > 100:
            user["history"] = user["history"][-100:]

        user["fortune_today"] = None
        self._save_data()

        msg_parts = [
            f"✅ 签到成功！{self._get_display_name(user_id)}",
            f"",
            f"📅 今日日期: {today}",
            f"⭐ 获得积分: +{total_points}",
            f"   ├ 基础积分: +{base}",
        ]

        if streak_bonus > 0:
            msg_parts.append(f"   ├ 连续加成: +{streak_bonus} (连续{user['streak']}天)")

        if lucky > 0:
            msg_parts.append(f"   └ 🎉 幸运奖励: +{lucky}")

        msg_parts.extend([
            f"",
            f"💰 总积分: {user['total_points']}",
            f"🔥 连续签到: {user['streak']} 天",
            f"📈 累计签到: {user['total_signins']} 天"
        ])

        for m in MILESTONES:
            if user["streak"] == m:
                msg_parts.append(f"")
                msg_parts.append(f"🎊 恭喜！你已连续签到 {m} 天！")
                break

        yield event.plain_result("\n".join(msg_parts))

    @filter.command("签到信息")
    @handle_errors
    async def signin_info(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """查看个人签到信息"""
        user_id = self._get_user_id(event)
        user_name = self._get_user_name(event)
        today = self._get_today()

        user = self._ensure_user(user_id, user_name)
        signed_today = user["last_signin"] == today

        all_users = sorted(
            self.user_data.items(),
            key=lambda x: x[1]["total_points"],
            reverse=True
        )
        rank = next((i + 1 for i, (uid, _) in enumerate(all_users) if uid == user_id), "-")

        current_month = today[:7]
        month_count = sum(1 for h in user["history"] if h["date"].startswith(current_month))

        items = user.get("items", {})
        item_str = ""
        if items:
            item_list = []
            for item_id, count in items.items():
                item_name = SHOP_ITEMS.get(item_id, {}).get("name", f"道具{item_id}")
                item_list.append(f"{item_name} x{count}")
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
        """查看积分排行榜"""
        if not self.config.enable_rank:
            yield event.plain_result("排行榜功能已关闭。")
            return

        if not self.user_data:
            yield event.plain_result("暂无签到数据，快来成为第一个签到的人吧！")
            return

        limit = self.config.top_limit

        sorted_users = sorted(
            self.user_data.items(),
            key=lambda x: x[1]["total_points"],
            reverse=True
        )[:limit]

        msg_lines = ["🏆 签到积分排行榜 🏆", ""]

        for i, (user_id, user) in enumerate(sorted_users, 1):
            emoji = self._get_rank_emoji(i)
            name = self._get_display_name(user_id)[:10]
            msg_lines.append(
                f"{emoji} {name:<12} 积分: {user['total_points']:>6}  连续: {user['streak']:>3}天"
            )

        msg_lines.append("")
        msg_lines.append(f"📊 共 {len(self.user_data)} 位用户参与签到")

        yield event.plain_result("\n".join(msg_lines))

    # ==================== 积分商店 ====================

    @filter.command("商店")
    @handle_errors
    async def shop(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """查看积分商店"""
        if not self.config.enable_shop:
            yield event.plain_result("积分商店功能已关闭。")
            return

        msg_lines = ["🏪 积分商店 🏪", ""]

        for item_id, item in SHOP_ITEMS.items():
            msg_lines.append(
                f"[{item_id}] {item['name']}\n"
                f"    💰 价格: {item['price']} 积分\n"
                f"    📖 {item['desc']}"
            )

        msg_lines.append("")
        msg_lines.append("使用 /购买 <编号> 来购买商品")

        yield event.plain_result("\n".join(msg_lines))

    @filter.command("购买")
    @handle_errors
    async def buy(self, event: AstrMessageEvent, item_id: str = None) -> AsyncGenerator[Any, None]:
        """购买商店商品

        用法: /购买 编号
        例如: /购买 1
        """
        if not self.config.enable_shop:
            yield event.plain_result("积分商店功能已关闭。")
            return

        user_id = self._get_user_id(event)
        user_name = self._get_user_name(event)

        user = self._ensure_user(user_id, user_name)

        # 从消息内容解析参数（支持 /购买1 /购买 1 /购买 [1] 等格式）
        message_text = event.message_str or ""
        # 匹配 /购买 后面跟着数字，支持可选空格和方括号
        match = re.search(r"/购买\s*\[?(\d+)\]?", message_text)
        if match:
            item_id = match.group(1)

        if not item_id:
            yield event.plain_result("❌ 请指定商品编号，如 /购买 1")
            return

        item = SHOP_ITEMS.get(item_id)
        if not item:
            yield event.plain_result("❌ 商品编号不存在，请使用 /商店 查看商品列表。")
            return

        if user["total_points"] < item["price"]:
            yield event.plain_result(
                f"❌ 积分不足！\n"
                f"商品: {item['name']} (需要 {item['price']} 积分)\n"
                f"你的积分: {user['total_points']}"
            )
            return

        user["total_points"] -= item["price"]
        result_msg = f"✅ 购买成功！\n\n{item['name']}\n"

        if item_id == "1":  # 神秘礼盒
            reward = random.randint(10, 100)
            user["total_points"] += reward
            result_msg += f"🎁 打开礼盒获得 {reward} 积分！"

        elif item_id == "2":  # 幸运符
            buffs = user.get("buffs", {})
            buffs["double_next"] = True
            user["buffs"] = buffs
            result_msg += "🍀 下次签到积分翻倍已生效！"

        elif item_id == "3":  # 占卜卡
            result_msg += "🔮 请使用 /占卜 查看今日运势"
            items = user.get("items", {})
            items["3"] = items.get("3", 0) + 1
            user["items"] = items

        elif item_id == "4":  # 改名卡
            result_msg += "💎 请使用 /改名 <新名称> 修改显示名"
            items = user.get("items", {})
            items["4"] = items.get("4", 0) + 1
            user["items"] = items

        elif item_id == "5":  # 补签卡
            result_msg += "🛡️  请使用 /补签 来补签昨天"
            items = user.get("items", {})
            items["5"] = items.get("5", 0) + 1
            user["items"] = items

        elif item_id == "6":  # 抽奖券
            result_msg += "🎲 请使用 /抽奖 参与积分抽奖"
            items = user.get("items", {})
            items["6"] = items.get("6", 0) + 1
            user["items"] = items

        self._save_data()
        result_msg += f"\n\n💰 剩余积分: {user['total_points']}"
        yield event.plain_result(result_msg)

    # ==================== 道具使用 ====================

    @filter.command("占卜")
    @handle_errors
    async def fortune(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """今日运势占卜"""
        user_id = self._get_user_id(event)
        user_name = self._get_user_name(event)

        user = self._ensure_user(user_id, user_name)

        items = user.get("items", {})
        if items.get("3", 0) <= 0:
            yield event.plain_result("🔮 你没有占卜卡，去 /商店 购买一张吧！")
            return

        items["3"] -= 1
        user["items"] = items

        today = self._get_today()
        if user.get("fortune_today") and user["fortune_today"].get("date") == today:
            fortune = user["fortune_today"]
        else:
            level = random.choices(
                ["大吉", "吉", "中", "凶"],
                weights=[15, 35, 40, 10]
            )[0]
            desc = random.choice(FORTUNES[level])
            lucky_num = random.randint(1, 99)
            lucky_color = random.choice(["红", "黄", "蓝", "绿", "紫", "黑", "白"])
            lucky_dir = random.choice(["东", "南", "西", "北", "东南", "西北", "东北", "西南"])

            fortune = {
                "date": today,
                "level": level,
                "desc": desc,
                "lucky_num": lucky_num,
                "lucky_color": lucky_color,
                "lucky_dir": lucky_dir
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
        """使用改名卡修改显示名称

        用法: /改名 新名称
        例如: /改名 小明
        """
        user_id = self._get_user_id(event)
        user_name = self._get_user_name(event)

        user = self._ensure_user(user_id, user_name)

        # 从消息内容解析名称
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
        user["items"] = items
        old_name = user.get("custom_name") or user["name"]
        user["custom_name"] = new_name

        self._save_data()

        yield event.plain_result(
            f"💎 改名成功！\n"
            f"{old_name} → {new_name}\n"
            f"排行榜中已更新显示。"
        )

    @filter.command("补签")
    @handle_errors
    async def makeup_sign(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """使用补签卡补签昨天"""
        user_id = self._get_user_id(event)
        user_name = self._get_user_name(event)

        user = self._ensure_user(user_id, user_name)

        items = user.get("items", {})
        if items.get("5", 0) <= 0:
            yield event.plain_result("🛡️  你没有补签卡，去 /商店 购买一张吧！")
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
        user["items"] = items

        before_yesterday = (datetime.strptime(yesterday, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")

        if user.get("last_signin") == before_yesterday or user.get("streak", 0) > 0:
            user["streak"] = user.get("streak", 0) + 1
        else:
            user["streak"] = 1

        user["last_signin"] = yesterday
        user["total_signins"] += 1
        user["history"].append({
            "date": yesterday,
            "points": 0,
            "streak": user["streak"],
            "makeup": True
        })

        self._save_data()

        yield event.plain_result(
            f"🛡️  补签成功！\n"
            f"📅 补签日期: {yesterday}\n"
            f"🔥 当前连续: {user['streak']} 天\n"
            f"⚠️ 补签不获得积分，仅保持连续天数"
        )

    @filter.command("抽奖")
    @handle_errors
    async def lottery(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """使用抽奖券参与积分抽奖"""
        user_id = self._get_user_id(event)
        user_name = self._get_user_name(event)

        user = self._ensure_user(user_id, user_name)

        items = user.get("items", {})
        if items.get("6", 0) <= 0:
            yield event.plain_result("🎲 你没有抽奖券，去 /商店 购买一张吧！")
            return

        items["6"] -= 1
        user["items"] = items

        prizes = [
            ("💸 谢谢参与", 0, 0.30),
            ("🪙 小奖", random.randint(5, 20), 0.35),
            ("💰 中奖", random.randint(30, 80), 0.25),
            ("💎 大奖", random.randint(100, 200), 0.08),
            ("👑 特等奖", random.randint(300, 500), 0.02),
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
        user["total_points"] += points

        self._save_data()

        msg = f"🎲 抽奖结果\n\n"
        msg += f"🎁 {name}"
        if points > 0:
            msg += f" +{points} 积分！"
        msg += f"\n\n💰 当前积分: {user['total_points']}"

        yield event.plain_result(msg)

    # ==================== 积分转账 ====================

    @filter.command("转账")
    @filter.command("转帐")
    @handle_errors
    async def transfer(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """转账积分给其他用户（通过QQ号）

        用法: /转账 QQ号 金额
        例如: /转账 123456789 100
        """
        if not self.config.enable_transfer:
            yield event.plain_result("积分转账功能已关闭。")
            return

        user_id = self._get_user_id(event)
        user_name = self._get_user_name(event)

        user = self._ensure_user(user_id, user_name)

        # 从消息内容解析参数（使用正则，更健壮）
        message_text = event.message_str or ""

        # 匹配 /转账 或 /转帐 后面跟着QQ号和金额
        match = re.search(r"/(?:转账|转帐)\s+(\d+)\s+(\d+)", message_text)
        if not match:
            yield event.plain_result(
                "❌ 参数格式错误！\n"
                "用法: /转账 QQ号 金额\n"
                "例如: /转账 123456789 100\n\n"
                "💡 提示: 请使用对方的QQ号，不是昵称"
            )
            return

        target_qq = match.group(1)
        amount_str = match.group(2)

        # 解析金额
        try:
            amount = int(amount_str)
        except ValueError:
            yield event.plain_result("❌ 金额格式错误，请输入数字。")
            return

        if amount <= 0:
            yield event.plain_result("❌ 转账金额必须大于0。")
            return

        if user["total_points"] < amount:
            yield event.plain_result(
                f"❌ 积分不足！\n"
                f"你的积分: {user['total_points']}\n"
                f"转账金额: {amount}"
            )
            return

        # 通过QQ号查找目标用户
        target_id = None
        target_display_name = None

        for uid, u in self.user_data.items():
            qq_part = uid.split(":")[-1] if ":" in uid else uid
            if qq_part == target_qq:
                target_id = uid
                target_display_name = self._get_display_name(uid)
                break

        if not target_id:
            yield event.plain_result(
                f"❌ 未找到QQ号为 '{target_qq}' 的用户。\n"
                f"对方需要先使用 /签到 注册账号。"
            )
            return

        if target_id == user_id:
            yield event.plain_result("❌ 不能转账给自己！")
            return

        user["total_points"] -= amount
        self.user_data[target_id]["total_points"] += amount

        self._save_data()

        yield event.plain_result(
            f"💸 转账成功！\n"
            f"从: {self._get_display_name(user_id)}\n"
            f"到: {target_display_name} (QQ:{target_qq})\n"
            f"金额: {amount} 积分\n"
            f"你的剩余积分: {user['total_points']}"
        )

    # ==================== 帮助 ====================

    @filter.command("签到帮助")
    @handle_errors
    async def signin_help(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """查看签到插件帮助"""
        msg = """📖 签到插件 v3.0 使用帮助

📝 签到指令:
  /签到          - 每日签到，获取积分
  /签到信息      - 查看个人签到详情
  /签到排行      - 查看积分排行榜

🛒 商店指令:
  /商店          - 查看积分商店商品
  /购买 <编号>   - 购买商品（如 /购买 1）

🎮 道具指令:
  /占卜          - 使用占卜卡查看今日运势
  /改名 <名称>   - 使用改名卡修改显示名
  /补签          - 使用补签卡补签昨天
  /抽奖          - 使用抽奖券参与积分抽奖

💸 其他指令:
  /转账 QQ号 金额  - 转账积分给其他用户（通过QQ号）
  /重置数据        - 清除所有签到数据（管理员）

✨ 功能说明:
  • 每日签到可获得基础积分 + 连续加成 + 幸运奖励
  • 积分可在商店购买道具：礼盒、幸运符、占卜卡、改名卡、补签卡、抽奖券
  • 连续签到加成有上限，断签会重置天数
  • 数据自动保存，重启不丢失

💡 提示:
  • 签到重置时间默认凌晨5点，可在配置中调整
  • 使用 /商店 查看所有可购买道具
  • 改名卡可以修改排行榜中的显示名称
  • 转账请使用对方QQ号，不是昵称"""

        yield event.plain_result(msg)

    def _is_admin(self, event: AstrMessageEvent) -> bool:
        """检查发送者是否为 AstrBot 管理员"""
        sender_id = event.get_sender_id()
        # 从 AstrBot 配置中获取管理员列表
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

    @filter.command("重置数据")
    @handle_errors
    async def reset_data(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """重置所有签到数据（仅 AstrBot 管理员可用）"""
        if not self._is_admin(event):
            yield event.plain_result("🚫 权限不足！只有 AstrBot 管理员才能使用此指令。")
            return

        if not self.user_data:
            yield event.plain_result("📭 当前没有任何签到数据。")
            return

        user_count = len(self.user_data)
        self.user_data.clear()
        self._save_data()

        yield event.plain_result(
            f"🗑️  数据重置成功！\n"
            f"已清除 {user_count} 位用户的签到记录。\n"
            f"所有积分、连续天数、道具已归零。"
        )

    async def terminate(self):
        """插件卸载时保存数据"""
        self._save_data()
        logger.info("签到插件已卸载，数据已保存")