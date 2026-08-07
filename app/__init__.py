from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
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

    # Create tables + default admin
    with app.app_context():
        db.create_all()

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