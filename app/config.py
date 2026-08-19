import os
from urllib.parse import quote_plus

from dotenv import load_dotenv

load_dotenv()


class Config:
    DATABASE_URL = os.environ.get("DATABASE_URL")
    if not DATABASE_URL:
        postgres_user = os.environ.get("POSTGRES_USER", "postgres")
        postgres_password = os.environ.get("POSTGRES_PASSWORD") or "Shadow123"
        postgres_host = os.environ.get("POSTGRES_HOST", "localhost")
        postgres_port = os.environ.get("POSTGRES_PORT", "5432")
        postgres_database = os.environ.get("POSTGRES_DB", "AgriDirect")

        credentials = postgres_user
        if postgres_password:
            credentials += f":{quote_plus(postgres_password)}"

        DATABASE_URL = (
            f"postgresql+psycopg2://{credentials}@"
            f"{postgres_host}:{postgres_port}/{postgres_database}"
        )

    SQLALCHEMY_DATABASE_URI = DATABASE_URL
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SECRET_KEY = os.environ.get("SECRET_KEY", "change-this-secret-key")
    JWT_SECRET = os.environ.get("JWT_SECRET", "change-this-jwt-secret")

    MAIL_SERVER = os.environ.get("MAIL_SERVER", "localhost")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "true").lower() in {"1", "true", "yes", "on"}
    MAIL_USE_SSL = os.environ.get("MAIL_USE_SSL", "false").lower() in {"1", "true", "yes", "on"}
