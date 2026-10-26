"""Public marketplace: browse, search (buy / rent), post listings (sell / rent), enquiries, accounts."""
from datetime import date

from flask import (Blueprint, abort, current_app, flash, g, jsonify, redirect, render_template,
                   request, url_for)
from sqlalchemy import func, or_

from models import (CONDITIONS, INDIAN_STATES, PARTNER_TYPES, Catalogue, Category, Enquiry,
                    PartnerProfile, Product, ProductAttributeValue, Requirement, User, db)
from utils import (FormErrors, apply_product_data, generate_ref_code, get_choice, get_date,
                   get_decimal, get_int, get_str, login_required, process_product_form,
                   validate_email, validate_phone)

bp = Blueprint("public", __name__)


def active_categories():
    return (Category.query.filter_by(is_active=True)
            .order_by(Category.group, Category.sort_order, Category.name).all())


def leaf_categories():
    return [c for c in active_categories() if not c.children]


def category_ids_with_children(cat):
    return [cat.id] + [c.id for c in cat.children if c.is_active]


# ------------------------------------------------------------------- home
@bp.route("/")
def home():
    counts = dict(db.session.query(Product.category_id, func.count(Product.id))
                  .filter(Product.status == "approved").group_by(Product.category_id).all())
    for cat in active_categories():  # roll sub-category counts up to their parent
        if cat.parent_id and cat.id in counts:
            counts[cat.parent_id] = counts.get(cat.parent_id, 0) + counts[cat.id]
    featured = (Product.query.filter_by(status="approved")
                .order_by(Product.is_featured.desc(), Product.created_at.desc()).limit(8).all())
    stats = {
        "sell": Product.query.filter_by(status="approved", listing_type="sell").count(),
        "rent": Product.query.filter_by(status="approved", listing_type="rent").count(),
        "brands": db.session.query(func.count(func.distinct(Catalogue.manufacturer))).scalar(),
    }
    return render_template("home.html", categories=active_categories(), counts=counts,
                           featured=featured, stats=stats)


# ------------------------------------------------------------------- search
SORTS = {
    "newest": ("Newest first", Product.created_at.desc()),
    "price_asc": ("Price: low to high", None),
    "price_desc": ("Price: high to low", None),
    "year_desc": ("Year: newest model", Product.manufacture_year.desc()),
    "usage_asc": ("Lowest usage", Product.usage_reading.asc()),
}


@bp.route("/search")
def search():
    args = request.args
    submitted = bool(args.get("submitted"))
    errors = FormErrors()
    results = None
    category = None
    attrs = []

    if submitted:
        intent = get_choice(args, "intent", errors, "Buy or rent", ["buy", "rent"])
        cat_id = get_int(args, "category", errors, "Category")
        if cat_id:
            category = db.session.get(Category, cat_id)
            if not category or not category.is_active:
                errors.add("category", "Please select a valid category.")
                category = None
        state = get_choice(args, "state", errors, "Location (state)", INDIAN_STATES + ["ALL"])
        year_min = get_int(args, "year_min", errors, "Year from", required=False, min_v=1970)
        year_max = get_int(args, "year_max", errors, "Year to", required=False, min_v=1970)
        if year_min and year_max and year_min > year_max:
            errors.add("year_max", "'Year to' must be after 'Year from'.")
        budget_min = get_decimal(args, "budget_min", errors, "Minimum budget", required=False, min_v=None)
        budget_max = get_decimal(args, "budget_max", errors, "Maximum budget", required=False, min_v=None)
        if budget_min is not None and budget_max is not None and budget_min > budget_max:
            errors.add("budget_max", "Maximum budget must be more than minimum.")
        usage_max = get_int(args, "usage_max", errors, "Maximum usage", required=False, min_v=0)
        condition = get_choice(args, "condition", errors, "Condition", CONDITIONS, required=False)

        if category:
            attrs = [a for a in category.all_attributes() if a.is_searchable]

        if not errors:
            q = (Product.query.join(Catalogue)
                 .filter(Product.status == "approved",
                         Product.listing_type == ("sell" if intent == "buy" else "rent"),
                         Product.category_id.in_(category_ids_with_children(category))))
            if state != "ALL":
                q = q.filter(Product.state == state)
            if args.get("city"):
                q = q.filter(Product.city.ilike(f"%{args['city'].strip()}%"))
            if args.get("manufacturer"):
                q = q.filter(Catalogue.manufacturer == args["manufacturer"])
            if args.get("catalogue_id", "").isdigit():
                q = q.filter(Product.catalogue_id == int(args["catalogue_id"]))
            if year_min:
                q = q.filter(Product.manufacture_year >= year_min)
            if year_max:
                q = q.filter(Product.manufacture_year <= year_max)
            price_col = Product.price if intent == "buy" else Product.rent_rate
            if budget_min is not None:
                q = q.filter(price_col >= budget_min)
            if budget_max is not None:
                q = q.filter(price_col <= budget_max)
            if intent == "rent" and args.get("rent_period"):
                q = q.filter(Product.rent_period == args["rent_period"])
            if intent == "rent" and args.get("operator") == "1":
                q = q.filter(Product.operator_included.is_(True))
            if usage_max is not None:
                q = q.filter(Product.usage_reading <= usage_max)
            if condition:
                q = q.filter(Product.condition == condition)
            if args.get("fuel_type"):
                q = q.filter(Product.fuel_type == args["fuel_type"])
            if args.get("q"):
                term = f"%{args['q'].strip()}%"
                q = q.filter(or_(Product.title.ilike(term), Product.description.ilike(term),
                                 Catalogue.model_name.ilike(term)))
            for a in attrs:
                val = (args.get(f"attr_{a.id}") or "").strip()
                if not val:
                    continue
                sub = db.session.query(ProductAttributeValue.product_id).filter(
                    ProductAttributeValue.attribute_id == a.id)
                if a.field_type == "number":
                    try:
                        sub = sub.filter(func.cast(ProductAttributeValue.value, db.Float) >= float(val))
                    except ValueError:
                        continue
                elif a.field_type == "text":
                    sub = sub.filter(ProductAttributeValue.value.ilike(f"%{val}%"))
                else:
                    sub = sub.filter(ProductAttributeValue.value == val)
                q = q.filter(Product.id.in_(sub))

            sort = args.get("sort", "newest")
            if sort == "price_asc":
                q = q.order_by(price_col.asc())
            elif sort == "price_desc":
                q = q.order_by(price_col.desc())
            else:
                q = q.order_by(Product.is_featured.desc(), SORTS.get(sort, SORTS["newest"])[1])
            results = q.paginate(page=args.get("page", 1, type=int),
                                  per_page=current_app.config["ITEMS_PER_PAGE"], error_out=False)
    elif args.get("category", "").isdigit():
        category = db.session.get(Category, int(args["category"]))
        attrs = [a for a in category.all_attributes() if a.is_searchable] if category else []

    return render_template("search.html", categories=active_categories(), errors=errors,
                           results=results, category=category, attrs=attrs, args=args,
                           sorts={k: v[0] for k, v in SORTS.items()}, submitted=submitted)


