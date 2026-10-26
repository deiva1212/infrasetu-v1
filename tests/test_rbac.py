"""Admin user management, roles & permissions, escalation guards and the audit log."""
import re

from models import AuditLog, Role, User, db
from test_app import csrf, login


def uid(app, email):
    with app.app_context():
        return User.query.filter_by(email=email).one().id


def role_id(app, slug):
    with app.app_context():
        return Role.query.filter_by(slug=slug).one().id


def roles_of(app, email):
    with app.app_context():
        return sorted(r.slug for r in User.query.filter_by(email=email).one().roles)


def flashes(r):
    return " ".join(re.findall(r'class="flash flash-\w+">(.*?)<button', r.get_data(as_text=True), re.S))


def test_staff_permission_matrix(client):
    cases = {
        "moderator@infrasetu.in": {"/admin/": 200, "/admin/products": 200, "/admin/products/1/edit": 200,
                                   "/admin/users": 200, "/admin/categories": 403, "/admin/roles": 403,
                                   "/admin/enquiries": 403, "/admin/users/new": 403, "/admin/audit": 403},
        "catalogue@infrasetu.in": {"/admin/categories": 200, "/admin/catalogue": 200, "/admin/products": 200,
                                   "/admin/products/1/edit": 403, "/admin/users": 403, "/admin/roles": 403},
        "support@infrasetu.in": {"/admin/enquiries": 200, "/admin/requirements": 200, "/admin/users": 200,
                                 "/admin/users/new": 200, "/admin/products/1/edit": 403, "/admin/roles": 403,
                                 "/admin/catalogue": 403},
        "ravi@example.com": {"/admin/": 403, "/admin/users": 403},
    }
    for email, urls in cases.items():
        login(client, email, "Seller@123" if "example" in email else "Staff@123")
        for url, code in urls.items():
            assert client.get(url).status_code == code, (email, url)
        client.post("/logout", data={"_csrf": csrf(client)})


def test_menu_only_shows_permitted_sections(client):
    login(client, "catalogue@infrasetu.in", "Staff@123")
    html = client.get("/admin/catalogue").get_data(as_text=True)
    assert "Catalogue (Make/Model)" in html and "Roles &amp; permissions" not in html and ">Enquiries<" not in html


def test_moderator_can_moderate_but_catalogue_manager_cannot(client, app):
    from models import Product
    with app.app_context():
        pid = Product.query.filter_by(status="pending").first().id
    login(client, "catalogue@infrasetu.in", "Staff@123")
    token = csrf(client, "/admin/products")
    assert client.post(f"/admin/products/{pid}/moderate", data={"_csrf": token, "status": "approved"}).status_code == 403
    client.post("/logout", data={"_csrf": token})
    login(client, "moderator@infrasetu.in", "Staff@123")
    token = csrf(client, "/admin/products")
    client.post(f"/admin/products/{pid}/moderate", data={"_csrf": token, "status": "approved"})
    with app.app_context():
        assert db.session.get(Product, pid).status == "approved"
        assert AuditLog.query.filter_by(action="product.approved", target_id=pid).count() == 1


def test_admin_creates_users_and_assigns_roles(client, app):
    login(client, "admin@infrasetu.in", "Admin@123")
    token = csrf(client, "/admin/users/new")
    r = client.post("/admin/users/new", data={"_csrf": token, "name": "Dev Patel", "email": "dev@infrasetu.in",
                                              "phone": "9811100001", "account_type": "staff"})
    assert "Assign at least one role" in r.get_data(as_text=True)
    r = client.post("/admin/users/new", follow_redirects=True, data={
        "_csrf": token, "name": "Dev Patel", "email": "dev@infrasetu.in", "phone": "9811100001",
        "account_type": "staff", "roles": [str(role_id(app, "moderator"))]})
    msg = flashes(r)
    assert "Temporary password:" in msg
    temp = re.search(r"Temporary password: (\w+)", msg).group(1)
    assert roles_of(app, "dev@infrasetu.in") == ["moderator"]
    client.post("/logout", data={"_csrf": csrf(client)})
    r = login(client, "dev@infrasetu.in", temp)
    assert client.get("/admin/products").status_code == 200


