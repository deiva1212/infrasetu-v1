"""Shared helpers: auth, CSRF, validation, uploads and product form processing."""
import os
import re
import secrets
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from functools import wraps

from flask import abort, current_app, flash, g, redirect, request, session, url_for

from models import (CONDITIONS, FUEL_TYPES, INDIAN_STATES, OWNERSHIP, RENT_PERIODS, Catalogue,
                    Category, ProductAttributeValue, ProductImage, User, db)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^[6-9]\d{9}$")  # Indian mobile
PIN_RE = re.compile(r"^\d{6}$")
GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
PAN_RE = re.compile(r"^[A-Z]{5}\d{4}[A-Z]$")
URL_RE = re.compile(r"^https?://[^\s/$.?#].[^\s]*$", re.I)


def validate_password(pw, confirm, errors, key="password"):
    if len(pw) < 8:
        errors.add(key, "Password must be at least 8 characters.")
    elif not (re.search(r"[A-Za-z]", pw) and re.search(r"\d", pw)):
        errors.add(key, "Password must contain both letters and numbers.")
    if confirm is not None and pw != confirm:
        errors.add("confirm", "Passwords do not match.")


def validate_gstin(val, errors, key="gstin", required=False):
    val = (val or "").strip().upper().replace(" ", "")
    if not val:
        if required:
            errors.add(key, "GSTIN is required.")
        return None
    if not GSTIN_RE.match(val):
        errors.add(key, "Enter a valid 15-character GSTIN, e.g. 29ABCDE1234F1Z5.")
    return val


def validate_pan(val, errors, key="pan", gstin=None):
    val = (val or "").strip().upper().replace(" ", "")
    if not val:
        return None
    if not PAN_RE.match(val):
        errors.add(key, "Enter a valid PAN, e.g. ABCDE1234F.")
    elif gstin and GSTIN_RE.match(gstin) and gstin[2:12] != val:
        errors.add(key, "PAN does not match the PAN inside your GSTIN.")
    return val


# ----------------------------------------------------------------- auth / csrf
def load_current_user():
    uid = session.get("user_id")
    g.user = db.session.get(User, uid) if uid else None
    if g.user is not None and not g.user.is_active:
        session.clear()
        g.user = None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth.login", next=request.full_path))
        return view(*args, **kwargs)
    return wrapped


def permission_required(*codes):
    """Allow the view if the signed-in user holds ANY of the given permissions."""
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.user is None:
                return redirect(url_for("auth.login", next=request.full_path))
            if not any(g.user.has_permission(c) for c in codes):
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def can(code):
    """Template/global helper: does the current user hold this permission?"""
    return bool(g.get("user") is not None and g.user.has_permission(code))


def client_ip():
    return (request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip())[:45]


def audit(action, target=None, details=None, actor=None):
    """Record an admin action or security event. Caller commits."""
    from models import AuditLog
    actor = actor if actor is not None else g.get("user")
    db.session.add(AuditLog(
        actor_id=actor.id if actor is not None else None, action=action,
        target_type=type(target).__name__.lower() if target is not None else None,
        target_id=getattr(target, "id", None), details=(details or "")[:2000] or None, ip=client_ip()))


def send_email(to, subject, body):
    """Send a plain-text email via SMTP, or just log it when no MAIL_SERVER is configured.
    Returns True if actually sent."""
    cfg = current_app.config
    if not cfg.get("MAIL_SERVER"):
        current_app.logger.warning("Email not sent (MAIL_SERVER not set). To: %s | %s\n%s", to, subject, body)
        return False
    import smtplib
    from email.message import EmailMessage
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = cfg["MAIL_FROM"], to, subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(cfg["MAIL_SERVER"], cfg["MAIL_PORT"], timeout=15) as smtp:
            if cfg["MAIL_USE_TLS"]:
                smtp.starttls()
            if cfg["MAIL_USERNAME"]:
                smtp.login(cfg["MAIL_USERNAME"], cfg["MAIL_PASSWORD"])
            smtp.send_message(msg)
        return True
    except (OSError, smtplib.SMTPException):
        current_app.logger.exception("Failed to send email to %s", to)
        return False


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


