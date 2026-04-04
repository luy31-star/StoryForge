import logging
import aiosmtplib
from email.message import EmailMessage
from app.core.config import settings

logger = logging.getLogger(__name__)

async def send_email_async(subject: str, to_email: str, content: str):
    """
    异步发送邮件（HTML 格式）。
    """
    message = EmailMessage()
    message["From"] = settings.mail_from
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(content, subtype="html")

    try:
        # aiosmtplib 的 use_tls=True 对应 SSL (通常 465 端口)
        # start_tls=True 对应 STARTTLS (通常 587/25 端口)
        await aiosmtplib.send(
            message,
            hostname=settings.mail_server,
            port=settings.mail_port,
            username=settings.mail_username,
            password=settings.mail_password,
            use_tls=settings.mail_use_ssl, 
            start_tls=settings.mail_use_tls,
        )
        logger.info(f"Email sent successfully to {to_email}")
    except Exception as e:
        logger.exception(f"Failed to send email to {to_email}")
        raise e

async def send_otp_email(email: str, otp: str):
    """
    发送验证码邮件。
    """
    subject = f"【StoryForge】您的注册验证码：{otp}"
    content = f"""
    <html>
        <body>
            <div style="max-width: 600px; margin: 20px auto; padding: 20px; border: 1px solid #eee; border-radius: 10px; font-family: sans-serif;">
                <h2 style="color: #333;">欢迎注册 StoryForge</h2>
                <p>您正在尝试使用此邮箱注册/绑定账号。</p>
                <p style="font-size: 18px; font-weight: bold; color: #4A90E2; background: #f0f7ff; padding: 10px; display: inline-block; border-radius: 5px;">
                    您的验证码为：{otp}
                </p>
                <p style="color: #666; font-size: 14px;">该验证码有效期为 {settings.otp_expire_minutes} 分钟。若非本人操作，请忽略此邮件。</p>
                <hr style="border: 0; border-top: 1px solid #eee; margin: 20px 0;">
                <p style="color: #999; font-size: 12px;">© 2024 StoryForge Team. All rights reserved.</p>
            </div>
        </body>
    </html>
    """
    await send_email_async(subject, email, content)
