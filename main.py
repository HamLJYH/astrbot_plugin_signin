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
版本: 2.0.0
日期: 2026-08-22
"""

import random
import re
import asyncio
from datetime import datetime
from typing import Dict, Any, AsyncGenerator, Optional

from astrbot.api.star import Context, Star
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api import logger

from .core.config import PluginConfig
from .core.constants import (
    TZ_BEIJING, MAX_NICKNAME_LENGTH, SHOP_ITEMS, DAILY_LIMIT_ITEMS,
    FORTUNE_EMOJIS, MessageEmoji, MILESTONES
)
from .core.models import (
    UserData, SigninRecord, TransferRecord, SigninResult, OperationResult
)
from .services.database import DatabaseManager
from .utils.decorators import handle_errors
from .utils.validators import (
    extract_target_qq, extract_amount, validate_nickname, format_amount_change
)
from .utils.helpers import (
    get_today, get_yesterday, get_before_yesterday,
    get_user_id, get_user_name, get_rank_emoji,
    generate_fortune, format_fortune_message,
    calculate_signin_points, check_milestone
)


PLUGIN_NAME = "astrbot_plugin_signin"


class SignInPlugin(Star):
    """签到插件主类"""

    def __init__(self, context: Context, config: dict = None):
        """初始化插件

        Args:
            context: AstrBot 上下文
            config: 插件配置（由 AstrBot 根据 _conf_schema.json 自动传入）
        """
        super().__init__(context)

        # 加载插件配置
        self.plugin_config = self._parse_config(config or {})
        logger.info(
            f"[{PLUGIN_NAME}] 配置加载成功: "
            f"base_points={self.plugin_config.base_points}, "
            f"reset_hour={self.plugin_config.reset_hour}"
        )

        # 初始化数据库
        self.db = DatabaseManager(PLUGIN_NAME)

        # 立即初始化数据库（创建表 + 迁移旧数据）
        asyncio.create_task(self._init_database())

        logger.info(f"[{PLUGIN_NAME}] v2.0.0 已加载")

    def _parse_config(self, config: Dict[str, Any]) -> PluginConfig:
        """解析插件配置"""
        try:
            cfg = PluginConfig.from_dict(config)
            cfg.validate()
            logger.info(f"[{PLUGIN_NAME}] 使用 WebUI 配置")
            return cfg
        except Exception as e:
            logger.warning(f"[{PLUGIN_NAME}] 配置解析失败，使用默认配置: {e}")
            return PluginConfig()

    async def _init_database(self):
        """异步初始化数据库"""
        try:
            success = await self.db.initialize()
            if success:
                logger.info(f"[{PLUGIN_NAME}] 数据库初始化成功")
            else:
                logger.error(f"[{PLUGIN_NAME}] 数据库初始化失败")
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] 数据库初始化异常: {e}", exc_info=True)

    async def terminate(self):
        """插件卸载时清理资源"""
        await self.db.close()
        logger.info(f"[{PLUGIN_NAME}] 插件已卸载")

    # ========== 辅助方法 ==========

    def _is_admin(self, event: AstrMessageEvent) -> bool:
        """检查是否为管理员"""
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

    def _get_today(self) -> str:
        """获取今日日期"""
        return get_today(self.plugin_config.reset_hour)

    def _get_yesterday(self) -> str:
        """获取昨天日期"""
        return get_yesterday(self.plugin_config.reset_hour)

    def _get_before_yesterday(self) -> str:
        """获取前天日期"""
        return get_before_yesterday(self.plugin_config.reset_hour)

    # ========== 签到指令 ==========

    @filter.command("签到")
    @handle_errors
    async def signin(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """每日签到"""
        user_id = get_user_id(event)
        user_name = get_user_name(event)
        today = self._get_today()

        # 确保用户存在
        user = await self.db.ensure_user(user_id, user_name)

        # 更新名称（可能已变更）
        await self.db.update_user_name(user_id, user_name)

        # 检查今日是否已签到
        if user.last_signin == today:
            yield event.plain_result(
                f"{MessageEmoji.CLOCK} {user.display_name}，你今天已经签到过了！\n"
                f"{MessageEmoji.COIN} 当前积分: {user.total_points}\n"
                f"{MessageEmoji.FIRE} 连续签到: {user.streak} 天"
            )
            return

        # 计算连续天数
        yesterday = self._get_yesterday()
        if user.last_signin == yesterday:
            user.streak += 1
            is_continuous = True
        else:
            if user.streak > 0:
                logger.info(f"用户 {user_name} 连续签到中断")
            user.streak = 1
            is_continuous = False

        # 检查双倍积分 buff
        double_next = False

        # 计算积分
        points_detail = calculate_signin_points(
            base_points=self.plugin_config.base_points,
            streak=user.streak,
            streak_bonus_enabled=self.plugin_config.streak_bonus,
            streak_bonus_rate=self.plugin_config.streak_bonus_rate,
            max_streak_bonus=self.plugin_config.max_streak_bonus,
            lucky_draw_enabled=self.plugin_config.lucky_draw,
            lucky_draw_max=self.plugin_config.lucky_draw_points_max,
            double_next=double_next,
        )

        total_points = points_detail["total"]
        base = points_detail["base"]
        streak_bonus = points_detail["streak_bonus"]
        lucky = points_detail["lucky"]

        # 更新用户数据
        user.total_points += total_points
        user.total_signins += 1
        user.last_signin = today
        user.fortune_today = None
        await self.db.update_user(user)

        # 记录签到
        record = SigninRecord(
            user_id=user_id,
            signin_date=today,
            points_earned=total_points,
            is_continuous=is_continuous,
        )
        await self.db.add_signin_record(record)

        # 构建消息
        msg_parts = [
            f"{MessageEmoji.SUCCESS} 签到成功！{user.display_name}",
            "",
            f"{MessageEmoji.CALENDAR} 今日日期: {today}",
            f"{MessageEmoji.STAR} 获得积分: +{total_points}",
            f"   ├ 基础积分: +{base}",
        ]
        if streak_bonus > 0:
            msg_parts.append(f"   ├ 连续加成: +{streak_bonus} (连续{user.streak}天)")
        if lucky > 0:
            msg_parts.append(f"   └ {MessageEmoji.GIFT} 幸运奖励: +{lucky}")
        msg_parts.extend([
            "",
            f"{MessageEmoji.COIN} 总积分: {user.total_points}",
            f"{MessageEmoji.FIRE} 连续签到: {user.streak} 天",
            f"{MessageEmoji.CHART} 累计签到: {user.total_signins} 天"
        ])

        # 里程碑检测
        milestone = check_milestone(user.streak)
        if milestone:
            msg_parts.extend(["", f"🎊 恭喜！你已连续签到 {milestone} 天！"])

        yield event.plain_result("\n".join(msg_parts))

    @filter.command("签到信息")
    @handle_errors
    async def signin_info(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """查看个人签到详情"""
        user_id = get_user_id(event)
        user_name = get_user_name(event)
        today = self._get_today()

        user = await self.db.ensure_user(user_id, user_name)
        signed_today = user.last_signin == today

        # 获取排名
        rank = await self.db.get_user_rank(user_id)
        rank_str = f"第 {rank} 名" if rank > 0 else "-"

        # 本月签到数
        current_month = today[:7]
        month_count = await self.db.get_month_signin_count(user_id, current_month)

        # 道具列表
        inventory = await self.db.get_inventory(user_id)
        item_str = ""
        if inventory:
            item_list = []
            for item_id, count in inventory.items():
                if count > 0:
                    item_name = SHOP_ITEMS.get(item_id, {}).get("name", f"道具{item_id}")
                    item_list.append(f"{item_name} x{count}")
            if item_list:
                item_str = "\n{MessageEmoji.BAG} 背包: " + ", ".join(item_list)

        status = f"{MessageEmoji.SUCCESS} 已签到" if signed_today else f"{MessageEmoji.ERROR} 未签到"
        msg = (
            f"📋 {user.display_name} 的签到信息\n\n"
            f"{MessageEmoji.CHART} 签到状态: {status}\n"
            f"{MessageEmoji.COIN} 总积分: {user.total_points}\n"
            f"{MessageEmoji.TROPHY} 积分排名: {rank_str}\n"
            f"{MessageEmoji.FIRE} 连续签到: {user.streak} 天\n"
            f"{MessageEmoji.CHART} 累计签到: {user.total_signins} 天\n"
            f"{MessageEmoji.CALENDAR} 本月签到: {month_count} 天\n"
            f"🗓️  最后签到: {user.last_signin or '无记录'}"
            f"{item_str}"
        )
        yield event.plain_result(msg)

    @filter.command("签到排行")
    @handle_errors
    async def signin_rank(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """查看积分排行榜"""
        if not self.plugin_config.enable_rank:
            yield event.plain_result("排行榜功能已关闭。")
            return

        user_count = await self.db.get_user_count()
        if user_count == 0:
            yield event.plain_result("暂无签到数据，快来成为第一个签到的人吧！")
            return

        limit = self.plugin_config.top_limit
        ranked_users = await self.db.get_rankboard(limit)

        msg_lines = [f"{MessageEmoji.TROPHY} 签到积分排行榜 {MessageEmoji.TROPHY}", ""]
        for i, (uid, user) in enumerate(ranked_users, 1):
            emoji = get_rank_emoji(i)
            name = user.display_name[:10]
            msg_lines.append(
                f"{emoji} {name:<12} 积分: {user.total_points:>6}  连续: {user.streak:>3}天"
            )
        msg_lines.extend(["", f"{MessageEmoji.CHART} 共 {user_count} 位用户参与签到"])
        yield event.plain_result("\n".join(msg_lines))

    # ========== 商店指令 ==========

    @filter.command("商店")
    @handle_errors
    async def shop(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """查看积分商店"""
        if not self.plugin_config.enable_shop:
            yield event.plain_result("积分商店功能已关闭。")
            return

        msg_lines = [f"{MessageEmoji.SHOP} 积分商店 {MessageEmoji.SHOP}", ""]
        for item_id, item in SHOP_ITEMS.items():
            limit_tag = "【每日限购1个】" if item_id in DAILY_LIMIT_ITEMS else ""
            msg_lines.append(
                f"[{item_id}] {item['name']} {limit_tag}\n"
                f"    {MessageEmoji.COIN} 价格: {item['price']} 积分\n"
                f"    📖 {item['desc']}"
            )
        msg_lines.extend(["", "使用 /购买 <编号> 来购买商品"])
        yield event.plain_result("\n".join(msg_lines))

    @filter.command("购买")
    @handle_errors
    async def buy(self, event: AstrMessageEvent, item_id: int = None) -> AsyncGenerator[Any, None]:
        """购买商品"""
        if not self.plugin_config.enable_shop:
            yield event.plain_result("积分商店功能已关闭。")
            return

        user_id = get_user_id(event)
        user_name = get_user_name(event)

        # 如果 AstrBot 参数解析失败，尝试正则回退
        if item_id is None:
            message_text = event.message_str or ""
            match = re.search(r"/购买\s+(\d+)", message_text)
            if match:
                item_id = int(match.group(1))

        if item_id is None:
            yield event.plain_result(f"{MessageEmoji.ERROR} 请指定商品编号，如 /购买 1")
            return

        item_id_str = str(item_id)
        item = SHOP_ITEMS.get(item_id_str)
        if not item:
            yield event.plain_result(
                f"{MessageEmoji.ERROR} 商品编号不存在，请使用 /商店 查看商品列表。"
            )
            return

        user = await self.db.ensure_user(user_id, user_name)
        today = self._get_today()

        # 检查每日限购
        if item_id_str in DAILY_LIMIT_ITEMS:
            already_bought = await self.db.check_daily_purchase(user_id, item_id_str, today)
            if already_bought:
                yield event.plain_result(
                    f"🚫 今日已购买过 {item['name']} 了！\n"
                    f"每天限购1个，凌晨{self.plugin_config.reset_hour}点刷新。"
                )
                return

        # 检查积分
        if user.total_points < item["price"]:
            yield event.plain_result(
                f"{MessageEmoji.ERROR} 积分不足！\n"
                f"商品: {item['name']} (需要 {item['price']} 积分)\n"
                f"你的积分: {user.total_points}"
            )
            return

        # 扣除积分
        user.total_points -= item["price"]
        await self.db.update_user(user)

        # 记录每日购买
        if item_id_str in DAILY_LIMIT_ITEMS:
            await self.db.record_daily_purchase(user_id, item_id_str, today)

        # 处理购买结果
        result_msg = f"{MessageEmoji.SUCCESS} 购买成功！\n\n{item['name']}\n"

        if item_id_str == "1":
            # 神秘礼盒
            reward = random.randint(10, 100)
            user.total_points += reward
            await self.db.update_user(user)
            result_msg += f"{MessageEmoji.GIFT} 打开礼盒获得 {reward} 积分！"

        elif item_id_str == "2":
            # 幸运符 - 存入背包，使用时触发
            await self.db.add_item(user_id, "2", 1)
            result_msg += "🍀 幸运符已放入背包！使用 /幸运符 可在下次签到时翻倍积分。"

        elif item_id_str in ("3", "4", "5", "6"):
            # 直接放入背包
            await self.db.add_item(user_id, item_id_str, 1)
            usage_map = {
                "3": "🔮 请使用 /占卜 查看今日运势",
                "4": "💎 请使用 /改名 <新名称> 修改显示名",
                "5": "🛡️ 请使用 /补签 来补签昨天",
                "6": "🎲 请使用 /抽奖 参与积分抽奖",
            }
            result_msg += usage_map.get(item_id_str, "")

        result_msg += f"\n\n{MessageEmoji.COIN} 剩余积分: {user.total_points}"
        yield event.plain_result(result_msg)

    # ========== 道具指令 ==========

    @filter.command("占卜")
    @handle_errors
    async def fortune(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """使用占卜卡查看今日运势"""
        user_id = get_user_id(event)
        user_name = get_user_name(event)
        today = self._get_today()

        # 检查道具
        qty = await self.db.get_item_quantity(user_id, "3")
        if qty <= 0:
            yield event.plain_result(
                f"🔮 你没有占卜卡，去 /商店 购买一张吧！"
            )
            return

        # 消耗道具
        await self.db.remove_item(user_id, "3", 1)

        user = await self.db.ensure_user(user_id, user_name)

        # 检查今日是否已占卜
        if user.fortune_today and user.fortune_today.get("date") == today:
            fortune_data = user.fortune_today
        else:
            fortune_data = generate_fortune()
            user.fortune_today = fortune_data
            await self.db.update_user(user)

        msg = format_fortune_message(fortune_data, user.display_name)
        yield event.plain_result(msg)

    @filter.command("改名")
    @handle_errors
    async def rename(self, event: AstrMessageEvent, new_name: str = None) -> AsyncGenerator[Any, None]:
        """使用改名卡修改显示名"""
        user_id = get_user_id(event)
        user_name = get_user_name(event)

        # 如果 AstrBot 参数解析失败，尝试正则回退
        if new_name is None:
            message_text = event.message_str or ""
            match = re.search(r"/改名\s+(.+)", message_text)
            if match:
                new_name = match.group(1).strip()

        # 检查道具
        qty = await self.db.get_item_quantity(user_id, "4")
        if qty <= 0:
            yield event.plain_result(
                f"💎 你没有改名卡，去 /商店 购买一张吧！"
            )
            return

        # 验证名称
        valid, error = validate_nickname(new_name)
        if not valid:
            yield event.plain_result(f"{MessageEmoji.ERROR} {error}")
            return

        # 消耗道具
        await self.db.remove_item(user_id, "4", 1)

        # 更新名称
        user = await self.db.ensure_user(user_id, user_name)
        old_name = user.display_name
        user.custom_name = new_name
        await self.db.update_user(user)

        yield event.plain_result(
            f"💎 改名成功！\n{old_name} → {new_name}\n排行榜中已更新显示。"
        )

    @filter.command("补签")
    @handle_errors
    async def makeup_sign(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """使用补签卡补签昨天"""
        user_id = get_user_id(event)
        user_name = get_user_name(event)

        # 检查道具
        qty = await self.db.get_item_quantity(user_id, "5")
        if qty <= 0:
            yield event.plain_result(
                f"🛡️ 你没有补签卡，去 /商店 购买一张吧！"
            )
            return

        today = self._get_today()
        yesterday = self._get_yesterday()
        before_yesterday = self._get_before_yesterday()

        user = await self.db.ensure_user(user_id, user_name)

        if user.last_signin == today:
            yield event.plain_result(
                f"{MessageEmoji.SUCCESS} 你今天已经签到了，不需要补签！"
            )
            return
        if user.last_signin == yesterday:
            yield event.plain_result(
                f"{MessageEmoji.SUCCESS} 你昨天已经签到了，不需要补签！"
            )
            return

        # 消耗道具
        await self.db.remove_item(user_id, "5", 1)

        # 计算补签后的连续天数
        if user.last_signin == before_yesterday:
            user.streak += 1
        elif user.last_signin == "":
            user.streak = 1
        else:
            user.streak = 1

        user.last_signin = yesterday
        user.total_signins += 1
        await self.db.update_user(user)

        # 记录补签
        record = SigninRecord(
            user_id=user_id,
            signin_date=yesterday,
            points_earned=0,
            is_makeup=True,
        )
        await self.db.add_signin_record(record)

        yield event.plain_result(
            f"🛡️ 补签成功！\n{MessageEmoji.CALENDAR} 补签日期: {yesterday}\n"
            f"{MessageEmoji.FIRE} 当前连续: {user.streak} 天\n"
            f"⚠️ 补签不获得积分，仅保持连续天数"
        )

    @filter.command("抽奖")
    @handle_errors
    async def lottery(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """使用抽奖券参与积分抽奖"""
        user_id = get_user_id(event)
        user_name = get_user_name(event)

        # 检查道具
        qty = await self.db.get_item_quantity(user_id, "6")
        if qty <= 0:
            yield event.plain_result(
                f"🎲 你没有抽奖券，去 /商店 购买一张吧！"
            )
            return

        # 消耗道具
        await self.db.remove_item(user_id, "6", 1)

        user = await self.db.ensure_user(user_id, user_name)

        # 抽奖逻辑
        from .core.constants import LOTTERY_PRIZES
        r = random.random()
        cumulative = 0
        prize = LOTTERY_PRIZES[0]
        for p in LOTTERY_PRIZES:
            cumulative += p[2]
            if r <= cumulative:
                prize = p
                break

        name, points_range, _ = prize

        # 计算实际积分
        if isinstance(points_range, tuple):
            points = random.randint(points_range[0], points_range[1])
        else:
            points = points_range

        old_points = user.total_points
        user.total_points += points
        if user.total_points < 0:
            user.total_points = 0
        await self.db.update_user(user)

        msg_lines = [f"{MessageEmoji.DICE} 抽奖结果", ""]
        if points > 0:
            msg_lines.append(f"🎁 {name} +{points} 积分！")
        elif points < 0:
            actual_deducted = old_points - user.total_points
            msg_lines.append(f"💥 {name} -{actual_deducted} 积分！")
            if user.total_points == 0:
                msg_lines.append("😱 积分被扣光了！")
        else:
            msg_lines.append(f"🎁 {name}")
        msg_lines.append("")
        msg_lines.append(f"{MessageEmoji.COIN} 当前积分: {user.total_points}")
        yield event.plain_result("\n".join(msg_lines))

    @filter.command("幸运符")
    @handle_errors
    async def use_lucky_charm(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """使用幸运符（下次签到积分翻倍）"""
        user_id = get_user_id(event)

        qty = await self.db.get_item_quantity(user_id, "2")
        if qty <= 0:
            yield event.plain_result(
                f"🍀 你没有幸运符，去 /商店 购买一张吧！"
            )
            return

        # 幸运符效果：直接消耗并提示
        user = await self.db.ensure_user(user_id, get_user_name(event))
        bonus = self.plugin_config.base_points
        user.total_points += bonus
        await self.db.remove_item(user_id, "2", 1)
        await self.db.update_user(user)

        yield event.plain_result(
            f"🍀 幸运符生效！\n"
            f"获得了 {bonus} 积分的幸运加成！\n"
            f"{MessageEmoji.COIN} 当前积分: {user.total_points}"
        )

    # ========== 转账指令 ==========

    @filter.command("转账")
    @handle_errors
    async def transfer(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """转账给其他用户"""
        if not self.plugin_config.enable_transfer:
            yield event.plain_result("💸 转账功能已关闭。")
            return

        user_id = get_user_id(event)
        user_name = get_user_name(event)
        sender = await self.db.ensure_user(user_id, user_name)

        # 解析目标QQ号和金额
        target_qq = extract_target_qq(event)
        amount = extract_amount(event)

        if not target_qq:
            yield event.plain_result(
                f"{MessageEmoji.ERROR} 请指定转账目标。\n"
                "用法: /转账 @用户 积分\n"
                "或: /转账 QQ号 积分"
            )
            return

        if not amount or amount <= 0:
            yield event.plain_result(
                f"{MessageEmoji.ERROR} 请指定有效的转账金额。用法: /转账 QQ号 积分"
            )
            return

        # 构建目标用户的完整ID（假设同平台）
        platform = event.get_platform_name()
        target_id = f"{platform}:{target_qq}"

        if target_id == user_id:
            yield event.plain_result(f"{MessageEmoji.ERROR} 不能转账给自己。")
            return

        # 检查最低转账金额
        min_amount = self.plugin_config.transfer_min_amount
        if amount < min_amount:
            yield event.plain_result(
                f"{MessageEmoji.ERROR} 最低转账金额为 {min_amount} 积分。"
            )
            return

        # 计算手续费
        fee_rate = self.plugin_config.transfer_fee_rate
        fee = int(amount * fee_rate)
        total_cost = amount + fee

        if sender.total_points < total_cost:
            yield event.plain_result(
                f"{MessageEmoji.ERROR} 积分不足。\n"
                f"转账积分: {amount}\n"
                f"手续费: {fee} ({int(fee_rate * 100)}%)\n"
                f"总计需要: {total_cost} 积分\n"
                f"你的积分: {sender.total_points}"
            )
            return

        # 确保目标用户存在
        target = await self.db.ensure_user(target_id, f"用户{target_qq}")

        # 执行转账
        sender_before = sender.total_points
        target_before = target.total_points
        sender.total_points -= total_cost
        target.total_points += amount
        await self.db.update_user(sender)
        await self.db.update_user(target)

        # 记录转账
        now = datetime.now(TZ_BEIJING).isoformat()
        transfer_record = TransferRecord(
            from_user=user_id,
            to_user=target_id,
            amount=amount,
            fee=fee,
            transfer_time=now,
        )
        await self.db.add_transfer(transfer_record)

        sender_name = sender.display_name
        target_name = target.display_name

        yield event.plain_result(
            f"{MessageEmoji.SUCCESS} 转账成功！\n"
            f"💸 从 {sender_name} 转给 {target_name}\n"
            f"💰 转账积分: {amount}\n"
            f"💵 手续费: {fee} 积分 ({int(fee_rate * 100)}%)\n"
            f"{format_amount_change(sender_before, sender.total_points, '📊 你的余额')}\n"
            f"{format_amount_change(target_before, target.total_points, '📊 对方余额')}"
        )

    @filter.command("转账记录")
    @handle_errors
    async def transfer_history(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """查看转账记录"""
        user_id = get_user_id(event)
        user_name = get_user_name(event)
        user = await self.db.ensure_user(user_id, user_name)

        records = await self.db.get_transfer_history(user_id, 10)
        if not records:
            yield event.plain_result("📭 暂无转账记录。")
            return

        msg_lines = [f"📋 {user.display_name} 的转账记录", ""]
        for i, record in enumerate(records, 1):
            ts = record.transfer_time
            try:
                dt = datetime.fromisoformat(ts)
                date_str = dt.strftime("%m-%d %H:%M")
            except:
                date_str = "未知时间"

            if record.from_user == user_id:
                target_qq = record.to_user.split(":")[-1]
                msg_lines.append(
                    f"{i}. {MessageEmoji.ARROW_RIGHT} {date_str} "
                    f"转给 {target_qq} {record.amount}积分"
                    f" (手续费{record.fee})"
                )
            else:
                from_qq = record.from_user.split(":")[-1]
                msg_lines.append(
                    f"{i}. {MessageEmoji.ARROW_LEFT} {date_str} "
                    f"来自 {from_qq} {record.amount}积分"
                )
        yield event.plain_result("\n".join(msg_lines))

    # ========== 管理指令 ==========

    @filter.command("重置数据")
    @filter.permission_type(filter.PermissionType.ADMIN)
    @handle_errors
    async def reset_data(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """清除所有签到数据（管理员）"""
        user_count = await self.db.get_user_count()
        if user_count == 0:
            yield event.plain_result("📭 当前没有任何签到数据。")
            return

        success = await self.db.reset_all_data()
        if success:
            yield event.plain_result(
                f"{MessageEmoji.TRASH} 数据重置成功！\n"
                f"已清除 {user_count} 位用户的签到记录。\n"
                f"所有积分、连续天数、道具已归零。"
            )
        else:
            yield event.plain_result(f"{MessageEmoji.ERROR} 数据重置失败，请检查日志。")

    @filter.command("签到帮助")
    @handle_errors
    async def signin_help(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """显示帮助信息"""
        msg = (
            f"📖 签到插件 v2.0.0 使用帮助\n\n"
            f"📝 签到指令:\n"
            f"  /签到          - 每日签到，获取积分\n"
            f"  /签到信息      - 查看个人签到详情\n"
            f"  /签到排行      - 查看积分排行榜\n\n"
            f"🛒 商店指令:\n"
            f"  /商店          - 查看积分商店商品\n"
            f"  /购买 <编号>   - 购买商品（如 /购买 1）\n\n"
            f"🎮 道具指令:\n"
            f"  /占卜          - 使用占卜卡查看今日运势\n"
            f"  /改名 <名称>   - 使用改名卡修改显示名\n"
            f"  /补签          - 使用补签卡补签昨天\n"
            f"  /抽奖          - 使用抽奖券参与积分抽奖\n"
            f"  /幸运符        - 使用幸运符获得积分加成\n\n"
            f"💸 转账指令:\n"
            f"  /转账 QQ号 金额  - 转账积分给其他用户\n"
            f"  /转账记录       - 查看转账历史\n\n"
            f"🔧 管理指令:\n"
            f"  /重置数据        - 清除所有签到数据（管理员）\n\n"
            f"✨ 功能说明:\n"
            f"  • 每日签到可获得基础积分 + 连续加成 + 幸运奖励\n"
            f"  • 积分可在商店购买道具\n"
            f"  • 神秘礼盒和抽奖券每日限购1个\n"
            f"  • 抽奖有概率触发惩罚（扣分，但不会扣到负数）\n"
            f"  • 连续签到加成有上限，断签会重置天数\n"
            f"  • 转账有手续费\n"
            f"  • 数据自动保存到 SQLite，重启不丢失\n"
            f"  • 支持从旧版 JSON 数据自动迁移"
        )
        yield event.plain_result(msg)
