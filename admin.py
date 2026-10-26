"""Admin back office: dashboard, category, catalogue and product management and leads.
User, role and audit screens live in admin_users.py. Every route is permission-gated."""
import csv
import io

from flask import (Blueprint, Response, abort, current_app, flash, g, redirect, render_template,
                   request, url_for)
from sqlalchemy import func, or_

from models import (ATTRIBUTE_TYPES, CATEGORY_GROUPS, ENQUIRY_STATUSES, PRODUCT_STATUSES,
                    USAGE_UNITS, Catalogue, Category, CategoryAttribute, Enquiry, Product,
                    Requirement, User, db)
from utils import (FormErrors, apply_product_data, audit, delete_image_file, generate_ref_code,
                   get_choice, get_int, get_str, permission_required, process_product_form, slugify)

bp = Blueprint("admin", __name__)


# First page each admin permission opens, in menu order (used when a user lacks dashboard.view).
ADMIN_LANDING = [
    ("dashboard.view", "admin.dashboard"), ("products.view", "admin.products"),
    ("catalogue.manage", "admin.categories"), ("leads.manage", "admin.enquiries"),
    ("users.view", "admin.users"), ("roles.manage", "admin.roles"), ("audit.view", "admin.audit"),
]


@bp.before_request
@permission_required("admin.access")
def _guard():
    pass


def _page(q):
    return q.paginate(page=request.args.get("page", 1, type=int),
                       per_page=current_app.config["ADMIN_ITEMS_PER_PAGE"], error_out=False)


# ------------------------------------------------------------------ dashboard
@bp.route("/")
def dashboard():
    if not g.user.has_permission("dashboard.view"):
        for code, endpoint in ADMIN_LANDING:
            if g.user.has_permission(code):
                return redirect(url_for(endpoint))
        abort(403)
    by_status = dict(db.session.query(Product.status, func.count(Product.id)).group_by(Product.status).all())
    by_type = dict(db.session.query(Product.listing_type, func.count(Product.id))
                   .filter(Product.status == "approved").group_by(Product.listing_type).all())
    by_cat = (db.session.query(Category.name, func.count(Product.id))
              .join(Product, Product.category_id == Category.id)
              .group_by(Category.name).order_by(func.count(Product.id).desc()).limit(8).all())
    stats = {
        "products": Product.query.count(),
        "pending": by_status.get("pending", 0),
        "live_sell": by_type.get("sell", 0),
        "live_rent": by_type.get("rent", 0),
        "categories": Category.query.count(),
        "catalogue": Catalogue.query.count(),
        "users": User.query.count(),
        "kyc_pending": User.query.filter_by(verification_status="pending").count(),
        "new_enquiries": Enquiry.query.filter_by(status="new").count(),
        "new_requirements": Requirement.query.filter_by(status="new").count(),
    }
    pending = Product.query.filter_by(status="pending").order_by(Product.created_at.asc()).limit(8).all()
    enquiries = Enquiry.query.order_by(Enquiry.created_at.desc()).limit(6).all()
    return render_template("admin/dashboard.html", stats=stats, by_status=by_status, by_cat=by_cat,
                           pending=pending, enquiries=enquiries)


# ------------------------------------------------------------------ categories
@bp.route("/categories")
@permission_required("catalogue.manage")
def categories():
    roots = (Category.query.filter_by(parent_id=None)
             .order_by(Category.group, Category.sort_order, Category.name).all())
    pcounts = dict(db.session.query(Product.category_id, func.count(Product.id)).group_by(Product.category_id).all())
    ccounts = dict(db.session.query(Catalogue.category_id, func.count(Catalogue.id)).group_by(Catalogue.category_id).all())
    return render_template("admin/categories.html", roots=roots, pcounts=pcounts, ccounts=ccounts)


