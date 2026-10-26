"""Registration (buyer / seller / partner) and the login ecosystem."""
import re
from datetime import datetime, timedelta

from models import Role, User, db
from test_app import csrf, login


def logout(client):
    client.post("/logout", data={"_csrf": csrf(client)})


def base(token, **over):
    data = {"_csrf": token, "name": "Asha Verma", "email": "asha@test.com", "phone": "9812345678",
            "state": "Karnataka", "city": "Mysuru", "password": "Strong123", "confirm": "Strong123", "terms": "1"}
    data.update(over)
    return data


def user(app, email):
    with app.app_context():
        u = User.query.filter_by(email=email).first()
        if u is None:
            return None
        return {"id": u.id, "type": u.account_type, "roles": [r.slug for r in u.roles],
                "kyc": u.verification_status, "post": u.can_post_listings, "active": u.is_active,
                "locked": u.is_locked}


def test_choose_account_type(client):
    html = client.get("/register").get_data(as_text=True)
    for label in ("Register as buyer", "Register as seller", "Register as partner"):
        assert label in html


def test_buyer_registration_validation_and_upgrade(client, app):
    token = csrf(client, "/register?type=buyer")
    r = client.post("/register?type=buyer", data={"_csrf": token})
    html = r.get_data(as_text=True)
    assert r.status_code == 422
    for msg in ["Full name is required", "Email is required", "Mobile number is required",
                "Please select state", "Please select buyer type", "accept the terms"]:
        assert msg in html, msg

    r = client.post("/register?type=buyer", data=base(token, password="password", confirm="other",
                                                       business_type="Contractor / Builder"))
    html = r.get_data(as_text=True)
    assert "letters and numbers" in html and "Passwords do not match" in html
    assert "Company / organisation is required" in html  # non-individual buyers need a company

    r = client.post("/register?type=buyer", data=base(token, email="buyer@example.com", phone="9900011122",
                                                       business_type="Individual"))
    html = r.get_data(as_text=True)
    assert "already exists" in html and "already registered" in html

    r = client.post("/register?type=buyer", data=base(token, business_type="Individual"), follow_redirects=True)
    assert "Welcome to Infrasetu, Asha" in r.get_data(as_text=True)
    u = user(app, "asha@test.com")
    assert u["type"] == "buyer" and u["roles"] == ["buyer"] and not u["post"]

    # buyers can't post until they upgrade
    r = client.get("/post?type=rent")
    assert r.status_code == 403 and "Become a seller" in r.get_data(as_text=True)
    token = csrf(client, "/account")
    r = client.post("/account/become-seller", data={"_csrf": token, "type": "rent"})
    assert r.status_code == 302 and "/post" in r.headers["Location"]
    u = user(app, "asha@test.com")
    assert u["type"] == "seller" and "seller" in u["roles"] and u["post"]
    assert client.get("/post").status_code == 200


def test_seller_registration_kyc_rules(client, app):
    token = csrf(client, "/register?type=seller")
    r = client.post("/register?type=seller", data=base(token, business_type="Dealer", company="Asha Motors"))
    assert "GSTIN is required" in r.get_data(as_text=True)
    r = client.post("/register?type=seller", data=base(token, business_type="Dealer", company="Asha Motors",
                                                        gstin="BADGST"))
    assert "valid 15-character GSTIN" in r.get_data(as_text=True)
    r = client.post("/register?type=seller", data=base(token, business_type="Dealer", company="Asha Motors",
                                                        gstin="29ABCDE1234F1Z5", pan="ZZZZZ9999Z"))
    assert "PAN does not match" in r.get_data(as_text=True)
    r = client.post("/register?type=seller", follow_redirects=True,
                    data=base(token, business_type="Dealer", company="Asha Motors", gstin="29abcde1234f1z5",
                              pan="ABCDE1234F"))
    assert r.status_code == 200
    u = user(app, "asha@test.com")
    assert u["roles"] == ["seller"] and u["kyc"] == "pending" and u["post"]  # sellers can list while KYC pending
    with app.app_context():
        assert User.query.filter_by(email="asha@test.com").one().gstin == "29ABCDE1234F1Z5"


