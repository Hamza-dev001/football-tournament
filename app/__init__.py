from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from sqlalchemy import inspect, text
from config import Config

# ==========================================================
# EXTENSIONS
# ==========================================================

db = SQLAlchemy()
login_manager = LoginManager()

# ✅ Tell Flask-Login where login page is
login_manager.login_view = "admin.login"
login_manager.login_message = "Please log in to access this page."


# ==========================================================
# STARTUP DATABASE SCHEMA SAFETY
# ==========================================================

def ensure_title_awarded_column():
    """
    Ensure the Match.title_awarded column exists in an existing database.

    db.create_all() creates missing tables, but it does not add new
    columns to tables that already exist. Render's PostgreSQL database
    may therefore still have the older Match schema.

    This migration is intentionally:
    - additive only
    - idempotent
    - non-destructive
    """

    inspector = inspect(db.engine)

    if not inspector.has_table("match"):
        return

    columns = inspector.get_columns("match")
    column_names = {column["name"] for column in columns}

    if "title_awarded" in column_names:
        return

    with db.engine.begin() as connection:
        connection.execute(
            text(
                'ALTER TABLE "match" '
                'ADD COLUMN title_awarded BOOLEAN NOT NULL DEFAULT FALSE'
            )
        )


def ensure_notification_delivery_table():
    """Create the approved delivery table without changing existing schema."""
    inspector = inspect(db.engine)

    if inspector.has_table("notification_delivery"):
        return

    from .models import NotificationDelivery

    NotificationDelivery.__table__.create(bind=db.engine, checkfirst=True)


# ==========================================================
# APPLICATION FACTORY
# ==========================================================

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)

    # Register blueprints
    from .routes import main
    from .admin_routes import admin

    app.register_blueprint(main)
    app.register_blueprint(admin, url_prefix="/admin")

    # Create tables + repair additive legacy schema
    with app.app_context():
        # notification_delivery is created only by its explicit, idempotent
        # migration below; do not rely on create_all() for an existing DB.
        existing_tables = [
            table for table in db.metadata.tables.values()
            if table.name != "notification_delivery"
        ]
        db.metadata.create_all(bind=db.engine, tables=existing_tables)

        ensure_title_awarded_column()
        ensure_notification_delivery_table()

        from .models import User

        existing_admin = User.query.filter_by(username="admin").first()

        if not existing_admin:
            admin_user = User(username="admin")
            admin_user.set_password("HamzaSecure2026!")
            db.session.add(admin_user)
            db.session.commit()

    return app


# ==========================================================
# FLASK-LOGIN USER LOADER
# ==========================================================

from .models import User


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
