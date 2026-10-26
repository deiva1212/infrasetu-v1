"""Sample data: categories with category-specific fields, catalogue of makes/models, users and listings."""
import random
from datetime import date, datetime, timedelta
from decimal import Decimal

from models import (Catalogue, Category, CategoryAttribute, Enquiry, PartnerProfile, Product,
                    ProductAttributeValue, Requirement, Role, User, db)
from utils import generate_ref_code, slugify

CV, HE = "Commercial Vehicle", "Heavy Equipment"

# name, group, usage unit, allow_sell, allow_rent, [children], [attributes]
# attribute: (label, type, options, unit, required, searchable)
AXLE = ("Axle configuration", "select", "4x2, 6x2, 6x4, 8x2, 8x4, 10x2, 10x4, 12x4", "", True, True)
CATEGORIES = [
    ("Trucks", CV, "km", True, True, ["Haulage Truck", "Tipper", "Container Truck", "Tanker"], [
        AXLE,
        ("Payload capacity", "number", "", "tonne", True, True),
        ("Body type", "select", "Open body, Box body, Rock body, Container, Tanker, Flatbed, Refrigerated", "", True, False),
        ("Cabin type", "select", "Day cab, Sleeper cab", "", False, True),
        ("National permit", "boolean", "", "", False, True),
        ("Number of tyres", "number", "", "", True, False),
    ]),
    ("Trailers", CV, "km", True, True, ["Prime Mover / Tractor Head", "Flatbed Trailer", "Low Bed Trailer"], [
        AXLE,
        ("Trailer length", "number", "", "ft", False, True),
        ("Fifth wheel / king pin", "select", "50 mm, 90 mm", "", False, False),
    ]),
    ("Buses", CV, "km", True, True, ["Staff Bus", "School Bus", "Coach"], [
        ("Seating capacity", "number", "", "seats", True, True),
        ("Air conditioned", "boolean", "", "", True, True),
        ("Permit type", "select", "Contract carriage, Stage carriage, Educational institution, Private", "", True, False),
    ]),
    ("Transit Mixers", CV, "km", True, True, [], [
        ("Drum capacity", "number", "", "cu m", True, True),
        AXLE,
    ]),
    ("Excavators", HE, "hours", True, True, [], [
        ("Bucket capacity", "number", "", "cu m", True, True),
        ("Undercarriage", "select", "Crawler, Wheeled", "", True, True),
        ("Attachments", "text", "", "", False, False),
        ("Rock breaker line", "boolean", "", "", False, True),
    ]),
    ("Backhoe Loaders", HE, "hours", True, True, [], [
        ("Loader bucket capacity", "number", "", "cu m", True, False),
        ("4WD", "boolean", "", "", True, True),
        ("Extendable dipper", "boolean", "", "", False, False),
    ]),
    ("Wheel Loaders", HE, "hours", True, True, [], [
        ("Bucket capacity", "number", "", "cu m", True, True),
    ]),
    ("Cranes", HE, "hours", True, True, ["Mobile / Pick & Carry Crane", "Truck Mounted Crane", "Crawler Crane"], [
        ("Lifting capacity", "number", "", "tonne", True, True),
        ("Boom length", "number", "", "m", True, True),
        ("Load moment indicator (LMI)", "boolean", "", "", False, False),
    ]),
    ("Motor Graders", HE, "hours", True, True, [], [
        ("Blade width", "number", "", "ft", True, True),
    ]),
    ("Road Rollers", HE, "hours", True, True, [], [
        ("Roller type", "select", "Single drum vibratory, Tandem vibratory, Pneumatic tyre, Static", "", True, True),
        ("Operating weight class", "number", "", "tonne", True, True),
    ]),
    ("Bulldozers", HE, "hours", True, True, [], [
        ("Blade type", "select", "Straight, Semi-U, Universal", "", True, True),
        ("Ripper", "boolean", "", "", False, True),
    ]),
    ("Forklifts", HE, "hours", True, True, [], [
        ("Lifting capacity", "number", "", "tonne", True, True),
        ("Mast height", "number", "", "m", False, False),
    ]),
]