def check_csrf():
    if request.method == "POST":
        token = request.form.get("_csrf") or request.headers.get("X-CSRF-Token")
        if not token or token != session.get("_csrf"):
            abort(400, description="Invalid or missing form token. Please reload the page and try again.")


# ----------------------------------------------------------------- formatting
def slugify(text):
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return text or uuid.uuid4().hex[:8]


def inr(value):
    """Indian number formatting: 1234567 -> ₹12,34,567"""
    if value is None:
        return "—"
    value = int(Decimal(value))
    s = str(abs(value))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = re.sub(r"(\d)(?=(\d{2})+$)", r"\1,", head)
        s = head + "," + tail
    return ("-" if value < 0 else "") + "₹" + s


def inr_short(value):
    if value is None:
        return "—"
    v = float(value)
    if v >= 1e7:
        return f"₹{v/1e7:.2f} Cr".replace(".00", "")
    if v >= 1e5:
        return f"₹{v/1e5:.2f} L".replace(".00", "")
    return inr(v)


# ----------------------------------------------------------------- validation
class FormErrors(dict):
    def add(self, field, msg):
        self.setdefault(field, msg)


def get_str(form, key, errors, label, required=True, max_len=255, min_len=0):
    val = (form.get(key) or "").strip()
    if not val:
        if required:
            errors.add(key, f"{label} is required.")
        return None
    if len(val) > max_len:
        errors.add(key, f"{label} must be at most {max_len} characters.")
    elif len(val) < min_len:
        errors.add(key, f"{label} must be at least {min_len} characters.")
    return val


def get_int(form, key, errors, label, required=True, min_v=None, max_v=None):
    raw = (form.get(key) or "").strip().replace(",", "")
    if not raw:
        if required:
            errors.add(key, f"{label} is required.")
        return None
    try:
        val = int(raw)
    except ValueError:
        errors.add(key, f"{label} must be a whole number.")
        return None
    if min_v is not None and val < min_v:
        errors.add(key, f"{label} must be at least {min_v}.")
    if max_v is not None and val > max_v:
        errors.add(key, f"{label} must be at most {max_v}.")
    return val


def get_decimal(form, key, errors, label, required=True, min_v=0):
    raw = (form.get(key) or "").strip().replace(",", "")
    if not raw:
        if required:
            errors.add(key, f"{label} is required.")
        return None
    try:
        val = Decimal(raw)
    except InvalidOperation:
        errors.add(key, f"{label} must be a number.")
        return None
    if min_v is not None and val <= min_v:
        errors.add(key, f"{label} must be greater than {min_v}.")
    return val


def get_date(form, key, errors, label, required=False):
    raw = (form.get(key) or "").strip()
    if not raw:
        if required:
            errors.add(key, f"{label} is required.")
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        errors.add(key, f"{label} must be a valid date.")
        return None


def get_choice(form, key, errors, label, choices, required=True):
    val = (form.get(key) or "").strip()
    if not val:
        if required:
            errors.add(key, f"Please select {label.lower()}.")
        return None
    if val not in choices:
        errors.add(key, f"Invalid {label.lower()}.")
        return None
    return val


def validate_phone(val, key, errors):
    if not val:
        return val
    digits = re.sub(r"\D", "", val)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if not PHONE_RE.match(digits):
        errors.add(key, "Enter a valid 10-digit mobile number.")
    return digits


def validate_email(val, key, errors):
    if val and not EMAIL_RE.match(val):
        errors.add(key, "Enter a valid email address.")
    return val.lower() if val else val


