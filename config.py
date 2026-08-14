import os

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "supersecretkey")

    # WhatsApp is deliberately opt-in.  The notification service remains a
    # no-op when any required setting is absent.
    WHATSAPP_ACCESS_TOKEN = os.environ.get("WHATSAPP_ACCESS_TOKEN")
    WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
    WHATSAPP_RECIPIENTS = os.environ.get("WHATSAPP_RECIPIENTS")
    WHATSAPP_GRAPH_API_VERSION = os.environ.get("WHATSAPP_GRAPH_API_VERSION")

    DATABASE_URL = os.environ.get("DATABASE_URL")

    if DATABASE_URL:
        if DATABASE_URL.startswith("postgres://"):
            DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

        SQLALCHEMY_DATABASE_URI = DATABASE_URL
    else:
        # Use absolute path for local SQLite
        BASEDIR = os.path.abspath(os.path.dirname(__file__))
        SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(BASEDIR, "local.db")

    SQLALCHEMY_TRACK_MODIFICATIONS = False
