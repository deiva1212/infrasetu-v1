"""Admin: user management, role & permission management and the audit log.

Escalation guards:
  * assigning or removing a *staff* role needs roles.manage (users.manage alone is not enough)
  * nobody can change their own roles or suspend/delete themselves
  * the last active Super Admin can't lose that role or be suspended
  * Super Admin's permissions are fixed (all); built-in roles can't be deleted
"""
import secrets
import string
from datetime import datetime

from flask import abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import func, or_

from admin import _page, bp
from models import (ACCOUNT_TYPES, BUYER_TYPES, INDIAN_STATES, MARKETPLACE_PERMISSIONS, PERMISSIONS,
                    SELLER_TYPES, VERIFICATION_STATUSES, AuditLog, Enquiry, PartnerProfile, Product, Role,
                    User, db, user_roles)
from utils import (FormErrors, audit, get_choice, get_str, permission_required, slugify,
                   validate_email, validate_gstin, validate_pan, validate_phone)


def _temp_password():
    alphabet = string.ascii_letters + string.digits
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(10))
        if any(c.isdigit() for c in pw) and any(c.isalpha() for c in pw):
            return pw


def _active_super_admins():
    role = Role.query.filter_by(slug="super_admin").one()
    return User.query.filter(User.roles.contains(role), User.is_active.is_(True)).count()


def _assignable_roles():
    """Roles the current admin may assign: marketplace roles with users.manage; staff roles need roles.manage."""
    roles = Role.query.order_by(Role.is_staff.desc(), Role.name).all()
    if g.user.has_permission("roles.manage"):
        return roles
    return [r for r in roles if not r.is_staff]


# ================================================================== users
@bp.route("/users")
@permission_required("users.view")
def users():
    a = request.args
    q = User.query
    if a.get("q"):
        t = f"%{a['q'].strip()}%"
        q = q.filter(or_(User.name.ilike(t), User.email.ilike(t), User.phone.ilike(t), User.company.ilike(t),
                         User.gstin.ilike(t)))
    if a.get("type") in ACCOUNT_TYPES:
        q = q.filter(User.account_type == a["type"])
    if a.get("role", "").isdigit():
        q = q.filter(User.roles.any(Role.id == int(a["role"])))
    if a.get("kyc") in VERIFICATION_STATUSES:
        q = q.filter(User.verification_status == a["kyc"])
    status = a.get("status")
    if status == "active":
        q = q.filter(User.is_active.is_(True))
    elif status == "suspended":
        q = q.filter(User.is_active.is_(False))
    elif status == "locked":
        q = q.filter(User.locked_until > datetime.utcnow())
    counts = dict(db.session.query(Product.user_id, func.count(Product.id)).group_by(Product.user_id).all())
    type_counts = dict(db.session.query(User.account_type, func.count(User.id)).group_by(User.account_type).all())
    kyc_pending = User.query.filter_by(verification_status="pending").count()
    return render_template("admin/users.html", page=_page(q.order_by(User.created_at.desc())), counts=counts,
                           roles=Role.query.order_by(Role.name).all(), type_counts=type_counts,
                           kyc_pending=kyc_pending)


def _apply_user_form(u, f, errors, creating=False):
    u.name = get_str(f, "name", errors, "Full name", max_len=120, min_len=2)
    if creating:
        email = validate_email(get_str(f, "email", errors, "Email", max_len=160), "email", errors)
        if email and "email" not in errors and User.query.filter_by(email=email).first():
            errors.add("email", "A user with this email already exists.")
        u.email = email
    phone = validate_phone(get_str(f, "phone", errors, "Mobile number", max_len=20), "phone", errors)
    if phone and "phone" not in errors and User.query.filter(User.phone == phone, User.id != (u.id or 0)).first():
        errors.add("phone", "This mobile number is used by another account.")
    u.phone = phone
    u.account_type = get_choice(f, "account_type", errors, "Account type", list(ACCOUNT_TYPES))
    btypes = BUYER_TYPES if u.account_type == "buyer" else SELLER_TYPES if u.account_type == "seller" else []
    bt = (f.get("business_type") or "").strip()
    u.business_type = bt if bt in btypes else None
    u.company = get_str(f, "company", errors, "Company", required=u.account_type == "partner", max_len=160)
    u.state = get_choice(f, "state", errors, "State", INDIAN_STATES, required=False)
    u.city = get_str(f, "city", errors, "City", required=False, max_len=80)
    u.gstin = validate_gstin(f.get("gstin"), errors, required=u.account_type == "partner")
    u.pan = validate_pan(f.get("pan"), errors, gstin=u.gstin)
    if u.account_type == "partner":
        from models import PARTNER_TYPES
        ptype = get_choice(f, "partner_type", errors, "Partner type", PARTNER_TYPES)
        if u.partner_profile is None:
            u.partner_profile = PartnerProfile(partner_type=ptype or PARTNER_TYPES[0], service_states="All India",
                                               description="")
        elif ptype:
            u.partner_profile.partner_type = ptype


