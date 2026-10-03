import logging

from app.config import settings

logger = logging.getLogger("campus.mail")


async def send_email(to: str, subject: str, body: str) -> None:
    if settings.EMAIL_BACKEND == "console":
        logger.warning("EMAIL to=%s subject=%r\n%s", to, subject, body)
        return
    raise NotImplementedError(f"Email backend {settings.EMAIL_BACKEND!r} is not set up yet")