# category name (leaf), manufacturer, model, variant, hp, gvw/op weight, specs
CATALOGUE = [
    ("Haulage Truck", "Tata Motors", "Signa 4825.T", "", 250, 47500, "Engine: Cummins ISBe 6.7L\nTransmission: 9 speed\nAxle: 6x4"),
    ("Haulage Truck", "Ashok Leyland", "4220", "Lift Axle", 220, 42000, "Engine: H6 CRS\nTransmission: 9 speed"),
    ("Haulage Truck", "BharatBenz", "3528R", "", 280, 35000, "Engine: OM926 7.2L\nTransmission: G131 9 speed"),
    ("Haulage Truck", "Eicher", "Pro 6035", "", 200, 35000, "Engine: VEDX8\nTransmission: 9 speed"),
    ("Tipper", "Tata Motors", "Signa 2823.K", "16 cum box body", 230, 28000, "Engine: Cummins ISBe 5.6L\nBody: Box 16 cu m"),
    ("Tipper", "Tata Motors", "Prima 2830.K", "Rock body", 300, 28000, "Engine: Cummins ISBe 6.7L\nBody: Rock"),
    ("Tipper", "Ashok Leyland", "2825 Tipper", "", 250, 28000, "Engine: H6\nBody: Box 18 cu m"),
    ("Tipper", "BharatBenz", "2828C", "", 280, 28000, "Engine: OM926\nBody: Box / Rock"),
    ("Tipper", "Volvo", "FMX 460", "8x4", 460, 49000, "Engine: D13 12.8L\nTransmission: I-Shift"),
    ("Container Truck", "Tata Motors", "LPT 1918", "32 ft container", 180, 18500, "Engine: 5.6L\nBody: 32 ft container"),
    ("Container Truck", "Ashok Leyland", "Ecomet 1615", "", 150, 16200, "Engine: H4 4-cyl"),
    ("Tanker", "Tata Motors", "LPT 2818", "Water tanker 18KL", 180, 28000, "Body: MS tank 18,000 L"),
    ("Prime Mover / Tractor Head", "Tata Motors", "Signa 5530.S", "", 300, 55000, "Engine: Cummins 6.7L"),
    ("Prime Mover / Tractor Head", "Volvo", "FM 420", "4x2 tractor", 420, 49000, "Engine: D13"),
    ("Flatbed Trailer", "Sri Venkateswara", "40 ft Flatbed", "3 axle", None, 45000, "Axles: 3\nLength: 40 ft"),
    ("Low Bed Trailer", "Sri Venkateswara", "Low Bed 60T", "", None, 70000, "Capacity: 60 t\nDeck height: 900 mm"),
    ("Staff Bus", "Tata Motors", "Starbus Ultra", "41 seater", 150, 14000, "Seats: 41\nEngine: 3.8L"),
    ("Staff Bus", "Ashok Leyland", "Falcon", "45 seater AC", 180, 16000, "Seats: 45"),
    ("School Bus", "Eicher", "Skyline Pro", "50 seater", 135, 12000, "Seats: 50"),
    ("Coach", "Volvo", "9600", "Multi-axle sleeper", 430, 25000, "Engine: D11"),
    ("Coach", "BharatBenz", "1624 Coach", "", 240, 16200, "Seats: 49"),
    ("Transit Mixers", "Schwing Stetter", "AM 7 CM", "On Tata 2823", 230, 28000, "Drum: 7 cu m"),
    ("Transit Mixers", "Ajax Fiori", "ARGO 4000", "Self loading", 101, 7600, "Drum: 4 cu m\nSelf-loading"),
    ("Excavators", "Tata Hitachi", "EX 200LC", "Super+", 140, 20000, "Engine: Isuzu 4HK1\nBucket: 0.9 cu m"),
    ("Excavators", "Komatsu", "PC210", "LC-10M0", 155, 21000, "Engine: SAA6D107E\nBucket: 1.0 cu m"),
    ("Excavators", "JCB", "JS205", "LC", 138, 20500, "Engine: JCB EcoMAX\nBucket: 0.93 cu m"),
    ("Excavators", "CAT", "320D3", "", 145, 21500, "Engine: C7.1\nBucket: 1.0 cu m"),
    ("Excavators", "Hyundai", "R215L Smart", "", 150, 21800, "Bucket: 0.92 cu m"),
    ("Excavators", "Volvo", "EC210D", "", 160, 21000, "Engine: D5"),
    ("Backhoe Loaders", "JCB", "3DX", "Super", 76, 7660, "Engine: JCB EcoMAX 4.4L\nLoader bucket: 1.1 cu m"),
    ("Backhoe Loaders", "JCB", "3DX Xtra", "Eco", 76, 8000, "Engine: JCB 448"),
    ("Backhoe Loaders", "CASE", "770 NX", "", 76, 7500, "Loader bucket: 1.0 cu m"),
    ("Backhoe Loaders", "Mahindra", "EarthMaster SX", "", 74, 7200, "Engine: Mahindra"),
    ("Backhoe Loaders", "CAT", "424", "", 75, 7400, "Engine: C3.6"),
    ("Wheel Loaders", "LiuGong", "856H", "", 220, 17500, "Bucket: 3.0 cu m"),
    ("Wheel Loaders", "Komatsu", "WA320", "", 165, 15000, "Bucket: 2.5 cu m"),
    ("Mobile / Pick & Carry Crane", "ACE", "NX 360", "", 76, 12000, "Capacity: 14 t\nBoom: 17.7 m"),
    ("Mobile / Pick & Carry Crane", "Escorts", "Hydra 14 FX", "", 75, 11000, "Capacity: 14 t"),
    ("Truck Mounted Crane", "TIL", "Tadano TM-ZE", "25 t", 270, 27000, "Capacity: 25 t\nBoom: 33 m"),
    ("Crawler Crane", "Sany", "SCC800A", "80 t", 270, 72000, "Capacity: 80 t\nBoom: 58 m"),
    ("Motor Graders", "CAT", "120K", "", 145, 13700, "Blade: 12 ft"),
    ("Motor Graders", "Mahindra", "RoadMaster G9075", "", 75, 9500, "Blade: 10 ft"),
    ("Road Rollers", "Hamm", "HD 99", "Tandem", 120, 9800, "Drum width: 1,680 mm"),
    ("Road Rollers", "Volvo", "SD110", "Single drum", 130, 11000, "Drum width: 2,130 mm"),
    ("Road Rollers", "Ammann", "ARS 110", "", 120, 11000, "Single drum vibratory"),
    ("Bulldozers", "BEML", "BD 155", "", 180, 18000, "Engine: BEML 6D"),
    ("Bulldozers", "CAT", "D6R", "", 175, 19000, "Engine: C9"),
    ("Forklifts", "Godrej", "GX 300", "Diesel 3T", 50, 4300, "Capacity: 3 t"),
    ("Forklifts", "Toyota", "8FD30", "", 60, 4500, "Capacity: 3 t"),
]