def _set_roles(u, role_ids, errors):
    """Apply a new role set to u, enforcing the escalation guards. Returns (added, removed) names."""
    wanted = {r.id: r for r in Role.query.filter(Role.id.in_(role_ids)).all()} if role_ids else {}
    current = {r.id: r for r in u.roles}
    changed = [r for rid, r in {**wanted, **current}.items() if (rid in wanted) != (rid in current)]
    if any(r.is_staff for r in changed) and not g.user.has_permission("roles.manage"):
        errors.add("roles", "You need the 'roles.manage' permission to grant or remove staff roles.")
    if u.id and u.id == g.user.id and changed:
        errors.add("roles", "You cannot change your own roles. Ask another administrator.")
    sa = Role.query.filter_by(slug="super_admin").one()
    if any(r.id == sa.id for r in changed) and not g.user.is_super_admin:
        errors.add("roles", "Only a Super Admin can grant or remove the Super Admin role.")
    if u.id and sa.id in current and sa.id not in wanted and u.is_active and _active_super_admins() <= 1:
        errors.add("roles", "This is the last active Super Admin; assign Super Admin to someone else first.")
    if not wanted:
        errors.add("roles", "Assign at least one role.")
    if errors:
        return [], []
    added = [r.name for r in wanted.values() if r.id not in current]
    removed = [r.name for r in current.values() if r.id not in wanted]
    u.roles = sorted(wanted.values(), key=lambda r: r.name)
    return added, removed


@bp.route("/users/new", methods=["GET", "POST"])
@permission_required("users.manage")
def user_new():
    errors = FormErrors()
    u = User(account_type=request.values.get("type", "buyer"), is_active=True)
    if request.method == "POST":
        f = request.form
        with db.session.no_autoflush:
            _apply_user_form(u, f, errors, creating=True)
            role_ids = [int(i) for i in f.getlist("roles") if i.isdigit()]
            pw = (f.get("password") or "").strip()
            if pw and (len(pw) < 8 or pw.isalpha() or pw.isdigit()):
                errors.add("password", "Password must be 8+ characters with letters and numbers.")
            if not errors:
                _set_roles(u, role_ids, errors)
        if not errors:
            temp = pw or _temp_password()
            u.set_password(temp)
            u.role = "admin" if any(r.is_staff for r in u.roles) else "user"
            if u.account_type == "partner":
                u.verification_status = "pending"
            db.session.add(u)
            db.session.flush()
            audit("user.create", u, f"{u.email} as {u.account_type}; roles: {', '.join(r.name for r in u.roles)}")
            db.session.commit()
            flash(f"User {u.email} created." + ("" if pw else f" Temporary password: {temp} — share it securely; "
                                                  "the user should change it after logging in."), "success")
            return redirect(url_for("admin.user_detail", uid=u.id))
        db.session.rollback()
        flash("Please fix the errors below.", "danger")
        form = f.to_dict()
        form["roles"] = f.getlist("roles")
    else:
        default_role = Role.query.filter_by(slug=u.account_type).first()
        form = {"account_type": u.account_type, "roles": [str(default_role.id)] if default_role else []}
    return render_template("admin/user_form.html", u=None, form=form, errors=errors, roles=_assignable_roles())


