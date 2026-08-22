"""
AstrBot 签到插件 - SQLite 数据库管理模块

版本: 2.0.0

功能:
- SQLite 数据库连接管理
- 数据表初始化
- 数据备份/恢复
- JSON 旧数据迁移
"""

import os
import json
import shutil
import aiosqlite
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

from astrbot.api import logger
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

from ..core.constants import TZ_BEIJING, LEGACY_DATA_FILENAME
from ..core.models import UserData, SigninRecord, InventoryItem, TransferRecord, GlobalStats


class DatabaseManager:
    """SQLite 数据库管理器

    负责所有数据库操作，包括连接管理、表初始化、数据迁移、备份恢复。
    """

    def __init__(self, plugin_name: str):
        """初始化数据库管理器

        Args:
            plugin_name: 插件名称，用于确定数据目录
        """
        self.plugin_name = plugin_name
        self.data_dir = Path(get_astrbot_plugin_data_path()) / plugin_name
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "signin.db"
        self.backup_dir = self.data_dir / "backups"
        self.backup_dir.mkdir(exist_ok=True)
        self.legacy_file = self.data_dir / LEGACY_DATA_FILENAME
        self._connection: Optional[aiosqlite.Connection] = None

    async def initialize(self) -> bool:
        """初始化数据库

        创建数据表，检查并迁移旧数据。

        Returns:
            是否成功初始化
        """
        try:
            await self._init_tables()

            # 检查是否需要迁移旧数据
            if self.legacy_file.exists():
                migrated = await self._migrate_legacy_data()
                if migrated:
                    logger.info(f"[{self.plugin_name}] 旧数据迁移完成")

            logger.info(f"[{self.plugin_name}] 数据库初始化完成: {self.db_path}")
            return True
        except Exception as e:
            logger.error(f"[{self.plugin_name}] 数据库初始化失败: {e}", exc_info=True)
            return False

    async def _init_tables(self):
        """初始化数据表"""
        async with aiosqlite.connect(self.db_path) as db:
            # 用户表
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL DEFAULT '匿名用户',
                    custom_name TEXT,
                    total_points INTEGER NOT NULL DEFAULT 0,
                    total_signins INTEGER NOT NULL DEFAULT 0,
                    streak INTEGER NOT NULL DEFAULT 0,
                    last_signin TEXT,
                    fortune_today TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 签到记录表
            await db.execute("""
                CREATE TABLE IF NOT EXISTS signin_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    signin_date TEXT NOT NULL,
                    points_earned INTEGER NOT NULL DEFAULT 0,
                    is_continuous INTEGER NOT NULL DEFAULT 0,
                    is_makeup INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )
            """)

            # 道具背包表
            await db.execute("""
                CREATE TABLE IF NOT EXISTS inventory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    quantity INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(user_id, item_id),
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )
            """)

            # 每日购买记录表
            await db.execute("""
                CREATE TABLE IF NOT EXISTS daily_purchases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    purchase_date TEXT NOT NULL,
                    UNIQUE(user_id, item_id, purchase_date),
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )
            """)

            # 转账记录表
            await db.execute("""
                CREATE TABLE IF NOT EXISTS transfers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    from_user TEXT NOT NULL,
                    to_user TEXT NOT NULL,
                    amount INTEGER NOT NULL DEFAULT 0,
                    fee INTEGER NOT NULL DEFAULT 0,
                    transfer_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (from_user) REFERENCES users(user_id) ON DELETE CASCADE,
                    FOREIGN KEY (to_user) REFERENCES users(user_id) ON DELETE CASCADE
                )
            """)

            # 创建索引
            await db.execute("CREATE INDEX IF NOT EXISTS idx_signin_user_date ON signin_records(user_id, signin_date)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_signin_date ON signin_records(signin_date)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_inventory_user ON inventory(user_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_transfer_from ON transfers(from_user)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_transfer_to ON transfers(to_user)")

            await db.commit()

    async def _migrate_legacy_data(self) -> bool:
        """迁移旧版 JSON 数据到 SQLite

        Returns:
            是否成功迁移
        """
        try:
            with open(self.legacy_file, "r", encoding="utf-8") as f:
                legacy_data: Dict[str, Any] = json.load(f)

            if not legacy_data:
                return False

            migrated_count = 0
            async with aiosqlite.connect(self.db_path) as db:
                for user_id, user_info in legacy_data.items():
                    # 迁移用户数据
                    await db.execute("""
                        INSERT OR REPLACE INTO users 
                        (user_id, name, custom_name, total_points, total_signins, streak, last_signin, fortune_today)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        user_id,
                        user_info.get("name", "匿名用户"),
                        user_info.get("custom_name"),
                        user_info.get("total_points", 0),
                        user_info.get("total_signins", 0),
                        user_info.get("streak", 0),
                        user_info.get("last_signin", ""),
                        json.dumps(user_info.get("fortune_today")) if user_info.get("fortune_today") else None,
                    ))

                    # 迁移历史记录
                    for record in user_info.get("history", []):
                        await db.execute("""
                            INSERT OR IGNORE INTO signin_records 
                            (user_id, signin_date, points_earned, is_makeup)
                            VALUES (?, ?, ?, ?)
                        """, (
                            user_id,
                            record.get("date", ""),
                            record.get("points", 0),
                            1 if record.get("makeup") else 0,
                        ))

                    # 迁移道具
                    for item_id, quantity in user_info.get("items", {}).items():
                        if quantity > 0:
                            await db.execute("""
                                INSERT OR REPLACE INTO inventory (user_id, item_id, quantity)
                                VALUES (?, ?, ?)
                            """, (user_id, str(item_id), quantity))

                    # 迁移转账记录
                    for transfer in user_info.get("transfer_history", []):
                        await db.execute("""
                            INSERT INTO transfers (from_user, to_user, amount, fee, transfer_time)
                            VALUES (?, ?, ?, ?, ?)
                        """, (
                            user_id if transfer.get("type") == "send" else f"{user_id.split(':')[0]}:{transfer.get('target', '')}",
                            f"{user_id.split(':')[0]}:{transfer.get('target', '')}" if transfer.get("type") == "send" else user_id,
                            transfer.get("amount", 0),
                            transfer.get("fee", 0),
                            datetime.fromtimestamp(transfer.get("timestamp", 0), TZ_BEIJING).isoformat() if transfer.get("timestamp") else datetime.now(TZ_BEIJING).isoformat(),
                        ))

                    migrated_count += 1

                await db.commit()

            # 备份旧文件
            backup_name = f"{LEGACY_DATA_FILENAME}.migrated.{datetime.now(TZ_BEIJING).strftime('%Y%m%d_%H%M%S')}"
            shutil.move(str(self.legacy_file), str(self.data_dir / backup_name))
            logger.info(f"[{self.plugin_name}] 已迁移 {migrated_count} 位用户数据，旧文件备份为 {backup_name}")
            return True

        except Exception as e:
            logger.error(f"[{self.plugin_name}] 迁移旧数据失败: {e}", exc_info=True)
            return False

    async def backup(self) -> Optional[Path]:
        """创建数据库备份

        Returns:
            备份文件路径，失败返回 None
        """
        try:
            timestamp = datetime.now(TZ_BEIJING).strftime("%Y%m%d_%H%M%S")
            backup_path = self.backup_dir / f"signin_backup_{timestamp}.db"
            shutil.copy2(self.db_path, backup_path)
            logger.info(f"[{self.plugin_name}] 数据库备份完成: {backup_path}")
            return backup_path
        except Exception as e:
            logger.error(f"[{self.plugin_name}] 数据库备份失败: {e}")
            return None

    async def close(self):
        """关闭数据库连接"""
        if self._connection:
            await self._connection.close()
            self._connection = None
            logger.info(f"[{self.plugin_name}] 数据库连接已关闭")

    # ========== 用户数据操作 ==========

    async def get_user(self, user_id: str) -> Optional[UserData]:
        """获取用户信息

        Args:
            user_id: 用户唯一ID

        Returns:
            用户数据，不存在返回 None
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT * FROM users WHERE user_id = ?", (user_id,)
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        data = dict(row)
                        if data.get("fortune_today"):
                            try:
                                data["fortune_today"] = json.loads(data["fortune_today"])
                            except json.JSONDecodeError:
                                data["fortune_today"] = None
                        return UserData.from_dict(data)
                    return None
        except Exception as e:
            logger.error(f"获取用户失败 [{user_id}]: {e}")
            return None

    async def ensure_user(self, user_id: str, name: str) -> UserData:
        """确保用户存在，不存在则创建

        Args:
            user_id: 用户唯一ID
            name: 用户名称

        Returns:
            用户数据
        """
        user = await self.get_user(user_id)
        if user is not None:
            return user

        # 用户不存在，创建新用户
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR IGNORE INTO users (user_id, name, total_points, total_signins, streak, last_signin)
                VALUES (?, ?, 0, 0, 0, '')
            """, (user_id, name))
            await db.commit()

        # 重新查询确保获取到数据
        user = await self.get_user(user_id)
        if user is None:
            # 如果仍然获取不到，返回内存中的对象
            logger.warning(f"创建用户后无法从数据库读取，返回内存对象: {user_id}")
            return UserData(user_id=user_id, name=name)
        return user

    async def update_user(self, user: UserData) -> bool:
        """更新用户信息

        Args:
            user: 用户数据

        Returns:
            是否成功
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    UPDATE users SET
                        name = ?,
                        custom_name = ?,
                        total_points = ?,
                        total_signins = ?,
                        streak = ?,
                        last_signin = ?,
                        fortune_today = ?
                    WHERE user_id = ?
                """, (
                    user.name,
                    user.custom_name,
                    user.total_points,
                    user.total_signins,
                    user.streak,
                    user.last_signin,
                    json.dumps(user.fortune_today) if user.fortune_today else None,
                    user.user_id,
                ))
                await db.commit()
            return True
        except Exception as e:
            logger.error(f"更新用户失败 [{user.user_id}]: {e}")
            return False

    async def update_user_name(self, user_id: str, name: str) -> bool:
        """更新用户名称

        Args:
            user_id: 用户唯一ID
            name: 新名称

        Returns:
            是否成功
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    "UPDATE users SET name = ? WHERE user_id = ?",
                    (name, user_id)
                )
                await db.commit()
            return True
        except Exception as e:
            logger.error(f"更新用户名称失败 [{user_id}]: {e}")
            return False

    async def get_all_users(self) -> List[Tuple[str, UserData]]:
        """获取所有用户

        Returns:
            [(user_id, UserData), ...]
        """
        users = []
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users") as cursor:
                async for row in cursor:
                    data = dict(row)
                    if data.get("fortune_today"):
                        try:
                            data["fortune_today"] = json.loads(data["fortune_today"])
                        except json.JSONDecodeError:
                            data["fortune_today"] = None
                    users.append((data["user_id"], UserData.from_dict(data)))
        return users

    async def get_user_count(self) -> int:
        """获取用户总数

        Returns:
            用户数量
        """
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM users") as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    # ========== 签到记录操作 ==========

    async def add_signin_record(self, record: SigninRecord) -> bool:
        """添加签到记录

        Args:
            record: 签到记录

        Returns:
            是否成功
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    INSERT INTO signin_records (user_id, signin_date, points_earned, is_continuous, is_makeup)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    record.user_id,
                    record.signin_date,
                    record.points_earned,
                    1 if record.is_continuous else 0,
                    1 if record.is_makeup else 0,
                ))
                await db.commit()
            return True
        except Exception as e:
            logger.error(f"添加签到记录失败: {e}")
            return False

    async def get_signin_records(self, user_id: str, limit: int = 100) -> List[SigninRecord]:
        """获取用户签到记录

        Args:
            user_id: 用户唯一ID
            limit: 限制数量

        Returns:
            签到记录列表
        """
        records = []
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM signin_records WHERE user_id = ? ORDER BY signin_date DESC LIMIT ?",
                (user_id, limit)
            ) as cursor:
                async for row in cursor:
                    data = dict(row)
                    records.append(SigninRecord(
                        id=data["id"],
                        user_id=data["user_id"],
                        signin_date=data["signin_date"],
                        points_earned=data["points_earned"],
                        is_continuous=bool(data["is_continuous"]),
                        is_makeup=bool(data["is_makeup"]),
                        created_at=data["created_at"],
                    ))
        return records

    async def get_today_signin_count(self, today: str) -> int:
        """获取今日签到人数

        Args:
            today: 今日日期

        Returns:
            签到人数
        """
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT COUNT(DISTINCT user_id) FROM signin_records WHERE signin_date = ?",
                (today,)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    async def get_month_signin_count(self, user_id: str, month_prefix: str) -> int:
        """获取用户本月签到次数

        Args:
            user_id: 用户唯一ID
            month_prefix: 月份前缀 YYYY-MM

        Returns:
            签到次数
        """
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM signin_records WHERE user_id = ? AND signin_date LIKE ?",
                (user_id, f"{month_prefix}%")
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    # ========== 道具背包操作 ==========

    async def get_inventory(self, user_id: str) -> Dict[str, int]:
        """获取用户道具背包

        Args:
            user_id: 用户唯一ID

        Returns:
            {item_id: quantity, ...}
        """
        items = {}
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT item_id, quantity FROM inventory WHERE user_id = ?",
                (user_id,)
            ) as cursor:
                async for row in cursor:
                    items[row[0]] = row[1]
        return items

    async def add_item(self, user_id: str, item_id: str, quantity: int = 1) -> bool:
        """添加道具

        Args:
            user_id: 用户唯一ID
            item_id: 道具ID
            quantity: 数量

        Returns:
            是否成功
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    INSERT INTO inventory (user_id, item_id, quantity)
                    VALUES (?, ?, ?)
                    ON CONFLICT(user_id, item_id) DO UPDATE SET
                    quantity = quantity + excluded.quantity
                """, (user_id, item_id, quantity))
                await db.commit()
            return True
        except Exception as e:
            logger.error(f"添加道具失败 [{user_id}, {item_id}]: {e}")
            return False

    async def remove_item(self, user_id: str, item_id: str, quantity: int = 1) -> bool:
        """移除道具

        Args:
            user_id: 用户唯一ID
            item_id: 道具ID
            quantity: 数量

        Returns:
            是否成功
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                # 先查询当前数量
                async with db.execute(
                    "SELECT quantity FROM inventory WHERE user_id = ? AND item_id = ?",
                    (user_id, item_id)
                ) as cursor:
                    row = await cursor.fetchone()
                    if not row or row[0] < quantity:
                        return False

                new_qty = row[0] - quantity
                if new_qty <= 0:
                    await db.execute(
                        "DELETE FROM inventory WHERE user_id = ? AND item_id = ?",
                        (user_id, item_id)
                    )
                else:
                    await db.execute(
                        "UPDATE inventory SET quantity = ? WHERE user_id = ? AND item_id = ?",
                        (new_qty, user_id, item_id)
                    )
                await db.commit()
            return True
        except Exception as e:
            logger.error(f"移除道具失败 [{user_id}, {item_id}]: {e}")
            return False

    async def get_item_quantity(self, user_id: str, item_id: str) -> int:
        """获取道具数量

        Args:
            user_id: 用户唯一ID
            item_id: 道具ID

        Returns:
            道具数量
        """
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT quantity FROM inventory WHERE user_id = ? AND item_id = ?",
                (user_id, item_id)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    # ========== 每日购买记录操作 ==========

    async def check_daily_purchase(self, user_id: str, item_id: str, today: str) -> bool:
        """检查今日是否已购买

        Args:
            user_id: 用户唯一ID
            item_id: 道具ID
            today: 今日日期

        Returns:
            今日是否已购买
        """
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT 1 FROM daily_purchases WHERE user_id = ? AND item_id = ? AND purchase_date = ?",
                (user_id, item_id, today)
            ) as cursor:
                row = await cursor.fetchone()
                return row is not None

    async def record_daily_purchase(self, user_id: str, item_id: str, today: str) -> bool:
        """记录每日购买

        Args:
            user_id: 用户唯一ID
            item_id: 道具ID
            today: 今日日期

        Returns:
            是否成功
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    INSERT OR IGNORE INTO daily_purchases (user_id, item_id, purchase_date)
                    VALUES (?, ?, ?)
                """, (user_id, item_id, today))
                await db.commit()
            return True
        except Exception as e:
            logger.error(f"记录每日购买失败: {e}")
            return False

    # ========== 转账记录操作 ==========

    async def add_transfer(self, transfer: TransferRecord) -> bool:
        """添加转账记录

        Args:
            transfer: 转账记录

        Returns:
            是否成功
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    INSERT INTO transfers (from_user, to_user, amount, fee, transfer_time)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    transfer.from_user,
                    transfer.to_user,
                    transfer.amount,
                    transfer.fee,
                    transfer.transfer_time,
                ))
                await db.commit()
            return True
        except Exception as e:
            logger.error(f"添加转账记录失败: {e}")
            return False

    async def get_transfer_history(self, user_id: str, limit: int = 20) -> List[TransferRecord]:
        """获取转账记录

        Args:
            user_id: 用户唯一ID
            limit: 限制数量

        Returns:
            转账记录列表
        """
        records = []
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM transfers 
                WHERE from_user = ? OR to_user = ?
                ORDER BY transfer_time DESC LIMIT ?
            """, (user_id, user_id, limit)) as cursor:
                async for row in cursor:
                    data = dict(row)
                    records.append(TransferRecord(
                        id=data["id"],
                        from_user=data["from_user"],
                        to_user=data["to_user"],
                        amount=data["amount"],
                        fee=data["fee"],
                        transfer_time=data["transfer_time"],
                    ))
        return records

    # ========== 排行榜操作 ==========

    async def get_rankboard(self, limit: int = 10) -> List[Tuple[str, UserData]]:
        """获取积分排行榜

        Args:
            limit: 限制数量

        Returns:
            [(user_id, UserData), ...]
        """
        users = []
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM users ORDER BY total_points DESC LIMIT ?",
                (limit,)
            ) as cursor:
                async for row in cursor:
                    data = dict(row)
                    if data.get("fortune_today"):
                        try:
                            data["fortune_today"] = json.loads(data["fortune_today"])
                        except json.JSONDecodeError:
                            data["fortune_today"] = None
                    users.append((data["user_id"], UserData.from_dict(data)))
        return users

    async def get_user_rank(self, user_id: str) -> int:
        """获取用户排名

        Args:
            user_id: 用户唯一ID

        Returns:
            排名，未找到返回 -1
        """
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT rank FROM (
                    SELECT user_id, ROW_NUMBER() OVER (ORDER BY total_points DESC) as rank
                    FROM users
                ) WHERE user_id = ?
            """, (user_id,)) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else -1

    # ========== 统计数据 ==========

    async def get_global_stats(self, today: str) -> GlobalStats:
        """获取全局统计数据

        Args:
            today: 今日日期

        Returns:
            全局统计数据
        """
        async with aiosqlite.connect(self.db_path) as db:
            # 总用户数
            async with db.execute("SELECT COUNT(*) FROM users") as cursor:
                total_users = (await cursor.fetchone())[0]

            # 今日签到数
            async with db.execute(
                "SELECT COUNT(DISTINCT user_id) FROM signin_records WHERE signin_date = ?",
                (today,)
            ) as cursor:
                today_signin = (await cursor.fetchone())[0]

            # 总积分
            async with db.execute("SELECT COALESCE(SUM(total_points), 0) FROM users") as cursor:
                total_points = (await cursor.fetchone())[0]

            # 7日活跃
            seven_days_ago = (datetime.strptime(today, "%Y-%m-%d") - __import__("datetime").timedelta(days=7)).strftime("%Y-%m-%d")
            async with db.execute(
                "SELECT COUNT(DISTINCT user_id) FROM signin_records WHERE signin_date >= ?",
                (seven_days_ago,)
            ) as cursor:
                active_7d = (await cursor.fetchone())[0]

            # 30日活跃
            thirty_days_ago = (datetime.strptime(today, "%Y-%m-%d") - __import__("datetime").timedelta(days=30)).strftime("%Y-%m-%d")
            async with db.execute(
                "SELECT COUNT(DISTINCT user_id) FROM signin_records WHERE signin_date >= ?",
                (thirty_days_ago,)
            ) as cursor:
                active_30d = (await cursor.fetchone())[0]

        return GlobalStats(
            total_users=total_users,
            today_signin=today_signin,
            total_points=total_points,
            active_7d=active_7d,
            active_30d=active_30d,
        )

    # ========== 数据清理 ==========

    async def reset_all_data(self) -> bool:
        """重置所有数据

        Returns:
            是否成功
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("DELETE FROM daily_purchases")
                await db.execute("DELETE FROM transfers")
                await db.execute("DELETE FROM inventory")
                await db.execute("DELETE FROM signin_records")
                await db.execute("DELETE FROM users")
                await db.commit()
            logger.warning(f"[{self.plugin_name}] 所有数据已重置")
            return True
        except Exception as e:
            logger.error(f"重置数据失败: {e}")
            return False