def test_partner_registration_verification_and_directory(client, app):
    token = csrf(client, "/register?type=partner")
    r = client.post("/register?type=partner", data=base(token))
    html = r.get_data(as_text=True)
    for msg in ["Registered company name is required", "GSTIN is required", "Please select partner type",
                "at least one state", "Services offered is required"]:
        assert msg in html, msg
    data = base(token, company="Asha Equipment Finance", gstin="29ABCDE1234F1Z5", partner_type="Financier / NBFC",
                description="Loans for used excavators and tippers across South India, 48 hour decisions.")
    data["service_states"] = ["Karnataka", "Kerala"]
    r = client.post("/register?type=partner", data=data, follow_redirects=True)
    assert "under verification" in r.get_data(as_text=True)
    u = user(app, "asha@test.com")
    assert u["type"] == "partner" and u["kyc"] == "pending" and not u["post"]
    r = client.get("/post")
    assert r.status_code == 403 and "isn't verified" in r.get_data(as_text=True)
    assert "Asha Equipment Finance" not in client.get("/partners").get_data(as_text=True)

    # a support agent verifies the GSTIN
    logout(client)
    login(client, "support@infrasetu.in", "Staff@123")
    token = csrf(client, f"/admin/users/{u['id']}")
    client.post(f"/admin/users/{u['id']}/verify", data={"_csrf": token, "status": "verified"})
    assert user(app, "asha@test.com")["kyc"] == "verified"
    html = client.get("/partners?state=Kerala").get_data(as_text=True)
    assert "Asha Equipment Finance" in html and "9812345678" in html  # logged in: contact visible
    assert "Asha Equipment Finance" not in client.get("/partners?state=Punjab").get_data(as_text=True)
    logout(client)
    html = client.get("/partners").get_data(as_text=True)
    assert "Asha Equipment Finance" in html and "9812345678" not in html  # anonymous: contact hidden
    login(client, "asha@test.com", "Strong123")
    assert client.get("/post").status_code == 200


