import os
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-this-secret-key-in-production")

    # Any SQLAlchemy-supported SQL database works. Examples:
    #   SQLite (default):  sqlite:///infrasetu.db
    #   MySQL:             mysql+pymysql://user:pass@localhost:3306/infrasetu
    #   PostgreSQL:        postgresql+psycopg2://user:pass@localhost:5432/infrasetu
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///" + os.path.join(BASE_DIR, "infrasetu.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
    MAX_CONTENT_LENGTH = 25 * 1024 * 1024  # 25 MB per request
    ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
    MAX_IMAGES_PER_PRODUCT = 8

    # Created automatically on startup if the database has no admin user.
    DEFAULT_ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@infrasetu.in")
    DEFAULT_ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Admin@123")

    # ---- login & sessions
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"  # set 1 behind HTTPS
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)  # "Keep me signed in"
    MAX_LOGIN_ATTEMPTS = 5
    LOCKOUT_MINUTES = 15
    PASSWORD_RESET_HOURS = 1
    REQUIRE_LOGIN_TO_ENQUIRE = os.environ.get("REQUIRE_LOGIN_TO_ENQUIRE", "1") == "1"

    # ---- outgoing email (password reset). Leave MAIL_SERVER empty to only log the mail.
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "1") == "1"
    MAIL_FROM = os.environ.get("MAIL_FROM", "Infrasetu <no-reply@infrasetu.in>")
    # Show password-reset links on screen when no mail server is set. NEVER enable in production.
    SHOW_DEV_LINKS = os.environ.get("SHOW_DEV_LINKS", "0") == "1"

    ITEMS_PER_PAGE = 12
    ADMIN_ITEMS_PER_PAGE = 20
    AUTO_APPROVE_LISTINGS = os.environ.get("AUTO_APPROVE_LISTINGS", "0") == "1"