def _category_from_form(cat, f, errors):
    cat.name = get_str(f, "name", errors, "Name", max_len=120)
    cat.group = get_choice(f, "group", errors, "Group", CATEGORY_GROUPS)
    slug = slugify(f.get("slug") or cat.name or "")
    clash = Category.query.filter(Category.slug == slug, Category.id != (cat.id or 0)).first()
    if clash:
        errors.add("slug", "This slug is already used by another category.")
    cat.slug = slug
    parent_id = get_int(f, "parent_id", errors, "Parent", required=False)
    if parent_id:
        parent = db.session.get(Category, parent_id)
        if not parent or parent.id == cat.id or parent.parent_id:
            errors.add("parent_id", "Parent must be a top-level category (two levels max).")
        elif cat.id and cat.children:
            errors.add("parent_id", "A category with sub-categories cannot be moved under another.")
    cat.parent_id = parent_id or None
    cat.usage_unit = get_choice(f, "usage_unit", errors, "Usage unit", list(USAGE_UNITS))
    cat.description = get_str(f, "description", errors, "Description", required=False, max_len=2000)
    cat.sort_order = get_int(f, "sort_order", errors, "Sort order", required=False) or 0
    cat.allow_sell = f.get("allow_sell") == "1"
    cat.allow_rent = f.get("allow_rent") == "1"
    if not (cat.allow_sell or cat.allow_rent):
        errors.add("allow_sell", "Allow at least one of sell or rent.")
    cat.is_active = f.get("is_active") == "1"


@bp.route("/categories/new", methods=["GET", "POST"])
@bp.route("/categories/<int:cid>/edit", methods=["GET", "POST"])
@permission_required("catalogue.manage")
def category_form(cid=None):
    cat = db.session.get(Category, cid) if cid else Category(is_active=True, allow_sell=True, allow_rent=True)
    if cid and not cat:
        abort(404)
    errors = FormErrors()
    if request.method == "POST":
        with db.session.no_autoflush:
            _category_from_form(cat, request.form, errors)
        if not errors:
            db.session.add(cat)
            db.session.commit()
            flash(f"Category '{cat.name}' saved.", "success")
            return redirect(url_for("admin.category_form", cid=cat.id))
        db.session.rollback()
        flash("Please fix the errors below.", "danger")
    parents = Category.query.filter_by(parent_id=None).order_by(Category.name).all()
    return render_template("admin/category_form.html", cat=cat, parents=parents, errors=errors,
                           form=request.form if request.method == "POST" else None)


@bp.route("/categories/<int:cid>/delete", methods=["POST"])
@permission_required("catalogue.manage")
def category_delete(cid):
    cat = db.session.get(Category, cid) or abort(404)
    if cat.products.count() or cat.catalogue_items.count() or cat.children:
        flash("Cannot delete: category has sub-categories, catalogue items or products. Deactivate it instead.", "danger")
        return redirect(url_for("admin.categories"))
    db.session.delete(cat)
    db.session.commit()
    flash("Category deleted.", "success")
    return redirect(url_for("admin.categories"))


@bp.route("/categories/<int:cid>/attributes", methods=["POST"])
@bp.route("/categories/<int:cid>/attributes/<int:aid>", methods=["POST"])
@permission_required("catalogue.manage")
def attribute_save(cid, aid=None):
    cat = db.session.get(Category, cid) or abort(404)
    attr = db.session.get(CategoryAttribute, aid) if aid else CategoryAttribute(category=cat)
    if not attr or attr.category_id not in (None, cat.id):
        abort(404)
    f = request.form
    if f.get("action") == "delete" and aid:
        db.session.delete(attr)
        db.session.commit()
        flash(f"Field '{attr.label}' removed.", "success")
        return redirect(url_for("admin.category_form", cid=cid) + "#fields")
    errors = FormErrors()
    attr.label = get_str(f, "label", errors, "Field label", max_len=120)
    attr.field_type = get_choice(f, "field_type", errors, "Field type", list(ATTRIBUTE_TYPES))
    attr.options = get_str(f, "options", errors, "Options", required=attr.field_type == "select", max_len=2000)
    attr.unit = get_str(f, "unit", errors, "Unit", required=False, max_len=30)
    attr.is_required = f.get("is_required") == "1"
    attr.is_searchable = f.get("is_searchable") == "1"
    attr.sort_order = get_int(f, "sort_order", errors, "Order", required=False) or 0
    if errors:
        db.session.rollback()
        flash(" ".join(errors.values()), "danger")
    else:
        db.session.add(attr)
        db.session.commit()
        flash(f"Field '{attr.label}' saved.", "success")
    return redirect(url_for("admin.category_form", cid=cid) + "#fields")