def test_login_by_mobile_remember_and_open_redirect(client):
    token = csrf(client, "/login")
    r = client.post("/login", data={"_csrf": token, "identifier": "+91 98450 12345", "password": "Seller@123",
                                    "remember": "1"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/account")
    assert "Expires=" in r.headers.get("Set-Cookie", "")  # persistent cookie for "keep me signed in"
    logout(client)
    token = csrf(client, "/login")
    r = client.post("/login?next=//evil.example.com", data={"_csrf": token, "identifier": "ravi@example.com",
                                                             "password": "Seller@123"})
    assert r.headers["Location"].endswith("/account")
    logout(client)
    token = csrf(client, "/login")
    r = client.post("/login", data={"_csrf": token, "identifier": "admin@infrasetu.in", "password": "Admin@123"})
    assert r.headers["Location"].endswith("/admin/")


def test_lockout_after_failed_logins(client, app):
    token = csrf(client, "/login")
    for _ in range(5):
        r = client.post("/login", data={"_csrf": token, "identifier": "ravi@example.com", "password": "wrong1"})
        assert r.status_code == 401
    assert user(app, "ravi@example.com")["locked"]
    r = client.post("/login", data={"_csrf": token, "identifier": "ravi@example.com", "password": "Seller@123"})
    assert r.status_code == 401 and "Too many failed attempts" in r.get_data(as_text=True)
    # admin unlocks
    login(client, "admin@infrasetu.in", "Admin@123")
    uid = user(app, "ravi@example.com")["id"]
    token = csrf(client, f"/admin/users/{uid}")
    client.post(f"/admin/users/{uid}/status", data={"_csrf": token, "action": "unlock"})
    logout(client)
    r = login(client, "ravi@example.com", "Seller@123")
    assert "Ravi Kumar" in r.get_data(as_text=True)


def test_lock_expires(client, app):
    with app.app_context():
        u = User.query.filter_by(email="ravi@example.com").one()
        u.locked_until = datetime.utcnow() - timedelta(minutes=1)
        db.session.commit()
    assert "Ravi Kumar" in login(client, "ravi@example.com", "Seller@123").get_data(as_text=True)


def test_forgot_and_reset_password(client, app):
    token = csrf(client, "/forgot-password")
    r = client.post("/forgot-password", data={"_csrf": token, "email": "nobody@example.com"}, follow_redirects=True)
    assert "If an account exists" in r.get_data(as_text=True)
    r = client.post("/forgot-password", data={"_csrf": token, "email": "ravi@example.com"})
    html = r.get_data(as_text=True)
    assert "If an account exists" in html
    link = re.search(r'data-reset-link>(http[^<]+)<', html).group(1)
    path = link.split("localhost", 1)[1]
    token = csrf(client, path)
    r = client.post(path, data={"_csrf": token, "password": "short", "confirm": "short"})
    assert "at least 8 characters" in r.get_data(as_text=True)
    r = client.post(path, data={"_csrf": token, "password": "NewPass456", "confirm": "NewPass456"},
                    follow_redirects=True)
    assert "password has been reset" in r.get_data(as_text=True)
    # link is single use; old password dead, new one works
    r = client.get(path, follow_redirects=True)
    assert "invalid or has expired" in r.get_data(as_text=True)
    assert "Incorrect" in login(client, "ravi@example.com", "Seller@123").get_data(as_text=True)
    assert "Ravi Kumar" in login(client, "ravi@example.com", "NewPass456").get_data(as_text=True)


def test_change_password_and_profile(client, app):
    login(client, "ravi@example.com", "Seller@123")
    token = csrf(client, "/account/password")
    r = client.post("/account/password", data={"_csrf": token, "current": "nope", "password": "Another789",
                                                "confirm": "Another789"})
    assert "current password is incorrect" in r.get_data(as_text=True)
    r = client.post("/account/password", follow_redirects=True,
                    data={"_csrf": token, "current": "Seller@123", "password": "Another789", "confirm": "Another789"})
    assert "Password changed" in r.get_data(as_text=True)

    # profile: phone must be unique; changing GSTIN of a verified seller re-opens KYC
    assert user(app, "ravi@example.com")["kyc"] == "verified"
    form = {"_csrf": token, "name": "Ravi Kumar", "phone": "9822012345", "state": "Karnataka", "city": "Bengaluru",
            "business_type": "Fleet owner", "company": "Kumar Earthmovers", "gstin": "29AAKPK4321R1Z3"}
    r = client.post("/account/profile", data=form)
    assert "used by another account" in r.get_data(as_text=True)
    form.update(phone="9845012345", gstin="29AAKPK4321R2Z3", pan="")
    r = client.post("/account/profile", data=form, follow_redirects=True)
    assert "Profile saved" in r.get_data(as_text=True)
    assert user(app, "ravi@example.com")["kyc"] == "pending"


def test_suspended_user_is_signed_out(client, app):
    login(client, "buyer@example.com", "Buyer@123")
    assert client.get("/account").status_code == 200
    with app.app_context():
        User.query.filter_by(email="buyer@example.com").one().is_active = False
        db.session.commit()
    assert client.get("/account").status_code == 302  # session dropped on next request
    assert "suspended" in login(client, "buyer@example.com", "Buyer@123").get_data(as_text=True)


def test_legacy_users_get_roles(app):
    """Users from a v1 database (no roles) are backfilled: listers become sellers, admins Super Admin."""
    from db_setup import backfill_user_roles
    with app.app_context():
        ravi = User.query.filter_by(email="ravi@example.com").one()
        buyer = User.query.filter_by(email="meena@example.com").one()
        for u in (ravi, buyer):
            u.roles = []
            u.account_type = "buyer"  # what the column default gives legacy rows
        db.session.commit()
        assert backfill_user_roles() == 2
        assert [r.slug for r in ravi.roles] == ["seller"] and ravi.account_type == "seller"
        assert [r.slug for r in buyer.roles] == ["buyer"]
        assert Role.query.filter_by(is_system=True).count() == 7
