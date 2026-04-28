import redis.asyncio as redis
from app.core.config import settings

# 异步 Redis 客户端
redis_client = redis.from_url(settings.redis_url, decode_responses=True)

class OTPHelper:
    @staticmethod
    async def set_otp(
        email: str,
        otp: str,
        expire_minutes: int = settings.otp_expire_minutes,
        scene: str = "register",
    ):
        """
        在 Redis 中设置验证码。
        """
        key = f"otp:{scene}:{email}"
        await redis_client.set(key, otp, ex=expire_minutes * 60)

    @staticmethod
    async def get_otp(email: str, scene: str = "register") -> str | None:
        """
        获取验证码。
        """
        key = f"otp:{scene}:{email}"
        return await redis_client.get(key)

    @staticmethod
    async def delete_otp(email: str, scene: str = "register"):
        """
        删除验证码。
        """
        key = f"otp:{scene}:{email}"
        await redis_client.delete(key)

    @staticmethod
    async def try_lock_send_limit(
        email: str, seconds: int = 60, scene: str = "register"
    ) -> bool:
        """
        尝试获取发送锁（原子操作：检查并设置频率限制）。
        如果 60 秒内已发送过，则返回 False。
        """
        limit_key = f"otp_limit:{scene}:{email}"
        # SET NX: 仅在 key 不存在时设置成功
        locked = await redis_client.set(limit_key, "1", ex=seconds, nx=True)
        return bool(locked)

    @staticmethod
    async def unlock_send_limit(email: str, scene: str = "register"):
        """
        手动解除发送限制（通常用于邮件发送彻底失败时）。
        """
        limit_key = f"otp_limit:{scene}:{email}"
        await redis_client.delete(limit_key)