# ------------------------------------------------------------------ catalogue
@bp.route("/catalogue")
@permission_required("catalogue.manage")
def catalogue():
    q = Catalogue.query.join(Category)
    if request.args.get("category", "").isdigit():
        cid = int(request.args["category"])
        q = q.filter(or_(Catalogue.category_id == cid, Category.parent_id == cid))
    if request.args.get("q"):
        t = f"%{request.args['q'].strip()}%"
        q = q.filter(or_(Catalogue.manufacturer.ilike(t), Catalogue.model_name.ilike(t), Catalogue.variant.ilike(t)))
    if request.args.get("active") in ("0", "1"):
        q = q.filter(Catalogue.is_active.is_(request.args["active"] == "1"))
    if request.args.get("export") == "csv":
        return _catalogue_csv(q.order_by(Catalogue.manufacturer, Catalogue.model_name).all())
    page = _page(q.order_by(Catalogue.manufacturer, Catalogue.model_name))
    counts = dict(db.session.query(Product.catalogue_id, func.count(Product.id)).group_by(Product.catalogue_id).all())
    cats = Category.query.order_by(Category.group, Category.name).all()
    return render_template("admin/catalogue.html", page=page, cats=cats, counts=counts)


CSV_FIELDS = ["category_slug", "manufacturer", "model_name", "variant", "engine_power_hp",
              "operating_weight_kg", "gvw_kg", "specifications", "description", "is_active"]


def _catalogue_csv(items):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_FIELDS)
    for i in items:
        w.writerow([i.category.slug, i.manufacturer, i.model_name, i.variant, i.engine_power_hp or "",
                    i.operating_weight_kg or "", i.gvw_kg or "", (i.specifications or "").replace("\n", " | "),
                    i.description or "", 1 if i.is_active else 0])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=catalogue.csv"})


@bp.route("/catalogue/import", methods=["POST"])
@permission_required("catalogue.manage")
def catalogue_import():
    file = request.files.get("file")
    if not file or not file.filename.lower().endswith(".csv"):
        flash("Please choose a .csv file.", "danger")
        return redirect(url_for("admin.catalogue"))
    reader = csv.DictReader(io.StringIO(file.read().decode("utf-8-sig")))
    added = updated = skipped = 0
    slugs = {c.slug: c for c in Category.query.all()}

    def num(v):
        v = (v or "").strip()
        return int(float(v)) if v else None

    for row in reader:
        cat = slugs.get((row.get("category_slug") or "").strip())
        mfr, model = (row.get("manufacturer") or "").strip(), (row.get("model_name") or "").strip()
        if not cat or not mfr or not model or cat.children:
            skipped += 1
            continue
        variant = (row.get("variant") or "").strip()
        item = Catalogue.query.filter_by(category_id=cat.id, manufacturer=mfr, model_name=model, variant=variant).first()
        if item:
            updated += 1
        else:
            item = Catalogue(category_id=cat.id, manufacturer=mfr, model_name=model, variant=variant)
            db.session.add(item)
            added += 1
        try:
            item.engine_power_hp = num(row.get("engine_power_hp"))
            item.operating_weight_kg = num(row.get("operating_weight_kg"))
            item.gvw_kg = num(row.get("gvw_kg"))
        except ValueError:
            pass
        item.specifications = (row.get("specifications") or "").replace(" | ", "\n") or None
        item.description = row.get("description") or None
        item.is_active = (row.get("is_active") or "1").strip() != "0"
    db.session.commit()
    flash(f"Import complete: {added} added, {updated} updated, {skipped} skipped.", "success")
    return redirect(url_for("admin.catalogue"))