def test_support_cannot_grant_staff_roles(client, app):
    login(client, "support@infrasetu.in", "Staff@123")
    buyer = uid(app, "buyer@example.com")
    token = csrf(client, f"/admin/users/{buyer}")
    r = client.post(f"/admin/users/{buyer}/roles", follow_redirects=True,
                    data={"_csrf": token, "roles": [str(role_id(app, "buyer")), str(role_id(app, "moderator"))]})
    assert "roles.manage" in flashes(r) and roles_of(app, "buyer@example.com") == ["buyer"]
    # marketplace roles are fine
    client.post(f"/admin/users/{buyer}/roles",
                data={"_csrf": token, "roles": [str(role_id(app, "buyer")), str(role_id(app, "seller"))]})
    assert roles_of(app, "buyer@example.com") == ["buyer", "seller"]
    # support may not touch a Super Admin
    admin = uid(app, "admin@infrasetu.in")
    assert client.post(f"/admin/users/{admin}/status", data={"_csrf": token, "action": "suspend"}).status_code == 403
    assert client.post(f"/admin/users/{admin}/password", data={"_csrf": token}).status_code == 403


def test_self_protection_and_super_admin_rules(client, app):
    login(client, "admin@infrasetu.in", "Admin@123")
    me = uid(app, "admin@infrasetu.in")
    token = csrf(client, f"/admin/users/{me}")
    r = client.post(f"/admin/users/{me}/roles", follow_redirects=True,
                    data={"_csrf": token, "roles": [str(role_id(app, "moderator"))]})
    assert "own roles" in flashes(r) and roles_of(app, "admin@infrasetu.in") == ["super_admin"]
    r = client.post(f"/admin/users/{me}/status", follow_redirects=True, data={"_csrf": token, "action": "suspend"})
    assert "cannot suspend" in flashes(r)

    # a non-Super-Admin with roles.manage still cannot hand out Super Admin
    client.post("/admin/roles/new", data={"_csrf": token, "name": "Access Manager", "is_staff": "1",
                                          "permissions": ["users.view", "users.manage", "roles.manage"]})
    with app.app_context():
        am_id = Role.query.filter_by(name="Access Manager").one().id
    sup = uid(app, "support@infrasetu.in")
    client.post(f"/admin/users/{sup}/roles", data={"_csrf": token, "roles": [str(am_id)]})
    assert roles_of(app, "support@infrasetu.in") == ["access_manager"]
    client.post("/logout", data={"_csrf": token})
    login(client, "support@infrasetu.in", "Staff@123")
    buyer = uid(app, "buyer@example.com")
    token = csrf(client, f"/admin/users/{buyer}")
    r = client.post(f"/admin/users/{buyer}/roles", follow_redirects=True,
                    data={"_csrf": token, "roles": [str(role_id(app, "super_admin"))]})
    assert "Only a Super Admin" in flashes(r)
    client.post(f"/admin/users/{buyer}/roles", data={"_csrf": token, "roles": [str(role_id(app, "moderator"))]})
    assert roles_of(app, "buyer@example.com") == ["moderator"]  # other staff roles are allowed


def test_role_crud_and_rules(client, app):
    login(client, "admin@infrasetu.in", "Admin@123")
    token = csrf(client, "/admin/roles/new")
    # staff role always gets admin.access
    r = client.post("/admin/roles/new", follow_redirects=True, data={
        "_csrf": token, "name": "Lead Desk", "description": "Calls back buyers", "is_staff": "1",
        "permissions": ["leads.manage"]})
    assert "Role &#39;Lead Desk&#39; saved" in r.get_data(as_text=True)
    with app.app_context():
        rd = Role.query.filter_by(name="Lead Desk").one()
        assert rd.codes == {"admin.access", "leads.manage"} and rd.slug == "lead_desk"
        rid = rd.id
    # marketplace role can't hold admin permissions
    r = client.post("/admin/roles/new", data={"_csrf": token, "name": "Premium Seller",
                                              "permissions": ["listing.create", "users.manage"]})
    assert "only hold marketplace permissions" in r.get_data(as_text=True)
    # duplicate name
    r = client.post("/admin/roles/new", data={"_csrf": token, "name": "lead desk", "is_staff": "1",
                                              "permissions": ["leads.manage"]})
    assert "already has this name" in r.get_data(as_text=True)
    # Super Admin permissions are locked
    sa = role_id(app, "super_admin")
    client.post(f"/admin/roles/{sa}/edit", data={"_csrf": token, "name": "Super Admin", "permissions": []})
    with app.app_context():
        assert db.session.get(Role, sa).codes == set(__import__("models").PERMISSIONS)
    # built-in roles can't be deleted; roles in use can't be deleted
    r = client.post(f"/admin/roles/{role_id(app, 'buyer')}/delete", data={"_csrf": token}, follow_redirects=True)
    assert "Built-in roles cannot be deleted" in flashes(r)
    client.post(f"/admin/users/{uid(app, 'meena@example.com')}/roles", data={"_csrf": token, "roles": [str(rid)]})
    r = client.post(f"/admin/roles/{rid}/delete", data={"_csrf": token}, follow_redirects=True)
    assert "assigned to 1 user" in flashes(r)

    # a user whose only staff permission is leads.manage lands on Enquiries, not the dashboard
    client.post("/logout", data={"_csrf": token})
    login(client, "meena@example.com", "Buyer@123")
    r = client.get("/admin/")
    assert r.status_code == 302 and r.headers["Location"].endswith("/admin/enquiries")

    # editing a role's permissions changes access immediately
    client.post("/logout", data={"_csrf": csrf(client)})
    login(client, "admin@infrasetu.in", "Admin@123")
    token = csrf(client, f"/admin/roles/{rid}/edit")
    client.post(f"/admin/roles/{rid}/edit", data={"_csrf": token, "name": "Lead Desk", "is_staff": "1",
                                                  "permissions": ["leads.manage", "dashboard.view"]})
    client.post("/logout", data={"_csrf": token})
    login(client, "meena@example.com", "Buyer@123")
    assert client.get("/admin/").status_code == 200