CITIES = [("Karnataka", "Bengaluru", "560058"), ("Maharashtra", "Pune", "411019"), ("Tamil Nadu", "Chennai", "600032"),
          ("Telangana", "Hyderabad", "500032"), ("Gujarat", "Ahmedabad", "382445"), ("Delhi", "New Delhi", "110041"),
          ("Uttar Pradesh", "Lucknow", "226010"), ("Odisha", "Bhubaneswar", "751024"), ("Karnataka", "Mysuru", "570016"),
          ("Rajasthan", "Jaipur", "302013"), ("West Bengal", "Kolkata", "700088"), ("Maharashtra", "Nagpur", "440016")]

RTO = {"Karnataka": "KA", "Maharashtra": "MH", "Tamil Nadu": "TN", "Telangana": "TS", "Gujarat": "GJ", "Delhi": "DL",
       "Uttar Pradesh": "UP", "Odisha": "OD", "Rajasthan": "RJ", "West Bengal": "WB"}

ATTR_VALUES = {
    "Axle configuration": lambda c: random.choice(["6x4", "8x4", "10x4", "4x2", "6x2"]),
    "Payload capacity": lambda c: str(random.choice([16, 18, 25, 28, 31, 35])),
    "Body type": lambda c: {"Tipper": random.choice(["Box body", "Rock body"]), "Container Truck": "Container",
                            "Tanker": "Tanker"}.get(c, random.choice(["Open body", "Flatbed", "Box body"])),
    "Cabin type": lambda c: random.choice(["Day cab", "Sleeper cab"]),
    "National permit": lambda c: random.choice(["Yes", "No"]),
    "Number of tyres": lambda c: str(random.choice([10, 12, 14, 16])),
    "Trailer length": lambda c: str(random.choice([32, 40, 48])),
    "Seating capacity": lambda c: str(random.choice([32, 41, 45, 50])),
    "Air conditioned": lambda c: random.choice(["Yes", "No"]),
    "Permit type": lambda c: {"School Bus": "Educational institution"}.get(c, random.choice(["Contract carriage", "Private"])),
    "Drum capacity": lambda c: str(random.choice([4, 6, 7, 8])),
    "Bucket capacity": lambda c: str(random.choice([0.9, 1.0, 1.2, 2.5, 3.0])),
    "Undercarriage": lambda c: "Crawler",
    "Attachments": lambda c: random.choice(["GP bucket", "GP bucket, rock bucket", "Rock breaker, GP bucket"]),
    "Rock breaker line": lambda c: random.choice(["Yes", "No"]),
    "Loader bucket capacity": lambda c: str(random.choice([1.0, 1.1])),
    "4WD": lambda c: random.choice(["Yes", "No"]),
    "Extendable dipper": lambda c: random.choice(["Yes", "No"]),
    "Lifting capacity": lambda c: str(random.choice([3, 14, 25, 80])),
    "Boom length": lambda c: str(random.choice([17.7, 33, 58])),
    "Load moment indicator (LMI)": lambda c: "Yes",
    "Blade width": lambda c: str(random.choice([10, 12])),
    "Roller type": lambda c: random.choice(["Single drum vibratory", "Tandem vibratory"]),
    "Operating weight class": lambda c: str(random.choice([10, 11])),
    "Blade type": lambda c: random.choice(["Straight", "Semi-U"]),
    "Ripper": lambda c: random.choice(["Yes", "No"]),
}


