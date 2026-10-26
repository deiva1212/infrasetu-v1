"""Database models for the Infrasetu heavy vehicle & equipment marketplace."""
from datetime import datetime

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()

# ---------------------------------------------------------------- constants
CATEGORY_GROUPS = ["Commercial Vehicle", "Heavy Equipment"]
USAGE_UNITS = {"km": "Kilometres driven", "hours": "Engine hours"}
LISTING_TYPES = {"sell": "For Sale", "rent": "For Rent"}
CONDITIONS = ["New", "Used", "Refurbished"]
FUEL_TYPES = ["Diesel", "CNG", "LNG", "Electric", "Petrol", "Hybrid"]
RENT_PERIODS = ["Hour", "Day", "Week", "Month"]
OWNERSHIP = ["1st Owner", "2nd Owner", "3rd Owner", "4th Owner or more"]
PRODUCT_STATUSES = ["pending", "approved", "rejected", "sold", "rented", "inactive"]
ENQUIRY_STATUSES = ["new", "contacted", "closed"]
ATTRIBUTE_TYPES = {"text": "Text", "number": "Number", "select": "Dropdown", "boolean": "Yes / No"}
INDIAN_STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat",
    "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh",
    "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab",
    "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh",
    "Uttarakhand", "West Bengal", "Andaman and Nicobar Islands", "Chandigarh",
    "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Jammu and Kashmir", "Ladakh",
    "Lakshadweep", "Puducherry",
]


# --------------------------------------------------------- accounts & access
ACCOUNT_TYPES = {"buyer": "Buyer", "seller": "Seller", "partner": "Partner", "staff": "Staff"}
BUYER_TYPES = ["Individual", "Contractor / Builder", "Company / Fleet operator", "Government / PSU"]
SELLER_TYPES = ["Individual owner", "Fleet owner", "Dealer", "Rental company"]
PARTNER_TYPES = ["Dealer / OEM", "Financier / NBFC", "Insurance", "Inspection & Valuation",
                 "Logistics / Transport", "Service & Spares", "Operator / Manpower"]
VERIFICATION_STATUSES = {"not_submitted": "Not submitted", "pending": "Pending review",
                         "verified": "Verified", "rejected": "Rejected"}

# Every permission the application checks. Roles are built from these in the admin panel.
PERMISSION_GROUPS = [
    ("Marketplace", [
        ("enquiry.create", "Contact sellers (send enquiries)"),
        ("listing.create", "Post listings for sale or rent"),
        ("partner.portal", "Partner portal and listing in the partner directory"),
    ]),
    ("Admin panel", [
        ("admin.access", "Sign in to the admin panel"),
        ("dashboard.view", "View the dashboard and statistics"),
    ]),
    ("Catalogue", [
        ("catalogue.manage", "Manage categories, listing fields and make/model catalogue"),
    ]),
    ("Products", [
        ("products.view", "View all listings"),
        ("products.moderate", "Approve, reject or deactivate listings"),
        ("products.edit", "Create, edit, feature and delete any listing"),
    ]),
    ("Leads", [
        ("leads.manage", "Manage enquiries and requirements"),
    ]),
    ("Users", [
        ("users.view", "View users and their activity"),
        ("users.manage", "Create and edit users, suspend, reset passwords"),
        ("users.verify", "Verify seller and partner KYC"),
    ]),
    ("Security", [
        ("roles.manage", "Manage roles and permissions; assign staff roles"),
        ("audit.view", "View the audit log"),
    ]),
]
PERMISSIONS = {code: label for _, perms in PERMISSION_GROUPS for code, label in perms}
MARKETPLACE_PERMISSIONS = {code for code, _ in PERMISSION_GROUPS[0][1]}

# Built-in roles. They are created on startup if missing; admins may change the permissions
# of all of them except Super Admin, but cannot delete them.
SYSTEM_ROLES = [
    ("super_admin", "Super Admin", True, "Full access to everything, including roles.", ["*"]),
    ("moderator", "Listing Moderator", True, "Reviews and edits listings.",
     ["admin.access", "dashboard.view", "products.view", "products.moderate", "products.edit", "users.view"]),
    ("catalogue_manager", "Catalogue Manager", True, "Maintains categories, fields and the make/model catalogue.",
     ["admin.access", "dashboard.view", "catalogue.manage", "products.view"]),
    ("support", "Support & Leads", True, "Handles enquiries, requirements, users and KYC.",
     ["admin.access", "dashboard.view", "leads.manage", "products.view", "users.view", "users.manage",
      "users.verify"]),
    ("buyer", "Buyer", False, "Buys or rents machines.", ["enquiry.create"]),
    ("seller", "Seller", False, "Sells or rents out machines.", ["enquiry.create", "listing.create"]),
    ("partner", "Partner", False, "Dealers, financiers, insurers, inspectors, transporters and service partners.",
     ["enquiry.create", "listing.create", "partner.portal"]),
]