# ------------------------------------------------------------------- detail
@bp.route("/listing/<ref>")
def listing(ref):
    product = Product.query.filter_by(ref_code=ref).first_or_404()
    owner_or_admin = g.user and (g.user.id == product.user_id or g.user.is_admin)
    if product.status != "approved" and not owner_or_admin:
        abort(404)
    if not owner_or_admin:
        product.views += 1
        db.session.commit()
    similar = (Product.query.filter(Product.status == "approved", Product.id != product.id,
                                    Product.category_id == product.category_id,
                                    Product.listing_type == product.listing_type)
               .order_by(Product.created_at.desc()).limit(4).all())
    attr_rows = [(v.attribute.display_label, v.value) for v in product.attribute_values]
    return render_template("listing.html", p=product, similar=similar, attr_rows=attr_rows,
                           errors={}, form={})


@bp.route("/listing/<ref>/enquire", methods=["POST"])
def enquire(ref):
    product = Product.query.filter_by(ref_code=ref, status="approved").first_or_404()
    if current_app.config["REQUIRE_LOGIN_TO_ENQUIRE"]:
        if g.user is None:
            flash("Please log in or register as a buyer to contact the seller.", "warning")
            return redirect(url_for("auth.login", next=url_for("public.listing", ref=ref)))
        if not g.user.has_permission("enquiry.create"):
            abort(403)
    if g.user is not None and g.user.id == product.user_id:
        flash("You cannot send an enquiry on your own listing.", "warning")
        return redirect(url_for("public.listing", ref=ref))
    f = request.form
    errors = FormErrors()
    etype = "buy" if product.listing_type == "sell" else "rent"
    e = Enquiry(product=product, enquiry_type=etype, user_id=g.user.id if g.user else None)
    e.name = get_str(f, "name", errors, "Your name", max_len=120)
    e.phone = validate_phone(get_str(f, "phone", errors, "Mobile number", max_len=20), "phone", errors)
    e.email = validate_email(get_str(f, "email", errors, "Email", max_len=160), "email", errors)
    e.city = get_str(f, "city", errors, "Your city", max_len=80)
    e.message = get_str(f, "message", errors, "Message", max_len=2000, min_len=10)
    if etype == "buy":
        e.offer_price = get_decimal(f, "offer_price", errors, "Your offer", required=False)
    else:
        e.rent_from = get_date(f, "rent_from", errors, "Rental start date", required=True)
        e.rent_to = get_date(f, "rent_to", errors, "Rental end date", required=True)
        e.work_site = get_str(f, "work_site", errors, "Work site location", max_len=200)
        if e.rent_from and e.rent_from < date.today():
            errors.add("rent_from", "Start date cannot be in the past.")
        if e.rent_from and e.rent_to and e.rent_to < e.rent_from:
            errors.add("rent_to", "End date must be after the start date.")
    if f.get("agree") != "1":
        errors.add("agree", "Please agree to share your details with the seller.")
    if errors:
        attr_rows = [(v.attribute.display_label, v.value) for v in product.attribute_values]
        flash("Please correct the highlighted fields.", "danger")
        return render_template("listing.html", p=product, similar=[], attr_rows=attr_rows,
                               errors=errors, form=f, open_enquiry=True), 422
    db.session.add(e)
    db.session.commit()
    flash("Your enquiry has been sent. The seller will contact you shortly.", "success")
    return redirect(url_for("public.listing", ref=ref))


