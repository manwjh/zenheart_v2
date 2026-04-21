import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Optional

import aiosmtplib

logger = logging.getLogger(__name__)


class SMTPService:
    """SMTP client for providers such as Aliyun Direct Mail (smtpdm.aliyun.com)."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        from_email: str,
        from_name: str = "ZenHeart",
        timeout: int = 10,
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.from_email = from_email
        self.from_name = from_name.strip()
        self.use_ssl = port == 465
        self.timeout = timeout

        logger.info(
            "SMTP initialized: %s:%s (implicit SSL: %s)",
            host,
            port,
            self.use_ssl,
        )

    def _from_header(self) -> str:
        if self.from_name:
            return formataddr((self.from_name, self.from_email))
        return self.from_email

    async def send_email(
        self,
        to_email: str,
        subject: str,
        body_html: str,
        body_text: Optional[str] = None,
        from_name: Optional[str] = None,
    ) -> tuple[bool, str, Optional[str]]:
        try:
            message = MIMEMultipart("alternative")
            message["Subject"] = subject
            if from_name:
                message["From"] = formataddr((from_name, self.from_email))
            else:
                message["From"] = self._from_header()
            message["To"] = to_email

            if body_text:
                message.attach(MIMEText(body_text, "plain", "utf-8"))
            message.attach(MIMEText(body_html, "html", "utf-8"))

            if self.use_ssl:
                async with aiosmtplib.SMTP(
                    hostname=self.host,
                    port=self.port,
                    use_tls=True,
                    timeout=self.timeout,
                ) as smtp:
                    await smtp.login(self.username, self.password)
                    await smtp.send_message(message)
            else:
                async with aiosmtplib.SMTP(
                    hostname=self.host,
                    port=self.port,
                    timeout=self.timeout,
                    start_tls=True,
                ) as smtp:
                    await smtp.login(self.username, self.password)
                    await smtp.send_message(message)

            logger.info("Email sent to %s", to_email)
            return True, "Email sent successfully", message.get("Message-ID")

        except aiosmtplib.SMTPException as e:
            err = f"SMTP error: {e}"
            logger.error("Send failed to %s: %s", to_email, err)
            return False, err, None
        except Exception as e:
            err = f"Unexpected error: {e}"
            logger.error("Send failed to %s: %s", to_email, err)
            return False, err, None

    async def test_connection(self) -> bool:
        try:
            if self.use_ssl:
                async with aiosmtplib.SMTP(
                    hostname=self.host,
                    port=self.port,
                    use_tls=True,
                    timeout=self.timeout,
                ) as smtp:
                    await smtp.login(self.username, self.password)
            else:
                async with aiosmtplib.SMTP(
                    hostname=self.host,
                    port=self.port,
                    timeout=self.timeout,
                    start_tls=True,
                ) as smtp:
                    await smtp.login(self.username, self.password)
            return True
        except Exception as e:
            logger.error("SMTP connection test failed: %s", e)
            return False
