import ipaddress
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def validate_mail_config(config):
    server = (config.get("MAIL_SERVER") or "localhost").strip().lower()
    local_servers = {"localhost"}
    try:
        is_local = server in local_servers or ipaddress.ip_address(server).is_loopback
    except ValueError:
        is_local = server in local_servers

    if (
        not is_local
        and not config.get("MAIL_USE_TLS")
        and not config.get("MAIL_USE_SSL")
        and not config.get("MAIL_SUPPRESS_SEND")
        and not config.get("TESTING")
    ):
        raise ValueError(
            "Remote SMTP requires encryption: set MAIL_USE_TLS=true or MAIL_USE_SSL=true."
        )

    if config.get("MAIL_USE_TLS") and config.get("MAIL_USE_SSL"):
        raise ValueError("Configure only one SMTP encryption mode: TLS or SSL.")


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY") or os.urandom(32)
    DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
    DB_PORT = int(os.getenv("DB_PORT", "3306"))
    DB_USER = os.getenv("DB_USER", "root")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "")
    DB_NAME = os.getenv("DB_NAME", "hbp_management_system")
    MAIL_SERVER = os.getenv("MAIL_SERVER", "localhost")
    MAIL_PORT = int(os.getenv("MAIL_PORT", "25"))
    MAIL_USERNAME = os.getenv("MAIL_USERNAME")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "false").lower() == "true"
    MAIL_USE_SSL = os.getenv("MAIL_USE_SSL", "false").lower() == "true"
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER")
