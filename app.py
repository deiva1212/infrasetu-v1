"""Infrasetu — marketplace to buy, sell and rent heavy commercial vehicles and heavy equipment.

Run:  flask --app app run   (after `flask --app app init-db` and optionally `flask --app app seed`)
"""
import os

import click
from flask import Flask, render_template, request

from config import Config
from db_setup import bootstrap
from models import (ACCOUNT_TYPES, ATTRIBUTE_TYPES, BUYER_TYPES, CATEGORY_GROUPS, CONDITIONS,
                    ENQUIRY_STATUSES, FUEL_TYPES, INDIAN_STATES, LISTING_TYPES, OWNERSHIP,
                    PARTNER_TYPES, PERMISSION_GROUPS, PRODUCT_STATUSES, RENT_PERIODS, SELLER_TYPES,
                    USAGE_UNITS, VERIFICATION_STATUSES, Role, User, db)
from utils import can, check_csrf, csrf_token, inr, inr_short, load_current_user


def create_app(config_object=Config):
    app = Flask(__name__)
    app.config.from_object(config_object)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    db.init_app(app)

    # Create/upgrade tables, built-in roles and a Super Admin — even if `flask seed` never ran.
    with app.app_context():
        bootstrap(app)

    import admin_users  # noqa: F401  (registers user/role/audit routes on the admin blueprint)
    from accounts import bp as auth_bp
    from admin import bp as admin_bp
    from public import bp as public_bp
    app.register_blueprint(public_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")

    @app.before_request
    def _before():
        load_current_user()
        check_csrf()

    # Globals (not a context processor) so they are also visible inside imported macros.
    app.jinja_env.globals.update(
            csrf_token=csrf_token, CONDITIONS=CONDITIONS, FUEL_TYPES=FUEL_TYPES,
            INDIAN_STATES=INDIAN_STATES, LISTING_TYPES=LISTING_TYPES, OWNERSHIP=OWNERSHIP,
            RENT_PERIODS=RENT_PERIODS, PRODUCT_STATUSES=PRODUCT_STATUSES,
            ENQUIRY_STATUSES=ENQUIRY_STATUSES, CATEGORY_GROUPS=CATEGORY_GROUPS,
            USAGE_UNITS=USAGE_UNITS, ATTRIBUTE_TYPES=ATTRIBUTE_TYPES,
            GROUP_LABELS={"Commercial Vehicle": "Commercial Vehicles", "Heavy Equipment": "Heavy Equipment"},
            ACCOUNT_TYPES=ACCOUNT_TYPES, BUYER_TYPES=BUYER_TYPES, SELLER_TYPES=SELLER_TYPES,
            PARTNER_TYPES=PARTNER_TYPES, VERIFICATION_STATUSES=VERIFICATION_STATUSES,
            PERMISSION_GROUPS=PERMISSION_GROUPS,
        )

    app.jinja_env.globals["can"] = can

    @app.context_processor
    def _admin_badges():
        if request.blueprint == "admin" and can("users.verify"):
            return {"admin_kyc_pending": User.query.filter_by(verification_status="pending").count()}
        return {}

    app.jinja_env.filters["inr"] = inr
    app.jinja_env.filters["inr_short"] = inr_short

    @app.template_filter("dt")
    def _dt(value, fmt="%d %b %Y"):
        return value.strftime(fmt) if value else "—"

    @app.template_global()
    def url_with(**changes):
        from urllib.parse import urlencode
        args = request.args.to_dict(flat=True)
        args.update(changes)
        return request.path + "?" + urlencode({k: v for k, v in args.items() if v not in (None, "")})

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(413)
    def _err(e):
        return render_template("error.html", error=e), e.code

    # ----------------------------------------------------------- CLI commands
    @app.cli.command("init-db")
    def init_db():
        """Create all database tables."""
        db.create_all()
        click.echo("Database tables created.")

    @app.cli.command("seed")
    def seed_cmd():
        """Load sample categories, catalogue, users and listings."""
        from seed import seed
        seed()
        click.echo("Sample data loaded. Admin: admin@infrasetu.in / Admin@123")

    def _make_super_admin(user):
        role = Role.query.filter_by(slug="super_admin").one()
        user.account_type, user.role, user.is_active = "staff", "admin", True
        user.failed_logins, user.locked_until = 0, None
        if role not in user.roles:
            user.roles.append(role)
        db.session.add(user)

    @app.cli.command("reset-admin")
    def reset_admin():
        """Reset (or create) the default Super Admin with the default password and unlock it."""
        email = app.config["DEFAULT_ADMIN_EMAIL"].lower()
        user = User.query.filter_by(email=email).first() or User(email=email, name="Infrasetu Admin",
                                                                    phone="9876500000")
        _make_super_admin(user)
        user.set_password(app.config["DEFAULT_ADMIN_PASSWORD"])
        db.session.commit()
        click.echo(f"Admin reset. Log in with {email} / {app.config['DEFAULT_ADMIN_PASSWORD']}")

    @app.cli.command("create-admin")
    @click.option("--name", prompt=True)
    @click.option("--email", prompt=True)
    @click.option("--phone", prompt=True)
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    def create_admin(name, email, phone, password):
        """Create a Super Admin user."""
        user = User.query.filter_by(email=email.lower()).first() or User(email=email.lower())
        user.name, user.phone = name, phone
        _make_super_admin(user)
        user.set_password(password)
        db.session.commit()
        click.echo(f"Super Admin {email} ready.")

    return app


app = create_app()

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