# ----------------------------------------------------------------- uploads
def allowed_image(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in current_app.config["ALLOWED_IMAGE_EXTENSIONS"]


def save_image(file_storage):
    ext = file_storage.filename.rsplit(".", 1)[1].lower()
    name = f"{uuid.uuid4().hex}.{ext}"
    os.makedirs(current_app.config["UPLOAD_FOLDER"], exist_ok=True)
    file_storage.save(os.path.join(current_app.config["UPLOAD_FOLDER"], name))
    return name


def delete_image_file(filename):
    try:
        os.remove(os.path.join(current_app.config["UPLOAD_FOLDER"], filename))
    except OSError:
        pass


# ----------------------------------------------------------------- products
def process_product_form(form, files, product=None, admin=False):
    """Validate the listing form. Returns (data, attr_values, new_files, errors).

    Required fields depend on the listing type (sell vs rent) and on the
    category's own admin-defined attributes."""
    errors = FormErrors()
    data = {}
    this_year = date.today().year

    data["listing_type"] = get_choice(form, "listing_type", errors, "Listing type", ["sell", "rent"])

    category = None
    cat_id = get_int(form, "category_id", errors, "Category")
    if cat_id:
        category = db.session.get(Category, cat_id)
        if not category or not category.is_active:
            errors.add("category_id", "Please select a valid category.")
            category = None
        elif category.children:
            errors.add("category_id", "Please choose a specific sub-category.")
        elif data["listing_type"] == "sell" and not category.allow_sell:
            errors.add("listing_type", "This category does not accept sale listings.")
        elif data["listing_type"] == "rent" and not category.allow_rent:
            errors.add("listing_type", "This category does not accept rental listings.")
    data["category_id"] = category.id if category else None

    cat_item_id = get_int(form, "catalogue_id", errors, "Make / model")
    if cat_item_id:
        item = db.session.get(Catalogue, cat_item_id)
        if not item or (category and item.category_id != category.id) or not item.is_active:
            errors.add("catalogue_id", "Please select a make / model from the list for this category.")
        else:
            data["catalogue_id"] = item.id

    data["title"] = get_str(form, "title", errors, "Listing title", max_len=200, min_len=10)
    data["manufacture_year"] = get_int(form, "manufacture_year", errors, "Year of manufacture",
                                       min_v=1970, max_v=this_year)
    data["condition"] = get_choice(form, "condition", errors, "Condition", CONDITIONS)
    usage_label = "Engine hours" if category and category.usage_unit == "hours" else "Kilometres driven"
    data["usage_reading"] = get_int(form, "usage_reading", errors, usage_label, min_v=0, max_v=5_000_000)
    data["fuel_type"] = get_choice(form, "fuel_type", errors, "Fuel type", FUEL_TYPES)

    is_vehicle = category is not None and category.group == "Commercial Vehicle"
    reg = get_str(form, "registration_no", errors, "Registration number",
                  required=is_vehicle and data.get("condition") != "New", max_len=30)
    data["registration_no"] = reg.upper().replace(" ", "") if reg else None
    data["ownership"] = get_choice(form, "ownership", errors, "Ownership", OWNERSHIP,
                                   required=data.get("condition") not in (None, "New"))
    data["insurance_valid_till"] = get_date(form, "insurance_valid_till", errors, "Insurance valid till")

    if data["listing_type"] == "sell":
        data["price"] = get_decimal(form, "price", errors, "Expected price")
        data["price_negotiable"] = form.get("price_negotiable") == "1"
        data.update(rent_rate=None, rent_period=None, min_rent_duration=None,
                    operator_included=False, fuel_included=False, available_from=None)
    elif data["listing_type"] == "rent":
        data["rent_rate"] = get_decimal(form, "rent_rate", errors, "Rental rate")
        data["rent_period"] = get_choice(form, "rent_period", errors, "Rental period", RENT_PERIODS)
        data["min_rent_duration"] = get_int(form, "min_rent_duration", errors, "Minimum rental duration",
                                            min_v=1, max_v=1000)
        data["operator_included"] = form.get("operator_included") == "1"
        data["fuel_included"] = form.get("fuel_included") == "1"
        data["available_from"] = get_date(form, "available_from", errors, "Available from", required=True)
        data.update(price=None, price_negotiable=False)

    data["state"] = get_choice(form, "state", errors, "State", INDIAN_STATES)
    data["city"] = get_str(form, "city", errors, "City", max_len=80)
    pin = get_str(form, "pincode", errors, "Pincode", max_len=10)
    if pin and not PIN_RE.match(pin):
        errors.add("pincode", "Pincode must be 6 digits.")
    data["pincode"] = pin
    data["description"] = get_str(form, "description", errors, "Description", max_len=5000, min_len=30)
    data["contact_name"] = get_str(form, "contact_name", errors, "Contact name", max_len=120)
    data["contact_phone"] = validate_phone(get_str(form, "contact_phone", errors, "Contact phone", max_len=20),
                                           "contact_phone", errors)
    data["contact_email"] = validate_email(get_str(form, "contact_email", errors, "Contact email",
                                                   required=False, max_len=160), "contact_email", errors)

    # category-specific attributes
    attr_values = {}
    if category:
        for attr in category.all_attributes():
            key = f"attr_{attr.id}"
            raw = (form.get(key) or "").strip()
            if attr.field_type == "boolean":
                raw = "Yes" if form.get(key) == "1" else ("No" if attr.is_required or raw else "")
            if not raw:
                if attr.is_required:
                    errors.add(key, f"{attr.label} is required.")
                continue
            if attr.field_type == "number":
                try:
                    float(raw.replace(",", ""))
                except ValueError:
                    errors.add(key, f"{attr.label} must be a number.")
                    continue
                raw = raw.replace(",", "")
            if attr.field_type == "select" and raw not in attr.option_list:
                errors.add(key, f"Invalid value for {attr.label}.")
                continue
            attr_values[attr.id] = raw[:255]

    # images
    new_files = [f for f in files.getlist("images") if f and f.filename]
    for f in new_files:
        if not allowed_image(f.filename):
            errors.add("images", "Photos must be JPG, PNG or WEBP.")
    existing = len(product.images) if product else 0
    removing = len(form.getlist("remove_image")) if product else 0
    total = existing - removing + len(new_files)
    if total < 1 and not admin:
        errors.add("images", "Please upload at least one photo of the vehicle / machine.")
    if total > current_app.config["MAX_IMAGES_PER_PRODUCT"]:
        errors.add("images", f"Maximum {current_app.config['MAX_IMAGES_PER_PRODUCT']} photos allowed.")

    if admin:
        from models import PRODUCT_STATUSES
        data["status"] = get_choice(form, "status", errors, "Status", PRODUCT_STATUSES)
        data["is_featured"] = form.get("is_featured") == "1"
        data["admin_note"] = get_str(form, "admin_note", errors, "Admin note", required=False)

    return data, attr_values, new_files, errors


def apply_product_data(product, data, attr_values, new_files, form):
    for k, v in data.items():
        setattr(product, k, v)
    # attributes: replace all
    product.attribute_values.clear()
    db.session.flush()
    for attr_id, val in attr_values.items():
        product.attribute_values.append(ProductAttributeValue(attribute_id=attr_id, value=val))
    # remove images
    remove_ids = {int(i) for i in form.getlist("remove_image") if i.isdigit()}
    for img in list(product.images):
        if img.id in remove_ids:
            delete_image_file(img.filename)
            product.images.remove(img)
    start = len(product.images)
    for i, f in enumerate(new_files):
        product.images.append(ProductImage(filename=save_image(f), sort_order=start + i))


def generate_ref_code(product):
    prefix = "S" if product.listing_type == "sell" else "R"
    return f"IS{prefix}{product.id:06d}"