class TimestampMixin:
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


# --------------------------------------------------------------------- users
class User(TimestampMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(160), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(20), nullable=False)
    company = db.Column(db.String(160))
    password_hash = db.Column(db.String(255), nullable=False)
    # Legacy column from v1 (user | admin). Access is now decided by roles; kept so older
    # databases keep working.
    role = db.Column(db.String(20), default="user", nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)  # False = suspended

    account_type = db.Column(db.String(20), default="buyer", nullable=False, index=True)
    business_type = db.Column(db.String(60))  # buyer / seller sub-type
    state = db.Column(db.String(60))
    city = db.Column(db.String(80))
    gstin = db.Column(db.String(15))
    pan = db.Column(db.String(10))
    verification_status = db.Column(db.String(20), default="not_submitted", nullable=False)
    verification_note = db.Column(db.String(255))
    verified_at = db.Column(db.DateTime)
    verified_by_id = db.Column(db.Integer)
    last_login_at = db.Column(db.DateTime)
    failed_logins = db.Column(db.Integer, default=0, nullable=False)
    locked_until = db.Column(db.DateTime)
    password_changed_at = db.Column(db.DateTime)

    products = db.relationship("Product", back_populates="user", lazy="dynamic")
    roles = db.relationship("Role", secondary="user_roles", back_populates="users", lazy="selectin",
                            order_by="Role.name")
    partner_profile = db.relationship("PartnerProfile", back_populates="user", uselist=False,
                                      cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        self.password_changed_at = datetime.utcnow()

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    # ---- access control
    @property
    def permissions(self):
        if any(r.slug == "super_admin" for r in self.roles):
            return set(PERMISSIONS)
        return set().union(*(r.codes for r in self.roles)) if self.roles else set()

    def has_permission(self, code):
        return bool(self.is_active) and code in self.permissions

    def has_role(self, slug):
        return any(r.slug == slug for r in self.roles)

    @property
    def is_admin(self):
        return self.has_permission("admin.access")

    @property
    def is_super_admin(self):
        return bool(self.is_active) and self.has_role("super_admin")

    @property
    def is_verified(self):
        return self.verification_status == "verified"

    @property
    def can_post_listings(self):
        if not self.has_permission("listing.create"):
            return False
        return self.account_type != "partner" or self.is_verified  # partners must be verified first

    @property
    def is_locked(self):
        return bool(self.locked_until and self.locked_until > datetime.utcnow())

    @property
    def account_label(self):
        return ACCOUNT_TYPES.get(self.account_type, self.account_type.title())

    @property
    def display_company(self):
        return self.company or self.name


user_roles = db.Table(
    "user_roles",
    db.Column("user_id", db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    db.Column("role_id", db.Integer, db.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)


class Role(TimestampMixin, db.Model):
    __tablename__ = "roles"
    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(60), unique=True, nullable=False, index=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.String(255))
    is_staff = db.Column(db.Boolean, default=False, nullable=False)  # admin-panel role
    is_system = db.Column(db.Boolean, default=False, nullable=False)  # built in, cannot be deleted

    grants = db.relationship("RolePermission", back_populates="role", cascade="all, delete-orphan")
    users = db.relationship("User", secondary="user_roles", back_populates="roles")

    @property
    def codes(self):
        if self.slug == "super_admin":
            return set(PERMISSIONS)
        return {gr.permission for gr in self.grants}

    def set_codes(self, codes):
        wanted = set(codes) & set(PERMISSIONS)
        for gr in list(self.grants):
            if gr.permission not in wanted:
                self.grants.remove(gr)
        have = {gr.permission for gr in self.grants}
        for code in sorted(wanted - have):
            self.grants.append(RolePermission(permission=code))


class RolePermission(db.Model):
    __tablename__ = "role_permissions"
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    permission = db.Column(db.String(60), primary_key=True)
    role = db.relationship("Role", back_populates="grants")


class PartnerProfile(TimestampMixin, db.Model):
    """Extra details for partner accounts (financiers, transporters, inspectors…)."""
    __tablename__ = "partner_profiles"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    partner_type = db.Column(db.String(60), nullable=False, index=True)
    website = db.Column(db.String(200))
    service_states = db.Column(db.Text, nullable=False, default="")  # comma separated, or "All India"
    description = db.Column(db.Text, nullable=False, default="")

    user = db.relationship("User", back_populates="partner_profile")

    @property
    def state_list(self):
        return [s.strip() for s in (self.service_states or "").split(",") if s.strip()]


class AuditLog(db.Model):
    """Who did what to which record — admin actions and security events."""
    __tablename__ = "audit_logs"
    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action = db.Column(db.String(60), nullable=False, index=True)
    target_type = db.Column(db.String(30))
    target_id = db.Column(db.Integer, index=True)
    details = db.Column(db.Text)
    ip = db.Column(db.String(45))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    actor = db.relationship("User", foreign_keys=[actor_id])


# ---------------------------------------------------------------- categories
class Category(TimestampMixin, db.Model):
    __tablename__ = "categories"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(140), unique=True, nullable=False, index=True)
    group = db.Column(db.String(40), nullable=False, default="Commercial Vehicle")
    parent_id = db.Column(db.Integer, db.ForeignKey("categories.id", ondelete="SET NULL"))
    description = db.Column(db.Text)
    usage_unit = db.Column(db.String(10), nullable=False, default="km")  # km | hours
    allow_sell = db.Column(db.Boolean, default=True, nullable=False)
    allow_rent = db.Column(db.Boolean, default=True, nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    parent = db.relationship("Category", remote_side=[id], backref=db.backref("children", lazy="select"))
    attributes = db.relationship(
        "CategoryAttribute", back_populates="category", cascade="all, delete-orphan",
        order_by="CategoryAttribute.sort_order",
    )
    catalogue_items = db.relationship("Catalogue", back_populates="category", lazy="dynamic")
    products = db.relationship("Product", back_populates="category", lazy="dynamic")

    @property
    def full_name(self):
        return f"{self.parent.name} › {self.name}" if self.parent else self.name

    def all_attributes(self):
        """Attributes of this category plus inherited ones from the parent."""
        inherited = self.parent.all_attributes() if self.parent else []
        return inherited + list(self.attributes)


class CategoryAttribute(db.Model):
    """Admin-defined, category-specific fields (e.g. 'Payload capacity' for trucks,
    'Bucket capacity' for excavators). Shown on the listing & search forms."""
    __tablename__ = "category_attributes"
    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id", ondelete="CASCADE"), nullable=False)
    label = db.Column(db.String(120), nullable=False)
    field_type = db.Column(db.String(20), nullable=False, default="text")
    options = db.Column(db.Text)  # comma separated for select
    unit = db.Column(db.String(30))
    is_required = db.Column(db.Boolean, default=False, nullable=False)
    is_searchable = db.Column(db.Boolean, default=False, nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)

    category = db.relationship("Category", back_populates="attributes")

    @property
    def option_list(self):
        return [o.strip() for o in (self.options or "").split(",") if o.strip()]

    @property
    def display_label(self):
        return f"{self.label} ({self.unit})" if self.unit else self.label


# ----------------------------------------------------------------- catalogue
class Catalogue(TimestampMixin, db.Model):
    """Master list of make / model / variant per category."""
    __tablename__ = "catalogue"
    __table_args__ = (
        db.UniqueConstraint("category_id", "manufacturer", "model_name", "variant", name="uq_catalogue_model"),
    )
    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=False, index=True)
    manufacturer = db.Column(db.String(120), nullable=False, index=True)
    model_name = db.Column(db.String(120), nullable=False)
    variant = db.Column(db.String(120), default="", nullable=False)
    engine_power_hp = db.Column(db.Integer)
    operating_weight_kg = db.Column(db.Integer)  # equipment
    gvw_kg = db.Column(db.Integer)  # vehicles: gross vehicle weight
    specifications = db.Column(db.Text)  # free text "Key: value" per line
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    category = db.relationship("Category", back_populates="catalogue_items")
    products = db.relationship("Product", back_populates="catalogue", lazy="dynamic")

    @property
    def display_name(self):
        parts = [self.manufacturer, self.model_name]
        if self.variant:
            parts.append(self.variant)
        return " ".join(parts)

    @property
    def spec_pairs(self):
        pairs = []
        for line in (self.specifications or "").splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                pairs.append((k.strip(), v.strip()))
        return pairs


# ------------------------------------------------------------------ products
class Product(TimestampMixin, db.Model):
    """A listing: a specific vehicle/machine offered for sale or rent."""
    __tablename__ = "products"
    id = db.Column(db.Integer, primary_key=True)
    ref_code = db.Column(db.String(20), unique=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=False, index=True)
    catalogue_id = db.Column(db.Integer, db.ForeignKey("catalogue.id"), nullable=False, index=True)
    listing_type = db.Column(db.String(10), nullable=False, index=True)  # sell | rent
    title = db.Column(db.String(200), nullable=False)
    manufacture_year = db.Column(db.Integer, nullable=False, index=True)
    condition = db.Column(db.String(20), nullable=False)
    usage_reading = db.Column(db.Integer, nullable=False, default=0)  # km or hours per category
    fuel_type = db.Column(db.String(20), nullable=False)
    registration_no = db.Column(db.String(30))
    ownership = db.Column(db.String(30))
    insurance_valid_till = db.Column(db.Date)
    # sale
    price = db.Column(db.Numeric(14, 2))
    price_negotiable = db.Column(db.Boolean, default=True, nullable=False)
    # rent
    rent_rate = db.Column(db.Numeric(12, 2))
    rent_period = db.Column(db.String(10))
    min_rent_duration = db.Column(db.Integer)
    operator_included = db.Column(db.Boolean, default=False, nullable=False)
    fuel_included = db.Column(db.Boolean, default=False, nullable=False)
    available_from = db.Column(db.Date)
    # location & contact
    state = db.Column(db.String(60), nullable=False, index=True)
    city = db.Column(db.String(80), nullable=False, index=True)
    pincode = db.Column(db.String(10), nullable=False)
    description = db.Column(db.Text, nullable=False)
    contact_name = db.Column(db.String(120), nullable=False)
    contact_phone = db.Column(db.String(20), nullable=False)
    contact_email = db.Column(db.String(160))
    # moderation
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    admin_note = db.Column(db.String(255))
    is_featured = db.Column(db.Boolean, default=False, nullable=False)
    views = db.Column(db.Integer, default=0, nullable=False)

    user = db.relationship("User", back_populates="products")
    category = db.relationship("Category", back_populates="products")
    catalogue = db.relationship("Catalogue", back_populates="products")
    images = db.relationship("ProductImage", back_populates="product", cascade="all, delete-orphan",
                             order_by="ProductImage.sort_order")
    attribute_values = db.relationship("ProductAttributeValue", back_populates="product",
                                       cascade="all, delete-orphan")
    enquiries = db.relationship("Enquiry", back_populates="product", cascade="all, delete-orphan",
                                lazy="dynamic")

    @property
    def cover_image(self):
        return self.images[0].filename if self.images else None

    @property
    def usage_label(self):
        unit = self.category.usage_unit if self.category else "km"
        return f"{self.usage_reading:,} {'km' if unit == 'km' else 'hrs'}"

    def attribute_map(self):
        return {v.attribute_id: v.value for v in self.attribute_values}


class ProductImage(db.Model):
    __tablename__ = "product_images"
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    product = db.relationship("Product", back_populates="images")


class ProductAttributeValue(db.Model):
    __tablename__ = "product_attribute_values"
    __table_args__ = (db.UniqueConstraint("product_id", "attribute_id", name="uq_product_attr"),)
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    attribute_id = db.Column(db.Integer, db.ForeignKey("category_attributes.id", ondelete="CASCADE"),
                             nullable=False, index=True)
    value = db.Column(db.String(255), nullable=False)
    product = db.relationship("Product", back_populates="attribute_values")
    attribute = db.relationship("CategoryAttribute")


# --------------------------------------------------------- leads / enquiries
class Enquiry(db.Model):
    """A buyer or renter contacting the seller about a listing."""
    __tablename__ = "enquiries"
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    enquiry_type = db.Column(db.String(10), nullable=False)  # buy | rent
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(160), nullable=False)
    city = db.Column(db.String(80), nullable=False)
    offer_price = db.Column(db.Numeric(14, 2))
    rent_from = db.Column(db.Date)
    rent_to = db.Column(db.Date)
    work_site = db.Column(db.String(200))
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default="new", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    product = db.relationship("Product", back_populates="enquiries")
    user = db.relationship("User")


class Requirement(db.Model):
    """A 'wanted' request posted by a buyer/renter when search finds nothing suitable."""
    __tablename__ = "requirements"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    intent = db.Column(db.String(10), nullable=False)  # buy | rent
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=False)
    manufacturer = db.Column(db.String(120))
    budget_max = db.Column(db.Numeric(14, 2))
    state = db.Column(db.String(60), nullable=False)
    city = db.Column(db.String(80), nullable=False)
    quantity = db.Column(db.Integer, default=1, nullable=False)
    needed_by = db.Column(db.Date)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(160), nullable=False)
    details = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default="new", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    category = db.relationship("Category")
    user = db.relationship("User")