# ------------------------------------------------------------- post listing
def _listing_form(product, form, errors, title):
    return render_template("post_listing.html", categories=active_categories(), product=product,
                           form=form, errors=errors, page_title=title,
                           current_year=date.today().year)


@bp.route("/post", methods=["GET", "POST"])
@login_required
def post_listing():
    if not g.user.can_post_listings:
        # Buyers can upgrade themselves; partners wait for verification.
        return render_template("account/upgrade.html", wanted=request.args.get("type", "sell")), 403
    if request.method == "POST":
        data, attrs, files, errors = process_product_form(request.form, request.files)
        if errors:
            flash("Please fill in all required fields correctly.", "danger")
            return _listing_form(None, request.form, errors, "Post a listing"), 422
        p = Product(user_id=g.user.id,
                    status="approved" if current_app.config["AUTO_APPROVE_LISTINGS"] else "pending")
        db.session.add(p)
        apply_product_data(p, data, attrs, files, request.form)
        db.session.flush()
        p.ref_code = generate_ref_code(p)
        db.session.commit()
        flash(f"Listing {p.ref_code} submitted. It will be visible once approved by our team."
              if p.status == "pending" else f"Listing {p.ref_code} is live.", "success")
        return redirect(url_for("public.my_listings"))
    form = {"listing_type": request.args.get("type", "sell"), "contact_name": g.user.name,
            "contact_phone": g.user.phone, "contact_email": g.user.email}
    return _listing_form(None, form, {}, "Post a listing")


@bp.route("/my/listings")
@login_required
def my_listings():
    items = g.user.products.order_by(Product.created_at.desc()).all()
    return render_template("my_listings.html", items=items)


def _own_product(pid):
    p = db.session.get(Product, pid)
    if not p or p.user_id != g.user.id:
        abort(404)
    return p


def _product_to_form(p):
    form = {c.name: getattr(p, c.name) for c in Product.__table__.columns}
    for k, v in list(form.items()):
        if v is None:
            form[k] = ""
        elif isinstance(v, bool):
            form[k] = "1" if v else ""
        elif hasattr(v, "isoformat"):
            form[k] = v.isoformat()
        else:
            form[k] = str(v)
    for av in p.attribute_values:
        form[f"attr_{av.attribute_id}"] = "1" if av.value == "Yes" and av.attribute.field_type == "boolean" else av.value
    return form


@bp.route("/my/listings/<int:pid>/edit", methods=["GET", "POST"])
@login_required
def edit_listing(pid):
    p = _own_product(pid)
    if not g.user.can_post_listings:
        return render_template("account/upgrade.html", wanted=p.listing_type), 403
    if request.method == "POST":
        data, attrs, files, errors = process_product_form(request.form, request.files, product=p)
        if errors:
            flash("Please fill in all required fields correctly.", "danger")
            return _listing_form(p, request.form, errors, f"Edit {p.ref_code}"), 422
        apply_product_data(p, data, attrs, files, request.form)
        if p.status in ("approved", "rejected") and not current_app.config["AUTO_APPROVE_LISTINGS"]:
            p.status = "pending"  # re-moderate after edits
        db.session.commit()
        flash("Listing updated and sent for review." if p.status == "pending" else "Listing updated.", "success")
        return redirect(url_for("public.my_listings"))
    return _listing_form(p, _product_to_form(p), {}, f"Edit {p.ref_code}")


@bp.route("/my/listings/<int:pid>/status", methods=["POST"])
@login_required
def listing_status(pid):
    p = _own_product(pid)
    new = request.form.get("status")
    allowed = {"sold", "inactive"} if p.listing_type == "sell" else {"rented", "inactive"}
    if new == "relist" and p.status in ("sold", "rented", "inactive"):
        p.status = "pending"
    elif new in allowed:
        p.status = new
    else:
        abort(400)
    db.session.commit()
    flash("Listing status updated.", "success")
    return redirect(url_for("public.my_listings"))