@bp.route("/users/<int:uid>")
@permission_required("users.view")
def user_detail(uid):
    u = db.session.get(User, uid) or abort(404)
    listings = u.products.order_by(Product.created_at.desc()).limit(10).all()
    total_listings = u.products.count()
    sent = Enquiry.query.filter_by(user_id=u.id).count()
    history = (AuditLog.query.filter(or_(
        (AuditLog.target_type == "user") & (AuditLog.target_id == u.id), AuditLog.actor_id == u.id))
        .order_by(AuditLog.created_at.desc()).limit(25).all())
    form = {"name": u.name, "phone": u.phone, "account_type": u.account_type, "business_type": u.business_type or "",
            "company": u.company or "", "state": u.state or "", "city": u.city or "", "gstin": u.gstin or "",
            "pan": u.pan or "", "partner_type": u.partner_profile.partner_type if u.partner_profile else ""}
    return render_template("admin/user_detail.html", u=u, form=form, errors={}, listings=listings,
                           total_listings=total_listings, sent=sent, history=history,
                           all_roles=Role.query.order_by(Role.is_staff.desc(), Role.name).all(),
                           assignable={r.id for r in _assignable_roles()})


@bp.route("/users/<int:uid>/edit", methods=["POST"])
@permission_required("users.manage")
def user_edit(uid):
    u = db.session.get(User, uid) or abort(404)
    if u.is_super_admin and not g.user.is_super_admin:
        abort(403)  # only a Super Admin can edit a Super Admin
    errors = FormErrors()
    before = (u.account_type, u.gstin, u.pan)
    with db.session.no_autoflush:
        _apply_user_form(u, request.form, errors)
    if errors:
        db.session.rollback()
        flash("Not saved: " + " ".join(errors.values()), "danger")
        return redirect(url_for("admin.user_detail", uid=uid))
    if (u.gstin, u.pan) != before[1:] and (u.gstin or u.pan) and u.verification_status == "verified":
        u.verification_status = "pending"
    audit("user.update", u, f"type {before[0]} → {u.account_type}" if before[0] != u.account_type else "profile")
    db.session.commit()
    flash("User details saved.", "success")
    return redirect(url_for("admin.user_detail", uid=uid))


@bp.route("/users/<int:uid>/roles", methods=["POST"])
@permission_required("users.manage")
def user_roles_update(uid):
    u = db.session.get(User, uid) or abort(404)
    errors = FormErrors()
    role_ids = [int(i) for i in request.form.getlist("roles") if i.isdigit()]
    added, removed = _set_roles(u, role_ids, errors)
    if errors:
        db.session.rollback()
        flash(" ".join(errors.values()), "danger")
    else:
        u.role = "admin" if any(r.is_staff for r in u.roles) else "user"
        audit("user.roles", u, f"added: {', '.join(added) or '—'}; removed: {', '.join(removed) or '—'}")
        db.session.commit()
        flash("Roles updated." if (added or removed) else "No role changes.", "success")
    return redirect(url_for("admin.user_detail", uid=uid) + "#roles")


@bp.route("/users/<int:uid>/status", methods=["POST"])
@permission_required("users.manage")
def user_status(uid):
    u = db.session.get(User, uid) or abort(404)
    action = request.form.get("action")
    if u.id == g.user.id:
        flash("You cannot suspend or unlock your own account here.", "warning")
    elif u.is_super_admin and not g.user.is_super_admin:
        abort(403)
    elif action == "suspend":
        if u.is_super_admin and _active_super_admins() <= 1:
            flash("Cannot suspend the last active Super Admin.", "danger")
        else:
            u.is_active = False
            audit("user.suspend", u, request.form.get("reason") or None)
            db.session.commit()
            flash(f"{u.email} suspended. They can no longer log in.", "success")
    elif action == "activate":
        u.is_active = True
        audit("user.activate", u)
        db.session.commit()
        flash(f"{u.email} re-activated.", "success")
    elif action == "unlock":
        u.failed_logins, u.locked_until = 0, None
        audit("user.unlock", u)
        db.session.commit()
        flash(f"{u.email} unlocked.", "success")
    else:
        abort(400)
    return redirect(request.referrer or url_for("admin.user_detail", uid=uid))