def seed():
    random.seed(42)
    db.session.autoflush = False
    db.drop_all()
    db.create_all()

    from db_setup import ensure_system_roles
    ensure_system_roles()
    R = {r.slug: r for r in Role.query.all()}
    now = datetime.utcnow()

    def person(name, email, phone, pw, acct, roles, **kw):
        u = User(name=name, email=email, phone=phone, account_type=acct, role="admin" if acct == "staff" else "user",
                 **kw)
        u.set_password(pw)
        u.roles = [R[r] for r in roles]
        db.session.add(u)
        return u

    # staff — one per built-in staff role
    admin = person("Infrasetu Admin", "admin@infrasetu.in", "9876500000", "Admin@123", "staff", ["super_admin"])
    person("Meera Nair", "moderator@infrasetu.in", "9876500011", "Staff@123", "staff", ["moderator"],
           state="Karnataka", city="Bengaluru")
    person("Kiran Rao", "catalogue@infrasetu.in", "9876500012", "Staff@123", "staff", ["catalogue_manager"],
           state="Karnataka", city="Bengaluru")
    person("Sana Qureshi", "support@infrasetu.in", "9876500013", "Staff@123", "staff", ["support"],
           state="Maharashtra", city="Pune")

    # sellers (own the sample listings)
    sellers = []
    for name, email, phone, company, btype, state, city, gstin, kyc in [
        ("Ravi Kumar", "ravi@example.com", "9845012345", "Kumar Earthmovers", "Fleet owner", "Karnataka",
         "Bengaluru", "29AAKPK4321R1Z3", "verified"),
        ("Priya Sharma", "priya@example.com", "9822012345", "Sharma Logistics", "Fleet owner", "Maharashtra",
         "Pune", None, "not_submitted"),
        ("Arjun Reddy", "arjun@example.com", "9849012345", "Reddy Infra Rentals", "Rental company", "Telangana",
         "Hyderabad", "36AAFCR5678M1Z9", "verified"),
        ("Fatima Sheikh", "fatima@example.com", "9820098765", "Coastal Cranes", "Dealer", "Maharashtra",
         "Mumbai", "27AAGCC2468K1Z1", "pending"),
    ]:
        sellers.append(person(name, email, phone, "Seller@123", "seller", ["seller"], company=company,
                              business_type=btype, state=state, city=city, gstin=gstin,
                              pan=gstin[2:12] if gstin else None, verification_status=kyc,
                              verified_at=now if kyc == "verified" else None,
                              verified_by_id=1 if kyc == "verified" else None, last_login_at=now))

    # buyers
    person("Suresh Patil", "buyer@example.com", "9900011122", "Buyer@123", "buyer", ["buyer"],
           business_type="Contractor / Builder", company="Patil Constructions", state="Maharashtra", city="Nashik")
    person("Meena Iyer", "meena@example.com", "9900011133", "Buyer@123", "buyer", ["buyer"],
           business_type="Individual", state="Tamil Nadu", city="Chennai")

    # partners (two verified, one waiting for KYC review, one rejected)
    for name, email, phone, company, ptype, gstin, kyc, states, desc, site, note in [
        ("Anand Kulkarni", "finance@example.com", "9811122233", "Sahyadri Equipment Finance", "Financier / NBFC",
         "27AAJCS1357P1Z2", "verified", "Maharashtra, Karnataka, Goa",
         "Loans for new and used tippers, excavators and cranes — up to 85% of value, decision in 48 hours.",
         "https://example.com/sahyadri", None),
        ("Harpreet Gill", "haulage@example.com", "9811122244", "Deccan Heavy Haul Logistics", "Logistics / Transport",
         "36AAKCD9753H1Z6", "verified", "All India",
         "Low-bed and hydraulic-axle trailers to move excavators, dozers and cranes across India, with permits.",
         None, None),
        ("Nikhil Joshi", "inspect@example.com", "9811122255", "Ironclad Inspections & Valuation",
         "Inspection & Valuation", "29AAHCI2468J1Z4", "pending", "Karnataka, Tamil Nadu, Kerala",
         "Independent 150-point inspection and bank-accepted valuation reports for used heavy equipment.",
         None, None),
        ("Lakshmi Menon", "spares@example.com", "9811122266", "Malabar Machine Spares", "Service & Spares",
         "32AAMCM8642L1Z7", "rejected", "Kerala",
         "Genuine and OEM-equivalent spares, on-site repair for backhoe loaders and excavators.",
         None, "GSTIN does not match the registered company name — please upload a corrected certificate."),
    ]:
        u = person(name, email, phone, "Partner@123", "partner", ["partner"], company=company, gstin=gstin,
                   pan=gstin[2:12], verification_status=kyc, verification_note=note,
                   verified_at=now if kyc == "verified" else None, state="Maharashtra", city="Pune")
        u.partner_profile = PartnerProfile(partner_type=ptype, service_states=states, description=desc,
                                           website=site)
    db.session.flush()

    by_name = {}
    for i, (name, group, unit, sell, rent, children, attrs) in enumerate(CATEGORIES):
        c = Category(name=name, slug=slugify(name), group=group, usage_unit=unit, allow_sell=sell,
                     allow_rent=rent, sort_order=i * 10, description=f"{name} for sale and rent.")
        for j, (label, ftype, opts, u, req, srch) in enumerate(attrs):
            c.attributes.append(CategoryAttribute(label=label, field_type=ftype, options=opts or None, unit=u or None,
                                                  is_required=req, is_searchable=srch, sort_order=(j + 1) * 10))
        db.session.add(c)
        by_name[name] = c
        for k, ch in enumerate(children):
            cc = Category(name=ch, slug=slugify(ch), group=group, usage_unit=unit, allow_sell=sell,
                          allow_rent=rent, sort_order=k * 10, parent=c)
            db.session.add(cc)
            by_name[ch] = cc
    db.session.flush()

    items = []
    for cat, mfr, model, variant, hp, wt, specs in CATALOGUE:
        c = by_name[cat]
        it = Catalogue(category=c, manufacturer=mfr, model_name=model, variant=variant, engine_power_hp=hp,
                       specifications=specs)
        if c.group == CV:
            it.gvw_kg = wt
        else:
            it.operating_weight_kg = wt
        db.session.add(it)
        items.append(it)
    db.session.flush()

    today = date.today()
    statuses = ["approved"] * 8 + ["pending", "pending", "rejected", "sold"]
    products = []
    for n in range(54):
        it = items[n % len(items)]
        cat = it.category
        ltype = "rent" if (cat.group == HE and n % 3 != 0) or (cat.group == CV and n % 4 == 0) else "sell"
        state, city, pin = random.choice(CITIES)
        year = random.randint(2012, today.year)
        new = year == today.year and n % 2 == 0
        seller = random.choice(sellers)
        usage = 0 if new else (random.randint(1500, 12000) if cat.usage_unit == "hours"
                               else random.randint(20000, 650000))
        status = random.choice(statuses)
        if status == "sold" and ltype == "rent":
            status = "rented"
        p = Product(
            user=seller, category=cat, catalogue=it, listing_type=ltype,
            title=f"{year} {it.manufacturer} {it.model_name}{' ' + it.variant if it.variant else ''}"
                  f" — {'brand new' if new else random.choice(['well maintained', 'single owner', 'ready to work', 'excellent condition', 'fleet maintained'])}",
            manufacture_year=year, condition="New" if new else random.choice(["Used", "Used", "Refurbished"]),
            usage_reading=usage, fuel_type="Diesel",
            ownership=None if new else random.choice(["1st Owner", "1st Owner", "2nd Owner"]),
            registration_no=(f"{RTO.get(state, 'KA')}{random.randint(1, 60):02d}{random.choice('ABCDEFGH')}"
                             f"{random.choice('ABCDEFGH')}{random.randint(1000, 9999)}") if cat.group == CV and not new else None,
            insurance_valid_till=today + timedelta(days=random.randint(30, 360)),
            state=state, city=city, pincode=pin,
            description=(f"{it.manufacturer} {it.model_name} available in {city}. Regularly serviced at authorised "
                         f"dealer with full service records. Tyres at {random.randint(50, 90)}%, all documents clear. "
                         f"Inspection welcome at our yard. Call for more photos and videos."),
            contact_name=seller.name, contact_phone=seller.phone, contact_email=seller.email,
            status=status, is_featured=n % 9 == 0, views=random.randint(5, 400),
            created_at=datetime.utcnow() - timedelta(days=random.randint(0, 60), hours=random.randint(0, 23)),
        )
        if status == "rejected":
            p.admin_note = "Please upload clear photos of the vehicle and odometer."
        if ltype == "sell":
            base = (it.engine_power_hp or 100) * random.randint(9000, 16000)
            age_factor = max(0.35, 1 - (today.year - year) * 0.07)
            p.price = Decimal(int(base * age_factor / 10000) * 10000)
            p.price_negotiable = n % 3 != 0
        else:
            if cat.group == HE:
                p.rent_period = random.choice(["Hour", "Day", "Month"])
                rate = {"Hour": random.choice([900, 1200, 1500, 2200]), "Day": random.choice([8000, 12000, 18000]),
                        "Month": random.choice([180000, 240000, 320000])}[p.rent_period]
            else:
                p.rent_period = random.choice(["Day", "Month"])
                rate = {"Day": random.choice([4500, 6000, 7500]), "Month": random.choice([95000, 130000, 160000])}[p.rent_period]
            p.rent_rate = Decimal(rate)
            p.min_rent_duration = {"Hour": 8, "Day": random.choice([1, 3, 7]), "Month": 1}[p.rent_period]
            p.operator_included = cat.group == HE and n % 2 == 0
            p.fuel_included = n % 5 == 0
            p.available_from = today + timedelta(days=random.randint(0, 20))
        for a in cat.all_attributes():
            gen = ATTR_VALUES.get(a.label)
            if gen:
                p.attribute_values.append(ProductAttributeValue(attribute=a, value=gen(cat.name)))
        db.session.add(p)
        products.append(p)
    db.session.flush()
    for p in products:
        p.ref_code = generate_ref_code(p)

    live = [p for p in products if p.status == "approved"]
    for i, p in enumerate(live[:10]):
        e = Enquiry(product=p, enquiry_type="buy" if p.listing_type == "sell" else "rent",
                    name=random.choice(["Suresh Patil", "Meena Iyer", "Vikram Singh", "Anil Gowda"]),
                    phone=f"98{random.randint(10000000, 99999999)}", email=f"buyer{i}@example.com",
                    city=random.choice(["Hosur", "Tumakuru", "Nashik", "Vijayawada"]),
                    message="Interested. Please share service records and best price. Can inspect this week.",
                    status=random.choice(["new", "new", "contacted"]))
        if e.enquiry_type == "buy":
            e.offer_price = (p.price * Decimal("0.9")).quantize(Decimal("1"))
        else:
            e.rent_from = today + timedelta(days=5)
            e.rent_to = today + timedelta(days=35)
            e.work_site = "NH-48 widening project, Nelamangala"
        db.session.add(e)

    db.session.add(Requirement(intent="rent", category=by_name["Excavators"], manufacturer="Komatsu",
                               budget_max=Decimal(260000), state="Karnataka", city="Hassan", quantity=2,
                               needed_by=today + timedelta(days=14), name="Deepak Rao", phone="9900112233",
                               email="deepak@example.com",
                               details="Need two 20-ton class excavators with operator for 6 months, canal excavation work."))
    db.session.commit()
    db.session.autoflush = True
