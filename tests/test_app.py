"""End-to-end tests for the public marketplace and admin back office.  Run: pytest -q"""
import io
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from config import Config  # noqa: E402
from models import Catalogue, Category, CategoryAttribute, Enquiry, Product, Requirement, User, db  # noqa: E402

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
       b"\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")


def csrf(client, url="/"):
    html = client.get(url).get_data(as_text=True)
    return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)


def login(client, email, pw):
    token = csrf(client, "/login")
    return client.post("/login", data={"_csrf": token, "email": email, "password": pw}, follow_redirects=True)


def leaf(app, name):
    with app.app_context():
        c = Category.query.filter_by(name=name).first()
        return c.id, [i.id for i in c.catalogue_items], {a.label: a.id for a in c.all_attributes()}


# ------------------------------------------------------------------ public
def test_home_and_listing_pages(client, app):
    r = client.get("/")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "Buy, sell and rent" in html
    assert ">Excavators</option>" in html  # category dropdown populated
    assert "↳ Tipper</option>" in client.get("/search").get_data(as_text=True)
    with app.app_context():
        p = Product.query.filter_by(status="approved").first()
        hidden = Product.query.filter_by(status="pending").first()
    assert client.get(f"/listing/{p.ref_code}").status_code == 200
    assert client.get(f"/listing/{hidden.ref_code}").status_code == 404


def test_search_requires_required_fields(client):
    r = client.get("/search?submitted=1")
    html = r.get_data(as_text=True)
    assert "A few details are missing" in html
    assert "Please select buy or rent" in html and "Category is required" in html
    assert "Please select location (state)" in html


def test_search_returns_filtered_results(client, app):
    with app.app_context():
        exc = Category.query.filter_by(name="Excavators").first()
        expected = Product.query.filter_by(category_id=exc.id, status="approved", listing_type="rent").count()
    r = client.get(f"/search?submitted=1&intent=rent&category={exc.id}&state=ALL")
    html = r.get_data(as_text=True)
    assert f"{expected} Excavators for rent" in html
    # parent category search includes sub-categories
    with app.app_context():
        trucks = Category.query.filter_by(name="Trucks").first()
    r = client.get(f"/search?submitted=1&intent=buy&category={trucks.id}&state=ALL&sort=price_asc")
    assert r.status_code == 200 and "Trucks for sale" in r.get_data(as_text=True)


def test_category_meta_api(client, app):
    cid, items, attrs = leaf(app, "Tipper")
    data = client.get(f"/api/categories/{cid}/meta").get_json()
    assert data["usage_unit"] == "km" and data["group"] == "Commercial Vehicle"
    assert {a["label"] for a in data["attributes"]} >= {"Axle configuration", "Payload capacity"}  # inherited
    assert len(data["catalogue"]) == len(items)


def listing_payload(token, cid, model, attrs, **over):
    data = {
        "_csrf": token, "listing_type": "sell", "category_id": str(cid), "catalogue_id": str(model),
        "title": "2020 Tata Signa 2823.K tipper in great shape", "manufacture_year": "2020",
        "condition": "Used", "usage_reading": "120000", "fuel_type": "Diesel", "registration_no": "KA 01 AB 1234",
        "ownership": "1st Owner", "price": "2850000", "state": "Karnataka", "city": "Bengaluru",
        "pincode": "560058", "description": "Single owner tipper, serviced at dealer, all papers clear, tyres 80%.",
        "contact_name": "Test Seller", "contact_phone": "9845011111", "contact_email": "seller@test.com",
        f"attr_{attrs['Axle configuration']}": "6x4", f"attr_{attrs['Payload capacity']}": "18",
        f"attr_{attrs['Body type']}": "Box body", f"attr_{attrs['Number of tyres']}": "10",
        "images": (io.BytesIO(PNG), "truck.png"),
    }
    data.update(over)
    return data