@bp.route("/users/<int:uid>/password", methods=["POST"])
@permission_required("users.manage")
def user_password(uid):
    u = db.session.get(User, uid) or abort(404)
    if u.id == g.user.id:
        flash("Use 'My account → Password' to change your own password.", "warning")
        return redirect(url_for("admin.user_detail", uid=uid))
    if u.is_super_admin and not g.user.is_super_admin:
        abort(403)
    temp = _temp_password()
    u.set_password(temp)
    u.failed_logins, u.locked_until = 0, None
    audit("user.password_reset", u, "Temporary password issued by admin")
    db.session.commit()
    flash(f"Temporary password for {u.email}: {temp} — share it securely. Their old password and any "
          "reset links no longer work.", "success")
    return redirect(url_for("admin.user_detail", uid=uid))


@bp.route("/users/<int:uid>/verify", methods=["POST"])
@permission_required("users.verify")
def user_verify(uid):
    u = db.session.get(User, uid) or abort(404)
    status = request.form.get("status")
    note = (request.form.get("note") or "").strip()[:255] or None
    if status not in ("verified", "rejected", "pending"):
        abort(400)
    if status == "rejected" and not note:
        flash("Please give a reason when rejecting KYC — the user will see it.", "danger")
        return redirect(url_for("admin.user_detail", uid=uid) + "#kyc")
    if status == "verified" and not (u.gstin or u.pan):
        flash("Cannot verify: the user has no GSTIN or PAN on file.", "danger")
        return redirect(url_for("admin.user_detail", uid=uid) + "#kyc")
    u.verification_status, u.verification_note = status, note
    u.verified_at = datetime.utcnow() if status == "verified" else None
    u.verified_by_id = g.user.id if status == "verified" else None
    audit(f"user.kyc_{status}", u, note)
    db.session.commit()
    flash(f"KYC for {u.display_company} marked {VERIFICATION_STATUSES[status].lower()}.", "success")
    return redirect(request.form.get("back") or url_for("admin.user_detail", uid=uid))


@bp.route("/users/<int:uid>/delete", methods=["POST"])
@permission_required("users.manage")
def user_delete(uid):
    u = db.session.get(User, uid) or abort(404)
    if u.id == g.user.id or u.is_super_admin:
        flash("This account cannot be deleted.", "danger")
        return redirect(url_for("admin.user_detail", uid=uid))
    if u.products.count() or Enquiry.query.filter_by(user_id=u.id).count():
        flash("This user has listings or enquiries. Suspend the account instead of deleting it.", "danger")
        return redirect(url_for("admin.user_detail", uid=uid))
    audit("user.delete", u, f"{u.email} ({u.account_type})")
    AuditLog.query.filter_by(actor_id=u.id).update({"actor_id": None})
    db.session.delete(u)
    db.session.commit()
    flash("User deleted.", "success")
    return redirect(url_for("admin.users"))


# ================================================================== roles
@bp.route("/roles")
@permission_required("roles.manage")
def roles():
    items = Role.query.order_by(Role.is_staff.desc(), Role.is_system.desc(), Role.name).all()
    counts = dict(db.session.query(user_roles.c.role_id, func.count(user_roles.c.user_id))
                  .group_by(user_roles.c.role_id).all())
    return render_template("admin/roles.html", items=items, counts=counts)