@bp.route("/catalogue/new", methods=["GET", "POST"])
@bp.route("/catalogue/<int:iid>/edit", methods=["GET", "POST"])
@permission_required("catalogue.manage")
def catalogue_form(iid=None):
    item = db.session.get(Catalogue, iid) if iid else Catalogue(is_active=True, variant="")
    if iid and not item:
        abort(404)
    errors = FormErrors()
    if request.method == "POST":
        f = request.form
        with db.session.no_autoflush:
            cid = get_int(f, "category_id", errors, "Category")
            cat = db.session.get(Category, cid) if cid else None
            if cid and (not cat or cat.children):
                errors.add("category_id", "Choose a specific (leaf) category.")
            item.category_id = cid
            item.manufacturer = get_str(f, "manufacturer", errors, "Manufacturer", max_len=120)
            item.model_name = get_str(f, "model_name", errors, "Model", max_len=120)
            item.variant = get_str(f, "variant", errors, "Variant", required=False, max_len=120) or ""
            item.engine_power_hp = get_int(f, "engine_power_hp", errors, "Engine power", required=False, min_v=1)
            item.operating_weight_kg = get_int(f, "operating_weight_kg", errors, "Operating weight", required=False, min_v=1)
            item.gvw_kg = get_int(f, "gvw_kg", errors, "GVW", required=False, min_v=1)
            item.specifications = get_str(f, "specifications", errors, "Specifications", required=False, max_len=5000)
            item.description = get_str(f, "description", errors, "Description", required=False, max_len=5000)
            item.is_active = f.get("is_active") == "1"
            if not errors:
                dup = Catalogue.query.filter(Catalogue.category_id == item.category_id,
                                             Catalogue.manufacturer == item.manufacturer,
                                             Catalogue.model_name == item.model_name,
                                             Catalogue.variant == item.variant,
                                             Catalogue.id != (item.id or 0)).first()
                if dup:
                    errors.add("model_name", "This make / model / variant already exists in the category.")
        if not errors:
            db.session.add(item)
            db.session.commit()
            flash(f"Catalogue item '{item.display_name}' saved.", "success")
            return redirect(url_for("admin.catalogue"))
        db.session.rollback()
        flash("Please fix the errors below.", "danger")
    cats = [c for c in Category.query.order_by(Category.group, Category.name).all() if not c.children]
    manufacturers = [m for (m,) in db.session.query(Catalogue.manufacturer).distinct().order_by(Catalogue.manufacturer)]
    return render_template("admin/catalogue_form.html", item=item, cats=cats, errors=errors,
                           manufacturers=manufacturers,
                           form=request.form if request.method == "POST" else None)


@bp.route("/catalogue/<int:iid>/delete", methods=["POST"])
@permission_required("catalogue.manage")
def catalogue_delete(iid):
    item = db.session.get(Catalogue, iid) or abort(404)
    if item.products.count():
        flash("Cannot delete: products reference this model. Deactivate it instead.", "danger")
    else:
        db.session.delete(item)
        db.session.commit()
        flash("Catalogue item deleted.", "success")
    return redirect(url_for("admin.catalogue"))


# ------------------------------------------------------------------ products
@bp.route("/products")
@permission_required("products.view")
def products():
    q = Product.query.join(Catalogue)
    a = request.args
    if a.get("status") in PRODUCT_STATUSES:
        q = q.filter(Product.status == a["status"])
    if a.get("type") in ("sell", "rent"):
        q = q.filter(Product.listing_type == a["type"])
    if a.get("category", "").isdigit():
        cid = int(a["category"])
        q = q.join(Category, Product.category_id == Category.id).filter(
            or_(Category.id == cid, Category.parent_id == cid))
    if a.get("user", "").isdigit():
        q = q.filter(Product.user_id == int(a["user"]))
    if a.get("q"):
        t = f"%{a['q'].strip()}%"
        q = q.filter(or_(Product.title.ilike(t), Product.ref_code.ilike(t), Product.city.ilike(t),
                         Catalogue.manufacturer.ilike(t), Product.registration_no.ilike(t)))
    page = _page(q.order_by(Product.created_at.desc()))
    cats = Category.query.order_by(Category.group, Category.name).all()
    status_counts = dict(db.session.query(Product.status, func.count(Product.id)).group_by(Product.status).all())
    return render_template("admin/products.html", page=page, cats=cats, status_counts=status_counts)


@bp.route("/products/bulk", methods=["POST"])
@permission_required("products.moderate", "products.edit")
def products_bulk():
    ids = [int(i) for i in request.form.getlist("ids") if i.isdigit()]
    action = request.form.get("action")
    if not ids or action not in ("approved", "rejected", "inactive", "feature", "unfeature", "delete"):
        flash("Select listings and an action.", "warning")
        return redirect(request.referrer or url_for("admin.products"))
    needed = "products.edit" if action in ("feature", "unfeature", "delete") else "products.moderate"
    if not g.user.has_permission(needed):
        abort(403)
    items = Product.query.filter(Product.id.in_(ids)).all()
    audit(f"product.bulk_{action}", None, "Listings: " + ", ".join(p.ref_code or str(p.id) for p in items))
    for p in items:
        if action == "delete":
            for img in p.images:
                delete_image_file(img.filename)
            db.session.delete(p)
        elif action in ("feature", "unfeature"):
            p.is_featured = action == "feature"
        else:
            p.status = action
    db.session.commit()
    flash(f"{len(items)} listing(s) updated.", "success")
    return redirect(request.referrer or url_for("admin.products"))


