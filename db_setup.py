"""Database bootstrap: create tables, add new columns to older databases, built-in roles,
role back-fill for existing users and the default Super Admin.

Runs on every start-up and is idempotent. For larger schema changes in production, adopt
Flask-Migrate (Alembic); this light upgrader only ADDs missing columns.
"""
from sqlalchemy import inspect, literal, text

from models import SYSTEM_ROLES, Role, User, db


def upgrade_schema():
    """Create missing tables, then ALTER TABLE ... ADD COLUMN for columns that older
    databases don't have yet (works on SQLite, MySQL and PostgreSQL)."""
    db.create_all()
    engine = db.engine
    dialect = engine.dialect
    insp = inspect(engine)
    quote = dialect.identifier_preparer.quote
    added = []
    with engine.begin() as conn:
        for table in db.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing:
                    continue
                ddl = f"ALTER TABLE {quote(table.name)} ADD COLUMN {quote(col.name)} {col.type.compile(dialect=dialect)}"
                default = col.default.arg if col.default is not None and col.default.is_scalar else None
                if default is not None:
                    lit = literal(default).compile(dialect=dialect, compile_kwargs={"literal_binds": True})
                    ddl += f" DEFAULT {lit}"
                conn.execute(text(ddl))
                added.append(f"{table.name}.{col.name}")
    return added


def ensure_system_roles():
    """Create the built-in roles if missing. Existing roles keep any permission changes made
    by admins; only Super Admin is always forced to 'all permissions'."""
    by_slug = {r.slug: r for r in Role.query.all()}
    for slug, name, is_staff, description, codes in SYSTEM_ROLES:
        role = by_slug.get(slug)
        if role is None:
            role = Role(slug=slug, name=name, is_staff=is_staff, is_system=True, description=description)
            db.session.add(role)
            if codes != ["*"]:
                role.set_codes(codes)
        role.is_system = True
    db.session.commit()


def backfill_user_roles():
    """Users created before roles existed get roles from their legacy 'role' column."""
    roles = {r.slug: r for r in Role.query.all()}
    changed = 0
    for user in User.query.filter(~User.roles.any()).all():
        if user.role == "admin":
            user.account_type = "staff"
            user.roles.append(roles["super_admin"])
        else:
            # Legacy users all received the column default 'buyer' during the upgrade, so decide
            # from what they actually did: anyone who has listed a machine becomes a seller.
            if user.account_type != "partner":
                user.account_type = "seller" if user.products.count() > 0 else "buyer"
            user.roles.append(roles[user.account_type])
        changed += 1
    if changed:
        db.session.commit()
    return changed


def ensure_default_admin(app):
    """Guarantee at least one active Super Admin so the admin panel is always reachable."""
    super_admin = Role.query.filter_by(slug="super_admin").one()
    if User.query.filter(User.roles.contains(super_admin), User.is_active.is_(True)).first():
        return
    email = app.config["DEFAULT_ADMIN_EMAIL"].lower()
    user = User.query.filter_by(email=email).first() or User(email=email)
    user.name = user.name or "Infrasetu Admin"
    user.phone = user.phone or "9876500000"
    user.account_type, user.role, user.is_active = "staff", "admin", True
    user.failed_logins, user.locked_until = 0, None
    if super_admin not in user.roles:
        user.roles.append(super_admin)
    user.set_password(app.config["DEFAULT_ADMIN_PASSWORD"])
    db.session.add(user)
    db.session.commit()
    app.logger.warning("Created default Super Admin %s — change the password after first login.", email)


def bootstrap(app):
    added = upgrade_schema()
    if added:
        app.logger.warning("Database upgraded, added columns: %s", ", ".join(added))
    ensure_system_roles()
    backfill_user_roles()
    ensure_default_admin(app)
