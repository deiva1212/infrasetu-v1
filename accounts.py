"""Login ecosystem: registration (buyer / seller / partner), login, logout, lockout,
forgot / reset password, account dashboard, profile, change password, upgrade to seller."""
import re
from datetime import datetime, timedelta

from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template, request,
                   session, url_for)
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import func

from models import (BUYER_TYPES, INDIAN_STATES, PARTNER_TYPES, SELLER_TYPES, Enquiry, PartnerProfile,
                    Product, Role, User, db)
from utils import (URL_RE, FormErrors, audit, get_choice, get_str, login_required, send_email,
                   validate_email, validate_gstin, validate_pan, validate_password, validate_phone)

bp = Blueprint("auth", __name__)

REG_TYPES = {
    "buyer": ("Buyer", "Buy or rent trucks and equipment, contact sellers, post requirements."),
    "seller": ("Seller", "Sell or rent out your vehicles and machines — owners, fleets, dealers, rental firms."),
    "partner": ("Partner", "Financiers, insurers, inspectors, transporters, dealers and service partners."),
}


def _safe_next(default):
    nxt = request.args.get("next") or request.form.get("next")
    if nxt and nxt.startswith("/") and not nxt.startswith("//") and "\\" not in nxt:
        return nxt
    return default


def _home_for(user):
    if user.is_admin:
        return url_for("admin.dashboard")
    return url_for("auth.account")


def _start_session(user, remember=False):
    session.clear()
    session["user_id"] = user.id
    session.permanent = bool(remember)
    user.failed_logins, user.locked_until = 0, None
    user.last_login_at = datetime.utcnow()


def _phone_taken(phone, exclude_id=None):
    q = User.query.filter(User.phone == phone)
    if exclude_id:
        q = q.filter(User.id != exclude_id)
    return db.session.query(q.exists()).scalar()


def _profile_fields(form, errors, acct, user=None):
    """Validate type-specific profile fields. Returns dict of User fields + partner dict."""
    data, partner = {}, None
    if acct == "buyer":
        data["business_type"] = get_choice(form, "business_type", errors, "Buyer type", BUYER_TYPES)
        data["company"] = get_str(form, "company", errors, "Company / organisation",
                                  required=data["business_type"] not in (None, "Individual"), max_len=160)
    elif acct == "seller":
        data["business_type"] = get_choice(form, "business_type", errors, "Seller type", SELLER_TYPES)
        business = data["business_type"] in ("Dealer", "Rental company")
        data["company"] = get_str(form, "company", errors, "Company / fleet name",
                                  required=data["business_type"] not in (None, "Individual owner"), max_len=160)
        data["gstin"] = validate_gstin(form.get("gstin"), errors, required=business)
        data["pan"] = validate_pan(form.get("pan"), errors, gstin=data["gstin"])
    elif acct == "partner":
        data["business_type"] = None
        data["company"] = get_str(form, "company", errors, "Registered company name", max_len=160)
        data["gstin"] = validate_gstin(form.get("gstin"), errors, required=True)
        data["pan"] = validate_pan(form.get("pan"), errors, gstin=data["gstin"])
        ptype = get_choice(form, "partner_type", errors, "Partner type", PARTNER_TYPES)
        website = get_str(form, "website", errors, "Website", required=False, max_len=200)
        if website and not URL_RE.match(website):
            errors.add("website", "Website must start with http:// or https://")
        states = [s for s in form.getlist("service_states") if s in INDIAN_STATES or s == "All India"]
        if not states:
            errors.add("service_states", "Select at least one state you serve, or All India.")
        if "All India" in states:
            states = ["All India"]
        desc = get_str(form, "description", errors, "Services offered", max_len=2000, min_len=30)
        partner = {"partner_type": ptype, "website": website, "service_states": ", ".join(states),
                   "description": desc}
    return data, partner