@bp.route("/products/<int:pid>/moderate", methods=["POST"])
@permission_required("products.moderate")
def product_moderate(pid):
    p = db.session.get(Product, pid) or abort(404)
    status = request.form.get("status")
    if status not in ("approved", "rejected"):
        abort(400)
    p.status = status
    p.admin_note = (request.form.get("admin_note") or "").strip()[:255] or p.admin_note
    audit(f"product.{status}", p, p.admin_note if status == "rejected" else p.ref_code)
    db.session.commit()
    flash(f"{p.ref_code} {status}.", "success")
    return redirect(request.referrer or url_for("admin.products"))


@bp.route("/products/new", methods=["GET", "POST"])
@bp.route("/products/<int:pid>/edit", methods=["GET", "POST"])
@permission_required("products.edit")
def product_form(pid=None):
    from public import _product_to_form, active_categories
    p = db.session.get(Product, pid) if pid else None
    if pid and not p:
        abort(404)
    if request.method == "POST":
        data, attrs, files, errors = process_product_form(request.form, request.files, product=p, admin=True)
        owner = None
        if not p:
            owner = User.query.filter_by(email=(request.form.get("owner_email") or "").strip().lower()).first()
            if not owner:
                errors.add("owner_email", "Enter the email of a registered user who owns this listing.")
        if not errors:
            if not p:
                p = Product(user_id=owner.id)
                db.session.add(p)
            apply_product_data(p, data, attrs, files, request.form)
            db.session.flush()
            if not p.ref_code:
                p.ref_code = generate_ref_code(p)
            db.session.commit()
            flash(f"Product {p.ref_code} saved.", "success")
            return redirect(url_for("admin.product_form", pid=p.id))
        flash("Please fix the errors below.", "danger")
        form = request.form
    else:
        form = _product_to_form(p) if p else {"listing_type": "sell", "status": "approved",
                                              "owner_email": g.user.email, "contact_name": g.user.name,
                                              "contact_phone": g.user.phone}
        errors = {}
    enquiries = p.enquiries.order_by(Enquiry.created_at.desc()).all() if p else []
    return render_template("admin/product_form.html", p=p, form=form, errors=errors,
                           categories=active_categories(), enquiries=enquiries,
                           current_year=__import__("datetime").date.today().year), (422 if errors else 200)


@bp.route("/products/<int:pid>/delete", methods=["POST"])
@permission_required("products.edit")
def product_delete(pid):
    p = db.session.get(Product, pid) or abort(404)
    audit("product.delete", p, f"{p.ref_code} {p.title}")
    for img in p.images:
        delete_image_file(img.filename)
    db.session.delete(p)
    db.session.commit()
    flash("Product deleted.", "success")
    return redirect(url_for("admin.products"))


# ------------------------------------------------------------------ leads
@bp.route("/enquiries")
@permission_required("leads.manage")
def enquiries():
    q = Enquiry.query
    if request.args.get("status") in ENQUIRY_STATUSES:
        q = q.filter_by(status=request.args["status"])
    if request.args.get("type") in ("buy", "rent"):
        q = q.filter_by(enquiry_type=request.args["type"])
    return render_template("admin/enquiries.html", page=_page(q.order_by(Enquiry.created_at.desc())))


@bp.route("/enquiries/<int:eid>/status", methods=["POST"])
@permission_required("leads.manage")
def enquiry_status(eid):
    e = db.session.get(Enquiry, eid) or abort(404)
    if request.form.get("status") in ENQUIRY_STATUSES:
        e.status = request.form["status"]
        db.session.commit()
        flash("Enquiry updated.", "success")
    return redirect(request.referrer or url_for("admin.enquiries"))


@bp.route("/requirements")
@permission_required("leads.manage")
def requirements():
    q = Requirement.query
    if request.args.get("status") in ENQUIRY_STATUSES:
        q = q.filter_by(status=request.args["status"])
    return render_template("admin/requirements.html", page=_page(q.order_by(Requirement.created_at.desc())))


@bp.route("/requirements/<int:rid>/status", methods=["POST"])
@permission_required("leads.manage")
def requirement_status(rid):
    r = db.session.get(Requirement, rid) or abort(404)
    if request.form.get("status") in ENQUIRY_STATUSES:
        r.status = request.form["status"]
        db.session.commit()
        flash("Requirement updated.", "success")
    return redirect(request.referrer or url_for("admin.requirements"))
