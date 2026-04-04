import redis.asyncio as redis
from app.core.config import settings

# 异步 Redis 客户端
redis_client = redis.from_url(settings.redis_url, decode_responses=True)

class OTPHelper:
    @staticmethod
    async def set_otp(email: str, otp: str, expire_minutes: int = settings.otp_expire_minutes):
        """
        在 Redis 中设置验证码。
        """
        key = f"otp:{email}"
        await redis_client.set(key, otp, ex=expire_minutes * 60)

    @staticmethod
    async def get_otp(email: str) -> str | None:
        """
        获取验证码。
        """
        key = f"otp:{email}"
        return await redis_client.get(key)

    @staticmethod
    async def delete_otp(email: str):
        """
        删除验证码。
        """
        key = f"otp:{email}"
        await redis_client.delete(key)

    @staticmethod
    async def is_too_frequent(email: str) -> bool:
        """
        检查是否过于频繁（60秒限制）。
        """
        limit_key = f"otp_limit:{email}"
        if await redis_client.get(limit_key):
            return True
        return False

    @staticmethod
    async def set_limit(email: str):
        """
        设置发送频率限制。
        """
        limit_key = f"otp_limit:{email}"
        await redis_client.set(limit_key, "1", ex=60)
