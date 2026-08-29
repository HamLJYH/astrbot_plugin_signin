"""
AstrBot 签到插件 - 装饰器工具模块 

版本: 2.0.1
"""

import functools
import asyncio
from typing import Callable, Any, AsyncGenerator

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent

from ..core.constants import MessageEmoji


def handle_errors(func: Callable) -> Callable:
    """统一错误处理装饰器"""
    @functools.wraps(func)
    async def wrapper(self, event: AstrMessageEvent, *args, **kwargs):
        try:
            if hasattr(func, "__code__") and func.__code__.co_flags & 0x200:
                async for result in func(self, event, *args, **kwargs):
                    yield result
            else:
                result = await func(self, event, *args, **kwargs)
                if result is not None:
                    yield result
        except ValueError as e:
            logger.warning(f"[{func.__name__}] 参数错误: {e}")
            yield event.plain_result(f"{MessageEmoji.ERROR} 参数错误: {str(e)}")
        except KeyError as e:
            logger.warning(f"[{func.__name__}] 数据缺失: {e}")
            yield event.plain_result(f"{MessageEmoji.ERROR} 操作失败: 数据缺失")
        except PermissionError as e:
            logger.error(f"[{func.__name__}] 文件权限错误: {e}")
            yield event.plain_result(f"{MessageEmoji.ERROR} 数据保存失败，请检查文件权限")
        except asyncio.TimeoutError:
            logger.error(f"[{func.__name__}] 操作超时")
            yield event.plain_result(f"{MessageEmoji.ERROR} 操作超时，请稍后重试")
        except Exception as e:
            error_type = type(e).__name__
            logger.error(f"[{func.__name__}] 执行失败 [{error_type}]: {e}", exc_info=True)
            yield event.plain_result(f"{MessageEmoji.ERROR} 操作失败，请稍后重试")
    return wrapper
