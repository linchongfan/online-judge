import smtplib
from email.message import EmailMessage
from pathlib import Path

from app.core.config import get_settings


class Mailer:
    def send_reset_code(self, recipient: str, code: str) -> None:
        settings = get_settings()
        if settings.smtp_host:
            message = EmailMessage()
            message["Subject"] = "新保研密码重置验证码"
            message["From"] = settings.smtp_from
            message["To"] = recipient
            message.set_content(f"您的验证码是 {code}，10 分钟内有效。若非本人操作，请忽略本邮件。")
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
                if settings.smtp_use_tls:
                    smtp.starttls()
                if settings.smtp_username:
                    smtp.login(settings.smtp_username, settings.smtp_password)
                smtp.send_message(message)
            return
        if settings.is_production:
            raise RuntimeError("SMTP is not configured")
        # Development uses an explicit outbox directory; credentials never enter application logs.
        outbox = settings.storage_root / "mail_outbox"
        outbox.mkdir(parents=True, exist_ok=True)
        safe_name = "".join(char for char in recipient if char.isalnum() or char in "@._-")
        Path(outbox / f"{safe_name}.txt").write_text(
            f"To: {recipient}\nSubject: 新保研密码重置验证码\n\n验证码：{code}（10 分钟内有效）\n",
            encoding="utf-8",
        )


mailer = Mailer()