def test_marketplace_role_permissions_are_enforced(client, app):
    """Removing listing.create from the Seller role stops every seller from posting."""
    login(client, "admin@infrasetu.in", "Admin@123")
    seller = role_id(app, "seller")
    token = csrf(client, f"/admin/roles/{seller}/edit")
    client.post(f"/admin/roles/{seller}/edit", data={"_csrf": token, "name": "Seller",
                                                     "permissions": ["enquiry.create"]})
    client.post("/logout", data={"_csrf": token})
    login(client, "ravi@example.com", "Seller@123")
    assert client.get("/post").status_code == 403


def test_kyc_review_password_reset_suspend_delete(client, app):
    login(client, "support@infrasetu.in", "Staff@123")
    fatima = uid(app, "fatima@example.com")
    token = csrf(client, f"/admin/users/{fatima}")
    r = client.post(f"/admin/users/{fatima}/verify", follow_redirects=True, data={"_csrf": token, "status": "rejected"})
    assert "give a reason" in flashes(r)
    client.post(f"/admin/users/{fatima}/verify", data={"_csrf": token, "status": "rejected",
                                                        "note": "Blurry GST certificate"})
    with app.app_context():
        u = db.session.get(User, fatima)
        assert u.verification_status == "rejected" and u.verification_note == "Blurry GST certificate"

    # temporary password
    r = client.post(f"/admin/users/{fatima}/password", data={"_csrf": token}, follow_redirects=True)
    temp = re.search(r"Temporary password for \S+: (\w+)", flashes(r)).group(1)

    # suspend → cannot log in; re-activate → can, with the temp password
    client.post(f"/admin/users/{fatima}/status", data={"_csrf": token, "action": "suspend"})
    client.post("/logout", data={"_csrf": token})
    assert "suspended" in login(client, "fatima@example.com", temp).get_data(as_text=True)
    login(client, "support@infrasetu.in", "Staff@123")
    token = csrf(client, "/admin/users")
    client.post(f"/admin/users/{fatima}/status", data={"_csrf": token, "action": "activate"})
    client.post("/logout", data={"_csrf": token})
    assert "Fatima" in login(client, "fatima@example.com", temp).get_data(as_text=True)
    client.post("/logout", data={"_csrf": csrf(client)})

    # delete: refused for users with listings, allowed for a fresh account
    login(client, "support@infrasetu.in", "Staff@123")
    token = csrf(client, "/admin/users")
    r = client.post(f"/admin/users/{fatima}/delete", data={"_csrf": token}, follow_redirects=True)
    assert "Suspend the account instead" in flashes(r)
    meena = uid(app, "meena@example.com")
    r = client.post(f"/admin/users/{meena}/delete", data={"_csrf": token}, follow_redirects=True)
    assert "User deleted" in flashes(r)

    # everything above is in the audit log
    with app.app_context():
        actions = {a.action for a in AuditLog.query.all()}
    for a in ("user.kyc_rejected", "user.password_reset", "user.suspend", "user.activate", "user.delete"):
        assert a in actions, a
    client.post("/logout", data={"_csrf": token})
    login(client, "admin@infrasetu.in", "Admin@123")
    html = client.get("/admin/audit?action=user.").get_data(as_text=True)
    assert "user.kyc_rejected" in html and "Blurry GST certificate" in html


def test_user_list_filters(client, app):
    login(client, "admin@infrasetu.in", "Admin@123")
    html = client.get("/admin/users?type=partner").get_data(as_text=True)
    assert "Sahyadri Equipment Finance" in html and "Ravi Kumar" not in html
    html = client.get("/admin/users?kyc=pending").get_data(as_text=True)
    assert "Ironclad Inspections" in html and "Sahyadri" not in html
    html = client.get(f"/admin/users?role={role_id(app, 'moderator')}").get_data(as_text=True)
    assert "Meera Nair" in html and "Kiran Rao" not in html