@bp.route("/roles/new", methods=["GET", "POST"])
@bp.route("/roles/<int:rid>/edit", methods=["GET", "POST"])
@permission_required("roles.manage")
def role_form(rid=None):
    role = db.session.get(Role, rid) if rid else Role(is_staff=True, is_system=False)
    if rid and not role:
        abort(404)
    errors = FormErrors()
    locked = role.slug == "super_admin"
    if request.method == "POST":
        f = request.form
        with db.session.no_autoflush:
            name = get_str(f, "name", errors, "Role name", max_len=80, min_len=3)
            if not role.is_system:
                role.name = name
                role.is_staff = f.get("is_staff") == "1"
            elif name and name != role.name:
                role.name = name  # built-in roles may be renamed but not re-typed
            role.description = get_str(f, "description", errors, "Description", required=False, max_len=255)
            if role.name and Role.query.filter(func.lower(Role.name) == role.name.lower(),
                                               Role.id != (role.id or 0)).first():
                errors.add("name", "Another role already has this name.")
            codes = [c for c in f.getlist("permissions") if c in PERMISSIONS]
            if not locked:
                if role.is_staff:
                    codes = set(codes) | {"admin.access"}
                elif set(codes) - MARKETPLACE_PERMISSIONS:
                    errors.add("permissions", "Marketplace roles can only hold marketplace permissions. "
                                              "Tick 'Staff role' to grant admin-panel permissions.")
                if not codes:
                    errors.add("permissions", "Choose at least one permission.")
            # Don't let an admin strip roles.manage from a role that is their only source of it.
            own_role = role.id is not None and role in g.user.roles
            other_source = any(r.id != role.id and "roles.manage" in r.codes for r in g.user.roles)
            if own_role and not locked and "roles.manage" in role.codes and "roles.manage" not in codes \
                    and not other_source:
                errors.add("permissions", "You would lose 'roles.manage' yourself. Ask another administrator.")
        if not errors:
            if not role.id:
                base = slugify(role.name).replace("-", "_")[:50]
                slug, n = base, 2
                while Role.query.filter_by(slug=slug).first():
                    slug, n = f"{base}_{n}", n + 1
                role.slug = slug
                db.session.add(role)
            before = sorted(role.codes)
            if not locked:
                role.set_codes(codes)
            db.session.flush()
            added = sorted(set(role.codes) - set(before))
            removed = sorted(set(before) - set(role.codes))
            audit("role.create" if not rid else "role.update", role,
                  f"+{', '.join(added) or '—'}; -{', '.join(removed) or '—'}")
            db.session.commit()
            flash(f"Role '{role.name}' saved.", "success")
            return redirect(url_for("admin.roles"))
        db.session.rollback()
        flash("Please fix the errors below.", "danger")
        form = {"name": f.get("name", ""), "description": f.get("description", ""),
                "is_staff": "1" if f.get("is_staff") == "1" else "", "permissions": f.getlist("permissions")}
    else:
        form = {"name": role.name or "", "description": role.description or "",
                "is_staff": "1" if role.is_staff else "", "permissions": sorted(role.codes) if role.id else ["admin.access"]}
    members = (User.query.filter(User.roles.contains(role)).order_by(User.name).limit(50).all()
               if role.id else [])
    return render_template("admin/role_form.html", role=role, form=form, errors=errors, locked=locked,
                           members=members, marketplace=MARKETPLACE_PERMISSIONS)


@bp.route("/roles/<int:rid>/delete", methods=["POST"])
@permission_required("roles.manage")
def role_delete(rid):
    role = db.session.get(Role, rid) or abort(404)
    if role.is_system:
        flash("Built-in roles cannot be deleted.", "danger")
    elif role.users:
        flash(f"'{role.name}' is assigned to {len(role.users)} user(s). Remove it from them first.", "danger")
    else:
        audit("role.delete", role, role.name)
        db.session.delete(role)
        db.session.commit()
        flash("Role deleted.", "success")
    return redirect(url_for("admin.roles"))


# ================================================================== audit
@bp.route("/audit", endpoint="audit")
@permission_required("audit.view")
def audit_log():
    q = AuditLog.query
    a = request.args
    if a.get("action"):
        q = q.filter(AuditLog.action.like(a["action"].strip() + "%"))
    if a.get("actor"):
        t = f"%{a['actor'].strip()}%"
        q = q.join(User, AuditLog.actor_id == User.id).filter(or_(User.email.ilike(t), User.name.ilike(t)))
    groups = sorted({x.split(".")[0] for (x,) in db.session.query(AuditLog.action).distinct()})
    return render_template("admin/audit.html", page=_page(q.order_by(AuditLog.created_at.desc())), groups=groups)