def test_post_listing_validation_and_create(client, app):
    assert client.get("/post").status_code == 302  # login required
    login(client, "ravi@example.com", "Seller@123")
    cid, items, attrs = leaf(app, "Tipper")
    token = csrf(client, "/post")

    # missing required fields → 422 with messages
    bad = listing_payload(token, cid, items[0], attrs, price="", registration_no="", pincode="12")
    bad.pop(f"attr_{attrs['Payload capacity']}")
    bad.pop("images")
    r = client.post("/post", data=bad, content_type="multipart/form-data")
    html = r.get_data(as_text=True)
    assert r.status_code == 422
    for msg in ["Expected price is required", "Registration number is required", "Pincode must be 6 digits",
                "Payload capacity is required", "upload at least one photo"]:
        assert msg in html, msg

    # rent listing needs rental fields
    rent = listing_payload(token, cid, items[0], attrs, listing_type="rent")
    r = client.post("/post", data=rent, content_type="multipart/form-data")
    assert r.status_code == 422 and "Rental rate is required" in r.get_data(as_text=True)

    # valid listing
    r = client.post("/post", data=listing_payload(token, cid, items[0], attrs), content_type="multipart/form-data",
                    follow_redirects=True)
    assert r.status_code == 200 and "submitted" in r.get_data(as_text=True)
    with app.app_context():
        p = Product.query.filter_by(title="2020 Tata Signa 2823.K tipper in great shape").one()
        assert p.status == "pending" and p.ref_code.startswith("ISS") and p.registration_no == "KA01AB1234"
        assert len(p.images) == 1 and len(p.attribute_values) == 4


def test_enquiry_flow(client, app):
    with app.app_context():
        p = Product.query.filter_by(status="approved", listing_type="rent").first()
    # anonymous visitors are asked to log in first
    html = client.get(f"/listing/{p.ref_code}").get_data(as_text=True)
    assert "Log in to contact seller" in html
    token = csrf(client, f"/listing/{p.ref_code}")
    r = client.post(f"/listing/{p.ref_code}/enquire", data={"_csrf": token, "name": "A"})
    assert r.status_code == 302 and "/login" in r.headers["Location"]
    login(client, "buyer@example.com", "Buyer@123")
    token = csrf(client, f"/listing/{p.ref_code}")
    r = client.post(f"/listing/{p.ref_code}/enquire", data={"_csrf": token, "name": "A"})
    assert r.status_code == 422 and "Rental start date is required" in r.get_data(as_text=True)
    from datetime import date, timedelta
    r = client.post(f"/listing/{p.ref_code}/enquire", follow_redirects=True, data={
        "_csrf": token, "name": "Buyer One", "phone": "+91 98450 22222", "email": "b@x.com", "city": "Hosur",
        "rent_from": (date.today() + timedelta(days=2)).isoformat(),
        "rent_to": (date.today() + timedelta(days=30)).isoformat(),
        "work_site": "Hosur SIPCOT", "message": "Need for one month urgently", "agree": "1"})
    assert "enquiry has been sent" in r.get_data(as_text=True)
    with app.app_context():
        e = Enquiry.query.filter_by(name="Buyer One").one()
        assert e.phone == "9845022222" and e.user.email == "buyer@example.com"


def test_requirement_post(client, app):
    cid, _, _ = leaf(app, "Excavators")
    token = csrf(client, "/requirement")
    r = client.post("/requirement", follow_redirects=True, data={
        "_csrf": token, "intent": "buy", "category": cid, "budget_max": "3500000", "state": "Karnataka",
        "city": "Hassan", "quantity": "1", "needed_by": "2027-01-15", "name": "R", "phone": "9900011111",
        "email": "r@x.com", "details": "Looking for 20 ton excavator 2018 or newer"})
    assert "requirement has been posted" in r.get_data(as_text=True)
    with app.app_context():
        assert Requirement.query.count() == 2


def test_csrf_enforced(client):
    r = client.post("/login", data={"email": "x", "password": "y"})
    assert r.status_code == 400


# ------------------------------------------------------------------ admin
def test_admin_requires_admin(client):
    assert client.get("/admin/").status_code == 302
    login(client, "ravi@example.com", "Seller@123")
    assert client.get("/admin/").status_code == 403


def test_admin_pages_render(client):
    login(client, "admin@infrasetu.in", "Admin@123")
    for url in ["/admin/", "/admin/categories", "/admin/categories/new", "/admin/categories/1/edit",
                "/admin/catalogue", "/admin/catalogue/new", "/admin/catalogue/1/edit", "/admin/products",
                "/admin/products?status=pending", "/admin/products/new", "/admin/products/1/edit",
                "/admin/enquiries", "/admin/requirements", "/admin/users", "/admin/catalogue?export=csv",
                "/admin/users/new", "/admin/users/1", "/admin/users/5", "/admin/users?kyc=pending&type=partner",
                "/admin/roles", "/admin/roles/new", "/admin/roles/1/edit", "/admin/audit"]:
        assert client.get(url).status_code == 200, url


