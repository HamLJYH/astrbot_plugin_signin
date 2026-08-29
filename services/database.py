"""
AstrBot 签到插件 - SQLite 数据库管理模块 

版本: 2.0.1
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
    """SQLite 数据库管理器"""

    def __init__(self, plugin_name: str):
        self.plugin_name = plugin_name
        self.data_dir = Path(get_astrbot_plugin_data_path()) / plugin_name
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "signin.db"
        self.backup_dir = self.data_dir / "backups"
        self.backup_dir.mkdir(exist_ok=True)
        self.legacy_file = self.data_dir / LEGACY_DATA_FILENAME
        self._connection: Optional[aiosqlite.Connection] = None

    async def initialize(self) -> bool:
        try:
            await self._init_tables()
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
        async with aiosqlite.connect(self.db_path) as db:
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
            await db.execute("CREATE INDEX IF NOT EXISTS idx_signin_user_date ON signin_records(user_id, signin_date)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_signin_date ON signin_records(signin_date)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_inventory_user ON inventory(user_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_transfer_from ON transfers(from_user)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_transfer_to ON transfers(to_user)")
            await db.commit()

    async def _migrate_legacy_data(self) -> bool:
        try:
            with open(self.legacy_file, "r", encoding="utf-8") as f:
                legacy_data: Dict[str, Any] = json.load(f)
            if not legacy_data:
                return False
            migrated_count = 0
            async with aiosqlite.connect(self.db_path) as db:
                for user_id, user_info in legacy_data.items():
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
                    for item_id, quantity in user_info.get("items", {}).items():
                        if quantity > 0:
                            await db.execute("""
                                INSERT OR REPLACE INTO inventory (user_id, item_id, quantity)
                                VALUES (?, ?, ?)
                            """, (user_id, str(item_id), quantity))
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
            backup_name = f"{LEGACY_DATA_FILENAME}.migrated.{datetime.now(TZ_BEIJING).strftime('%Y%m%d_%H%M%S')}"
            shutil.move(str(self.legacy_file), str(self.data_dir / backup_name))
            logger.info(f"[{self.plugin_name}] 已迁移 {migrated_count} 位用户数据")
            return True
        except Exception as e:
            logger.error(f"[{self.plugin_name}] 迁移旧数据失败: {e}", exc_info=True)
            return False

    async def backup(self) -> Optional[Path]:
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
        if self._connection:
            await self._connection.close()
            self._connection = None
            logger.info(f"[{self.plugin_name}] 数据库连接已关闭")

    async def get_user(self, user_id: str) -> Optional[UserData]:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
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
        user = await self.get_user(user_id)
        if user is not None:
            return user
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR IGNORE INTO users (user_id, name, total_points, total_signins, streak, last_signin)
                VALUES (?, ?, 0, 0, 0, '')
            """, (user_id, name))
            await db.commit()
        user = await self.get_user(user_id)
        if user is None:
            logger.warning(f"创建用户后无法从数据库读取，返回内存对象: {user_id}")
            return UserData(user_id=user_id, name=name)
        return user

    async def update_user(self, user: UserData) -> bool:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    UPDATE users SET
                        name = ?, custom_name = ?, total_points = ?,
                        total_signins = ?, streak = ?, last_signin = ?, fortune_today = ?
                    WHERE user_id = ?
                """, (
                    user.name, user.custom_name, user.total_points,
                    user.total_signins, user.streak, user.last_signin,
                    json.dumps(user.fortune_today) if user.fortune_today else None,
                    user.user_id,
                ))
                await db.commit()
            return True
        except Exception as e:
            logger.error(f"更新用户失败 [{user.user_id}]: {e}")
            return False

    async def update_user_name(self, user_id: str, name: str) -> bool:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("UPDATE users SET name = ? WHERE user_id = ?", (name, user_id))
                await db.commit()
            return True
        except Exception as e:
            logger.error(f"更新用户名称失败 [{user_id}]: {e}")
            return False

    async def get_all_users(self) -> List[Tuple[str, UserData]]:
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
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM users") as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    async def add_signin_record(self, record: SigninRecord) -> bool:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    INSERT INTO signin_records (user_id, signin_date, points_earned, is_continuous, is_makeup)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    record.user_id, record.signin_date, record.points_earned,
                    1 if record.is_continuous else 0,
                    1 if record.is_makeup else 0,
                ))
                await db.commit()
            return True
        except Exception as e:
            logger.error(f"添加签到记录失败: {e}")
            return False

    async def get_signin_records(self, user_id: str, limit: int = 100) -> List[SigninRecord]:
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
                        id=data["id"], user_id=data["user_id"],
                        signin_date=data["signin_date"], points_earned=data["points_earned"],
                        is_continuous=bool(data["is_continuous"]),
                        is_makeup=bool(data["is_makeup"]),
                        created_at=data["created_at"],
                    ))
        return records

    async def get_today_signin_count(self, today: str) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT COUNT(DISTINCT user_id) FROM signin_records WHERE signin_date = ?",
                (today,)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    async def get_month_signin_count(self, user_id: str, month_prefix: str) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM signin_records WHERE user_id = ? AND signin_date LIKE ?",
                (user_id, f"{month_prefix}%")
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    async def get_inventory(self, user_id: str) -> Dict[str, int]:
        items = {}
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT item_id, quantity FROM inventory WHERE user_id = ?", (user_id,)
            ) as cursor:
                async for row in cursor:
                    items[row[0]] = row[1]
        return items

    async def add_item(self, user_id: str, item_id: str, quantity: int = 1) -> bool:
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
        try:
            async with aiosqlite.connect(self.db_path) as db:
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
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT quantity FROM inventory WHERE user_id = ? AND item_id = ?",
                (user_id, item_id)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    async def check_daily_purchase(self, user_id: str, item_id: str, today: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT 1 FROM daily_purchases WHERE user_id = ? AND item_id = ? AND purchase_date = ?",
                (user_id, item_id, today)
            ) as cursor:
                row = await cursor.fetchone()
                return row is not None

    async def record_daily_purchase(self, user_id: str, item_id: str, today: str) -> bool:
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

    async def add_transfer(self, transfer: TransferRecord) -> bool:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    INSERT INTO transfers (from_user, to_user, amount, fee, transfer_time)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    transfer.from_user, transfer.to_user,
                    transfer.amount, transfer.fee, transfer.transfer_time,
                ))
                await db.commit()
            return True
        except Exception as e:
            logger.error(f"添加转账记录失败: {e}")
            return False

    async def get_transfer_history(self, user_id: str, limit: int = 20) -> List[TransferRecord]:
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
                        id=data["id"], from_user=data["from_user"],
                        to_user=data["to_user"], amount=data["amount"],
                        fee=data["fee"], transfer_time=data["transfer_time"],
                    ))
        return records

    async def get_rankboard(self, limit: int = 10) -> List[Tuple[str, UserData]]:
        users = []
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM users ORDER BY total_points DESC LIMIT ?", (limit,)
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
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT rank FROM (
                    SELECT user_id, ROW_NUMBER() OVER (ORDER BY total_points DESC) as rank
                    FROM users
                ) WHERE user_id = ?
            """, (user_id,)) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else -1

    async def get_global_stats(self, today: str) -> GlobalStats:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM users") as cursor:
                total_users = (await cursor.fetchone())[0]
            async with db.execute(
                "SELECT COUNT(DISTINCT user_id) FROM signin_records WHERE signin_date = ?",
                (today,)
            ) as cursor:
                today_signin = (await cursor.fetchone())[0]
            async with db.execute("SELECT COALESCE(SUM(total_points), 0) FROM users") as cursor:
                total_points = (await cursor.fetchone())[0]
            seven_days_ago = (datetime.strptime(today, "%Y-%m-%d") - __import__("datetime").timedelta(days=7)).strftime("%Y-%m-%d")
            async with db.execute(
                "SELECT COUNT(DISTINCT user_id) FROM signin_records WHERE signin_date >= ?",
                (seven_days_ago,)
            ) as cursor:
                active_7d = (await cursor.fetchone())[0]
            thirty_days_ago = (datetime.strptime(today, "%Y-%m-%d") - __import__("datetime").timedelta(days=30)).strftime("%Y-%m-%d")
            async with db.execute(
                "SELECT COUNT(DISTINCT user_id) FROM signin_records WHERE signin_date >= ?",
                (thirty_days_ago,)
            ) as cursor:
                active_30d = (await cursor.fetchone())[0]
        return GlobalStats(
            total_users=total_users, today_signin=today_signin,
            total_points=total_points, active_7d=active_7d, active_30d=active_30d,
        )

    async def reset_all_data(self) -> bool:
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
