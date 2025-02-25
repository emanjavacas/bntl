
import logging

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from jinja2 import Environment, FileSystemLoader
from humanize import naturaltime

from bntl.settings import settings

logger = logging.getLogger(__name__)


jinja_env = Environment(loader=FileSystemLoader('static/templates/email'))


def send_email(email: str, subject: str, msg: str):
    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = settings.MAIL_FROM
    message["To"] = email
    part = MIMEText(msg, "html")
    message.attach(part)
    server = smtplib.SMTP(settings.MAIL_SERVER, settings.MAIL_PORT)
    server.sendmail(settings.MAIL_FROM, email, message.as_string())


def send_verification_code(email: str, code: str):
    template = jinja_env.get_template(
        'verification.html'
    ).render(
        {"code": code, 
         "expiration": naturaltime(settings.VERIFICATION_TOKEN_TIME, future=True)})
    send_email(email, "BNTL verification code", template)


if __name__ == "__main__":
    send_verification_code("enrique.manjavacas@gmail.com", "1234")