@bp.route("/my/listings/<int:pid>/delete", methods=["POST"])
@login_required
def delete_listing(pid):
    from utils import delete_image_file
    p = _own_product(pid)
    for img in p.images:
        delete_image_file(img.filename)
    db.session.delete(p)
    db.session.commit()
    flash("Listing deleted.", "success")
    return redirect(url_for("public.my_listings"))


@bp.route("/my/enquiries")
@login_required
def my_enquiries():
    items = (Enquiry.query.join(Product).filter(Product.user_id == g.user.id)
             .order_by(Enquiry.created_at.desc()).all())
    sent = Enquiry.query.filter_by(user_id=g.user.id).order_by(Enquiry.created_at.desc()).all()
    return render_template("my_enquiries.html", items=items, sent=sent)


# ------------------------------------------------------------- requirements
@bp.route("/requirement", methods=["GET", "POST"])
def requirement():
    f = request.form if request.method == "POST" else request.args
    errors = FormErrors()
    if request.method == "POST":
        r = Requirement(user_id=g.user.id if g.user else None)
        r.intent = get_choice(f, "intent", errors, "Buy or rent", ["buy", "rent"])
        r.category_id = get_int(f, "category", errors, "Category")
        if r.category_id and not db.session.get(Category, r.category_id):
            errors.add("category", "Invalid category.")
        r.manufacturer = get_str(f, "manufacturer", errors, "Preferred make", required=False, max_len=120)
        r.budget_max = get_decimal(f, "budget_max", errors, "Budget", required=True)
        r.state = get_choice(f, "state", errors, "State", INDIAN_STATES)
        r.city = get_str(f, "city", errors, "City", max_len=80)
        r.quantity = get_int(f, "quantity", errors, "Quantity", min_v=1, max_v=500)
        r.needed_by = get_date(f, "needed_by", errors, "Needed by", required=True)
        r.name = get_str(f, "name", errors, "Name", max_len=120)
        r.phone = validate_phone(get_str(f, "phone", errors, "Mobile", max_len=20), "phone", errors)
        r.email = validate_email(get_str(f, "email", errors, "Email", max_len=160), "email", errors)
        r.details = get_str(f, "details", errors, "Requirement details", max_len=3000, min_len=20)
        if not errors:
            db.session.add(r)
            db.session.commit()
            flash("Your requirement has been posted. Our team will match you with sellers.", "success")
            return redirect(url_for("public.home"))
        flash("Please correct the highlighted fields.", "danger")
    form = f.to_dict()
    if request.method == "GET" and g.user:
        form.setdefault("name", g.user.name)
        form.setdefault("phone", g.user.phone)
        form.setdefault("email", g.user.email)
    return render_template("requirement.html", categories=active_categories(), form=form,
                           errors=errors), (422 if errors else 200)


# ------------------------------------------------------------- partners
@bp.route("/partners")
def partners():
    """Directory of verified partners: financiers, insurers, inspectors, transporters, dealers."""
    q = (User.query.join(PartnerProfile)
         .filter(User.account_type == "partner", User.is_active.is_(True),
                 User.verification_status == "verified"))
    ptype = request.args.get("type", "")
    state = request.args.get("state", "")
    if ptype in PARTNER_TYPES:
        q = q.filter(PartnerProfile.partner_type == ptype)
    if state in INDIAN_STATES:
        q = q.filter(or_(PartnerProfile.service_states.contains(state),
                         PartnerProfile.service_states.contains("All India")))
    items = [u for u in q.order_by(User.company).all() if u.has_permission("partner.portal")]
    return render_template("partners.html", items=items, ptype=ptype, state=state)


# ------------------------------------------------------------------- JSON API
@bp.route("/api/categories/<int:cid>/meta")
def category_meta(cid):
    cat = db.session.get(Category, cid)
    if not cat or not cat.is_active:
        abort(404)
    items = (Catalogue.query.filter(Catalogue.category_id.in_(category_ids_with_children(cat)),
                                    Catalogue.is_active.is_(True))
             .order_by(Catalogue.manufacturer, Catalogue.model_name).all())
    return jsonify({
        "id": cat.id, "name": cat.name, "group": cat.group, "usage_unit": cat.usage_unit,
        "allow_sell": cat.allow_sell, "allow_rent": cat.allow_rent,
        "has_children": bool(cat.children),
        "catalogue": [{"id": i.id, "manufacturer": i.manufacturer, "name": i.display_name,
                       "model": (i.model_name + (" " + i.variant if i.variant else ""))} for i in items],
        "attributes": [{"id": a.id, "label": a.label, "type": a.field_type, "options": a.option_list,
                        "unit": a.unit or "", "required": a.is_required, "searchable": a.is_searchable}
                       for a in cat.all_attributes()],
    })