# --------------------------------------------------------------- register
@bp.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for("auth.account"))
    acct = request.values.get("type")
    if acct not in REG_TYPES:
        return render_template("auth/register_choose.html", types=REG_TYPES)
    f = request.form
    errors = FormErrors()
    if request.method == "POST":
        name = get_str(f, "name", errors, "Full name", max_len=120, min_len=2)
        email = validate_email(get_str(f, "email", errors, "Email", max_len=160), "email", errors)
        phone = validate_phone(get_str(f, "phone", errors, "Mobile number", max_len=20), "phone", errors)
        state = get_choice(f, "state", errors, "State", INDIAN_STATES)
        city = get_str(f, "city", errors, "City", max_len=80)
        validate_password(f.get("password", ""), f.get("confirm", ""), errors)
        if f.get("terms") != "1":
            errors.add("terms", "Please accept the terms of use and privacy policy.")
        data, partner = _profile_fields(f, errors, acct)
        if email and "email" not in errors and User.query.filter_by(email=email).first():
            errors.add("email", "An account with this email already exists. Log in instead.")
        if phone and "phone" not in errors and _phone_taken(phone):
            errors.add("phone", "This mobile number is already registered.")
        if not errors:
            u = User(name=name, email=email, phone=phone, state=state, city=city, account_type=acct, **data)
            u.set_password(f["password"])
            u.roles.append(Role.query.filter_by(slug=acct).one())
            if acct == "partner":
                u.partner_profile = PartnerProfile(**partner)
                u.verification_status = "pending"
            elif acct == "seller" and (u.gstin or u.pan):
                u.verification_status = "pending"
            db.session.add(u)
            db.session.flush()
            audit("user.register", u, f"Self-registered as {acct}", actor=u)
            _start_session(u)
            db.session.commit()
            if acct == "partner":
                flash("Welcome! Your partner account is under verification. You'll appear in the partner "
                      "directory and can post listings once our team verifies your GSTIN.", "success")
            else:
                flash(f"Welcome to Infrasetu, {u.name.split()[0]}! Your {REG_TYPES[acct][0].lower()} "
                      "account is ready.", "success")
            return redirect(_safe_next(url_for("auth.account")))
        flash("Please fix the highlighted fields.", "danger")
    return render_template("auth/register.html", acct=acct, label=REG_TYPES[acct][0], form=f,
                           errors=errors), (422 if errors else 200)


# --------------------------------------------------------------- login / logout
@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user and request.method == "GET":
        return redirect(_home_for(g.user))
    f = request.form
    errors = FormErrors()
    if request.method == "POST":
        ident = (f.get("identifier") or f.get("email") or "").strip().lower()
        pw = f.get("password", "")
        if not ident or not pw:
            errors.add("password", "Enter your email or mobile number and password.")
        else:
            if "@" in ident:
                user = User.query.filter_by(email=ident).first()
            else:
                digits = re.sub(r"\D", "", ident)[-10:]
                matches = User.query.filter_by(phone=digits).limit(2).all() if digits else []
                user = matches[0] if len(matches) == 1 else None
            cfg = current_app.config
            if user and user.is_locked:
                mins = max(1, int((user.locked_until - datetime.utcnow()).total_seconds() // 60) + 1)
                errors.add("password", f"Too many failed attempts. Try again in {mins} minute"
                                       f"{'s' if mins != 1 else ''}, or reset your password.")
            elif not user or not user.check_password(pw):
                if user:
                    user.failed_logins = (user.failed_logins or 0) + 1
                    if user.failed_logins >= cfg["MAX_LOGIN_ATTEMPTS"]:
                        user.locked_until = datetime.utcnow() + timedelta(minutes=cfg["LOCKOUT_MINUTES"])
                        user.failed_logins = 0
                        audit("auth.locked", user, f"Locked after {cfg['MAX_LOGIN_ATTEMPTS']} failed logins",
                              actor=user)
                    db.session.commit()
                errors.add("password", "Incorrect email/mobile or password.")
            elif not user.is_active:
                errors.add("password", "This account has been suspended. Please contact support.")
            else:
                _start_session(user, remember=f.get("remember") == "1")
                if user.is_admin:
                    audit("auth.login", user, "Staff login", actor=user)
                db.session.commit()
                return redirect(_safe_next(_home_for(user)))
    return render_template("auth/login.html", form=f, errors=errors), (401 if errors else 200)


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("public.home"))


# --------------------------------------------------------------- password reset
def _serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="password-reset")


def make_reset_token(user):
    # Including part of the current hash makes the link single-use: it dies once the password changes.
    return _serializer().dumps({"uid": user.id, "h": user.password_hash[-16:]})


def _user_from_token(token):
    try:
        data = _serializer().loads(token, max_age=current_app.config["PASSWORD_RESET_HOURS"] * 3600)
    except (SignatureExpired, BadSignature):
        return None
    user = db.session.get(User, data.get("uid"))
    if not user or user.password_hash[-16:] != data.get("h") or not user.is_active:
        return None
    return user


@bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    errors = FormErrors()
    dev_link = None
    if request.method == "POST":
        email = validate_email(get_str(request.form, "email", errors, "Email", max_len=160), "email", errors)
        if not errors:
            user = User.query.filter_by(email=email).first()
            if user and user.is_active:
                link = url_for("auth.reset_password", token=make_reset_token(user), _external=True)
                sent = send_email(user.email, "Reset your Infrasetu password",
                                  f"Hi {user.name},\n\nUse this link within "
                                  f"{current_app.config['PASSWORD_RESET_HOURS']} hour(s) to set a new password:\n"
                                  f"{link}\n\nIf you didn't ask for this, ignore this email.")
                audit("auth.reset_requested", user, actor=user)
                db.session.commit()
                cfg = current_app.config
                if not sent and (cfg["SHOW_DEV_LINKS"] or current_app.debug or current_app.testing):
                    dev_link = link
            # Same message whether or not the account exists (prevents email enumeration).
            flash("If an account exists for that email, we've sent a password reset link.", "info")
            if not dev_link:
                return redirect(url_for("auth.login"))
    return render_template("auth/forgot.html", form=request.form, errors=errors, dev_link=dev_link)


@bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    user = _user_from_token(token)
    if not user:
        flash("This reset link is invalid or has expired. Please request a new one.", "danger")
        return redirect(url_for("auth.forgot_password"))
    errors = FormErrors()
    if request.method == "POST":
        validate_password(request.form.get("password", ""), request.form.get("confirm", ""), errors)
        if not errors:
            user.set_password(request.form["password"])
            user.failed_logins, user.locked_until = 0, None
            audit("auth.password_reset", user, actor=user)
            db.session.commit()
            session.clear()
            flash("Your password has been reset. Please log in.", "success")
            return redirect(url_for("auth.login"))
    return render_template("auth/reset.html", errors=errors, user=user)


# --------------------------------------------------------------- account area
@bp.route("/account")
@login_required
def account():
    u = g.user
    listings = dict(db.session.query(Product.status, func.count(Product.id))
                    .filter(Product.user_id == u.id).group_by(Product.status).all())
    received = (Enquiry.query.join(Product).filter(Product.user_id == u.id).count())
    new_received = (Enquiry.query.join(Product).filter(Product.user_id == u.id, Enquiry.status == "new").count())
    sent = Enquiry.query.filter_by(user_id=u.id).count()
    return render_template("account/dashboard.html", listings=listings, total_listings=sum(listings.values()),
                           received=received, new_received=new_received, sent=sent)


def _user_to_form(u):
    form = {"name": u.name, "phone": u.phone, "company": u.company or "", "business_type": u.business_type or "",
            "state": u.state or "", "city": u.city or "", "gstin": u.gstin or "", "pan": u.pan or ""}
    if u.partner_profile:
        p = u.partner_profile
        form.update(partner_type=p.partner_type, website=p.website or "", description=p.description,
                    service_states=p.state_list)
    return form


@bp.route("/account/profile", methods=["GET", "POST"])
@login_required
def profile():
    u = g.user
    errors = FormErrors()
    if request.method == "POST":
        f = request.form
        name = get_str(f, "name", errors, "Full name", max_len=120, min_len=2)
        phone = validate_phone(get_str(f, "phone", errors, "Mobile number", max_len=20), "phone", errors)
        state = get_choice(f, "state", errors, "State", INDIAN_STATES, required=u.account_type != "staff")
        city = get_str(f, "city", errors, "City", max_len=80, required=u.account_type != "staff")
        if phone and "phone" not in errors and _phone_taken(phone, exclude_id=u.id):
            errors.add("phone", "This mobile number is used by another account.")
        data, partner = _profile_fields(f, errors, u.account_type, u)
        if not errors:
            kyc_before = (u.gstin, u.pan)
            u.name, u.phone, u.state, u.city = name, phone, state, city
            for k, v in data.items():
                setattr(u, k, v)
            if partner is not None:
                if u.partner_profile is None:
                    u.partner_profile = PartnerProfile(**partner)
                else:
                    for k, v in partner.items():
                        setattr(u.partner_profile, k, v)
            # Changing KYC identifiers sends the account back for verification.
            if (u.gstin, u.pan) != kyc_before and (u.gstin or u.pan):
                u.verification_status, u.verification_note = "pending", None
                flash("Your KYC details changed, so your account has been sent for re-verification.", "info")
            db.session.commit()
            flash("Profile saved.", "success")
            return redirect(url_for("auth.profile"))
        flash("Please fix the highlighted fields.", "danger")
        form = f.to_dict()
        form["service_states"] = f.getlist("service_states")
    else:
        form = _user_to_form(u)
    return render_template("account/profile.html", form=form, errors=errors), (422 if errors else 200)


@bp.route("/account/password", methods=["GET", "POST"])
@login_required
def change_password():
    errors = FormErrors()
    if request.method == "POST":
        f = request.form
        if not g.user.check_password(f.get("current", "")):
            errors.add("current", "Your current password is incorrect.")
        validate_password(f.get("password", ""), f.get("confirm", ""), errors)
        if not errors and f["password"] == f.get("current"):
            errors.add("password", "Choose a password different from your current one.")
        if not errors:
            g.user.set_password(f["password"])
            audit("auth.password_changed", g.user)
            db.session.commit()
            flash("Password changed.", "success")
            return redirect(url_for("auth.account"))
    return render_template("account/password.html", errors=errors), (422 if errors else 200)


@bp.route("/account/become-seller", methods=["POST"])
@login_required
def become_seller():
    u = g.user
    if u.account_type != "buyer":
        abort(400)
    u.account_type = "seller"
    u.business_type = "Individual owner" if u.business_type in (None, "Individual") else "Fleet owner"
    seller = Role.query.filter_by(slug="seller").one()
    if seller not in u.roles:
        u.roles.append(seller)
    audit("user.upgrade_seller", u)
    db.session.commit()
    flash("You're now a seller. Post your first listing below.", "success")
    return redirect(url_for("public.post_listing", type=request.form.get("type", "sell")))
