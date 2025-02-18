
from fastapi_mail import ConnectionConfig, FastMail, MessageSchema, MessageType
from jinja2 import Environment, FileSystemLoader
from humanize import naturaltime

from bntl.settings import settings


conf = ConnectionConfig(
    MAIL_SERVER = settings.MAIL_SERVER,
    MAIL_USERNAME = settings.MAIL_USERNAME,
    MAIL_PASSWORD = settings.MAIL_PASSWORD,
    MAIL_FROM = settings.MAIL_FROM,
    MAIL_PORT = settings.MAIL_PORT,
    MAIL_STARTTLS = True,
    MAIL_SSL_TLS = False)


jinja_env = Environment(loader=FileSystemLoader('static/templates/email'))


async def send_email(email: str, subject: str, msg: str):
    message = MessageSchema(
        subject=subject,
        recipients=[email],
        body=msg,
        subtype=MessageType.html)

    await FastMail(conf).send_message(message)


async def send_verification_code(email: str, code: str):
    template = jinja_env.get_template(
        'verification.html'
    ).render(
        {"code": code, 
         "expiration": naturaltime(settings.VERIFICATION_TOKEN_TIME, future=True)})
    await send_email(email, "BNTL verification code", template)


if __name__ == "__main__":
    import asyncio
    asyncio.run(send_verification_code("enrique.manjavacas@gmail.com", "1234"))