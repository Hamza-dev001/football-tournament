import os

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "supersecretkey")

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