def test_admin_category_and_attribute_crud(client, app):
    login(client, "admin@infrasetu.in", "Admin@123")
    token = csrf(client, "/admin/categories/new")
    r = client.post("/admin/categories/new", follow_redirects=True, data={
        "_csrf": token, "name": "Pavers", "group": "Heavy Equipment", "usage_unit": "hours",
        "allow_sell": "1", "allow_rent": "1", "is_active": "1"})
    assert "Category &#39;Pavers&#39; saved" in r.get_data(as_text=True)
    with app.app_context():
        cat = Category.query.filter_by(slug="pavers").one()
        cid = cat.id
    r = client.post(f"/admin/categories/{cid}/attributes", follow_redirects=True, data={
        "_csrf": token, "label": "Paving width", "field_type": "number", "unit": "m", "is_required": "1"})
    assert "Paving width" in r.get_data(as_text=True)
    # duplicate slug rejected
    r = client.post("/admin/categories/new", data={"_csrf": token, "name": "Pavers", "group": "Heavy Equipment",
                                                   "usage_unit": "hours", "allow_sell": "1"})
    assert "already used" in r.get_data(as_text=True)
    # cannot delete category with products
    with app.app_context():
        busy = Category.query.filter_by(name="Excavators").one().id
    r = client.post(f"/admin/categories/{busy}/delete", data={"_csrf": token}, follow_redirects=True)
    assert "Cannot delete" in r.get_data(as_text=True)
    r = client.post(f"/admin/categories/{cid}/delete", data={"_csrf": token}, follow_redirects=True)
    assert "Category deleted" in r.get_data(as_text=True)


def test_admin_catalogue_crud_and_import(client, app):
    login(client, "admin@infrasetu.in", "Admin@123")
    cid, _, _ = leaf(app, "Excavators")
    token = csrf(client, "/admin/catalogue/new")
    r = client.post("/admin/catalogue/new", follow_redirects=True, data={
        "_csrf": token, "category_id": cid, "manufacturer": "SANY", "model_name": "SY215C", "engine_power_hp": "150",
        "specifications": "Bucket: 1.0 cu m", "is_active": "1"})
    assert "SANY SY215C" in r.get_data(as_text=True)
    r = client.post("/admin/catalogue/new", data={"_csrf": token, "category_id": cid, "manufacturer": "SANY",
                                                  "model_name": "SY215C", "is_active": "1"})
    assert "already exists" in r.get_data(as_text=True)
    csv_data = "category_slug,manufacturer,model_name,variant,engine_power_hp\nexcavators,Kobelco,SK220,,160\nnope,X,Y,,\n"
    r = client.post("/admin/catalogue/import", follow_redirects=True, content_type="multipart/form-data",
                    data={"_csrf": token, "file": (io.BytesIO(csv_data.encode()), "c.csv")})
    assert "1 added, 0 updated, 1 skipped" in r.get_data(as_text=True)


def test_admin_product_moderation_and_edit(client, app):
    login(client, "admin@infrasetu.in", "Admin@123")
    with app.app_context():
        p = Product.query.filter_by(status="pending").first()
        pid, ref = p.id, p.ref_code
    token = csrf(client, "/admin/products")
    client.post(f"/admin/products/{pid}/moderate", data={"_csrf": token, "status": "approved"})
    with app.app_context():
        assert db.session.get(Product, pid).status == "approved"
    # bulk feature
    client.post("/admin/products/bulk", data={"_csrf": token, "ids": [str(pid)], "action": "feature"})
    with app.app_context():
        assert db.session.get(Product, pid).is_featured
    # full edit round trip: GET form then POST it back with a change
    html = client.get(f"/admin/products/{pid}/edit").get_data(as_text=True)
    assert ref in html
    with app.app_context():
        from public import _product_to_form
        form = _product_to_form(db.session.get(Product, pid))
    form = {k: v for k, v in form.items() if v not in ("", None)}
    form.update(_csrf=token, city="Hubballi", status="approved")
    r = client.post(f"/admin/products/{pid}/edit", data=form, follow_redirects=True)
    assert r.status_code == 200, r.get_data(as_text=True)[:3000]
    with app.app_context():
        assert db.session.get(Product, pid).city == "Hubballi"


def test_admin_login_works_without_seed():
    """Fresh, empty database (seed never run): default admin must still be able to log in."""
    tmp = tempfile.mkdtemp()

    class EmptyConfig(Config):
        SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(tmp, "empty.db")
        UPLOAD_FOLDER = os.path.join(tmp, "uploads")
        TESTING = True

    app = create_app(EmptyConfig)
    c = app.test_client()
    r = login(c, "admin@infrasetu.in", "Admin@123")
    assert "Dashboard" in r.get_data(as_text=True)
    assert c.get("/admin/").status_code == 200
