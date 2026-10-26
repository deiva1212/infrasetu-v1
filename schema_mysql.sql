-- Infrasetu schema (mysql). Generated from models.py.
-- You can also just start the app: it creates and upgrades tables automatically.

CREATE TABLE categories (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	name VARCHAR(120) NOT NULL, 
	slug VARCHAR(140) NOT NULL, 
	`group` VARCHAR(40) NOT NULL, 
	parent_id INTEGER, 
	description TEXT, 
	usage_unit VARCHAR(10) NOT NULL, 
	allow_sell BOOL NOT NULL, 
	allow_rent BOOL NOT NULL, 
	sort_order INTEGER NOT NULL, 
	is_active BOOL NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(parent_id) REFERENCES categories (id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX ix_categories_slug ON categories (slug);

CREATE TABLE roles (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	slug VARCHAR(60) NOT NULL, 
	name VARCHAR(80) NOT NULL, 
	description VARCHAR(255), 
	is_staff BOOL NOT NULL, 
	is_system BOOL NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (name)
);

CREATE UNIQUE INDEX ix_roles_slug ON roles (slug);

CREATE TABLE users (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	name VARCHAR(120) NOT NULL, 
	email VARCHAR(160) NOT NULL, 
	phone VARCHAR(20) NOT NULL, 
	company VARCHAR(160), 
	password_hash VARCHAR(255) NOT NULL, 
	`role` VARCHAR(20) NOT NULL, 
	is_active BOOL NOT NULL, 
	account_type VARCHAR(20) NOT NULL, 
	business_type VARCHAR(60), 
	state VARCHAR(60), 
	city VARCHAR(80), 
	gstin VARCHAR(15), 
	pan VARCHAR(10), 
	verification_status VARCHAR(20) NOT NULL, 
	verification_note VARCHAR(255), 
	verified_at DATETIME, 
	verified_by_id INTEGER, 
	last_login_at DATETIME, 
	failed_logins INTEGER NOT NULL, 
	locked_until DATETIME, 
	password_changed_at DATETIME, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_users_email ON users (email);
CREATE INDEX ix_users_account_type ON users (account_type);

CREATE TABLE audit_logs (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	actor_id INTEGER, 
	action VARCHAR(60) NOT NULL, 
	target_type VARCHAR(30), 
	target_id INTEGER, 
	details TEXT, 
	ip VARCHAR(45), 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(actor_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_audit_logs_target_id ON audit_logs (target_id);
CREATE INDEX ix_audit_logs_created_at ON audit_logs (created_at);
CREATE INDEX ix_audit_logs_actor_id ON audit_logs (actor_id);
CREATE INDEX ix_audit_logs_action ON audit_logs (action);

CREATE TABLE catalogue (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	category_id INTEGER NOT NULL, 
	manufacturer VARCHAR(120) NOT NULL, 
	model_name VARCHAR(120) NOT NULL, 
	variant VARCHAR(120) NOT NULL, 
	engine_power_hp INTEGER, 
	operating_weight_kg INTEGER, 
	gvw_kg INTEGER, 
	specifications TEXT, 
	description TEXT, 
	is_active BOOL NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_catalogue_model UNIQUE (category_id, manufacturer, model_name, variant), 
	FOREIGN KEY(category_id) REFERENCES categories (id)
);

CREATE INDEX ix_catalogue_category_id ON catalogue (category_id);
CREATE INDEX ix_catalogue_manufacturer ON catalogue (manufacturer);

CREATE TABLE category_attributes (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	category_id INTEGER NOT NULL, 
	label VARCHAR(120) NOT NULL, 
	field_type VARCHAR(20) NOT NULL, 
	options TEXT, 
	unit VARCHAR(30), 
	is_required BOOL NOT NULL, 
	is_searchable BOOL NOT NULL, 
	sort_order INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(category_id) REFERENCES categories (id) ON DELETE CASCADE
);


CREATE TABLE partner_profiles (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	user_id INTEGER NOT NULL, 
	partner_type VARCHAR(60) NOT NULL, 
	website VARCHAR(200), 
	service_states TEXT NOT NULL, 
	description TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (user_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_partner_profiles_partner_type ON partner_profiles (partner_type);

CREATE TABLE requirements (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	user_id INTEGER, 
	intent VARCHAR(10) NOT NULL, 
	category_id INTEGER NOT NULL, 
	manufacturer VARCHAR(120), 
	budget_max NUMERIC(14, 2), 
	state VARCHAR(60) NOT NULL, 
	city VARCHAR(80) NOT NULL, 
	quantity INTEGER NOT NULL, 
	needed_by DATE, 
	name VARCHAR(120) NOT NULL, 
	phone VARCHAR(20) NOT NULL, 
	email VARCHAR(160) NOT NULL, 
	details TEXT NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(category_id) REFERENCES categories (id)
);


CREATE TABLE role_permissions (
	role_id INTEGER NOT NULL, 
	permission VARCHAR(60) NOT NULL, 
	PRIMARY KEY (role_id, permission), 
	FOREIGN KEY(role_id) REFERENCES roles (id) ON DELETE CASCADE
);


CREATE TABLE user_roles (
	user_id INTEGER NOT NULL, 
	role_id INTEGER NOT NULL, 
	PRIMARY KEY (user_id, role_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(role_id) REFERENCES roles (id) ON DELETE CASCADE
);


CREATE TABLE products (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	ref_code VARCHAR(20), 
	user_id INTEGER NOT NULL, 
	category_id INTEGER NOT NULL, 
	catalogue_id INTEGER NOT NULL, 
	listing_type VARCHAR(10) NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	manufacture_year INTEGER NOT NULL, 
	`condition` VARCHAR(20) NOT NULL, 
	usage_reading INTEGER NOT NULL, 
	fuel_type VARCHAR(20) NOT NULL, 
	registration_no VARCHAR(30), 
	ownership VARCHAR(30), 
	insurance_valid_till DATE, 
	price NUMERIC(14, 2), 
	price_negotiable BOOL NOT NULL, 
	rent_rate NUMERIC(12, 2), 
	rent_period VARCHAR(10), 
	min_rent_duration INTEGER, 
	operator_included BOOL NOT NULL, 
	fuel_included BOOL NOT NULL, 
	available_from DATE, 
	state VARCHAR(60) NOT NULL, 
	city VARCHAR(80) NOT NULL, 
	pincode VARCHAR(10) NOT NULL, 
	description TEXT NOT NULL, 
	contact_name VARCHAR(120) NOT NULL, 
	contact_phone VARCHAR(20) NOT NULL, 
	contact_email VARCHAR(160), 
	status VARCHAR(20) NOT NULL, 
	admin_note VARCHAR(255), 
	is_featured BOOL NOT NULL, 
	views INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(category_id) REFERENCES categories (id), 
	FOREIGN KEY(catalogue_id) REFERENCES catalogue (id)
);

CREATE UNIQUE INDEX ix_products_ref_code ON products (ref_code);
CREATE INDEX ix_products_catalogue_id ON products (catalogue_id);
CREATE INDEX ix_products_status ON products (status);
CREATE INDEX ix_products_city ON products (city);
CREATE INDEX ix_products_user_id ON products (user_id);
CREATE INDEX ix_products_manufacture_year ON products (manufacture_year);
CREATE INDEX ix_products_category_id ON products (category_id);
CREATE INDEX ix_products_listing_type ON products (listing_type);
CREATE INDEX ix_products_state ON products (state);

CREATE TABLE enquiries (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	product_id INTEGER NOT NULL, 
	user_id INTEGER, 
	enquiry_type VARCHAR(10) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	phone VARCHAR(20) NOT NULL, 
	email VARCHAR(160) NOT NULL, 
	city VARCHAR(80) NOT NULL, 
	offer_price NUMERIC(14, 2), 
	rent_from DATE, 
	rent_to DATE, 
	work_site VARCHAR(200), 
	message TEXT NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(product_id) REFERENCES products (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id)
);


CREATE TABLE product_attribute_values (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	product_id INTEGER NOT NULL, 
	attribute_id INTEGER NOT NULL, 
	value VARCHAR(255) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_product_attr UNIQUE (product_id, attribute_id), 
	FOREIGN KEY(product_id) REFERENCES products (id) ON DELETE CASCADE, 
	FOREIGN KEY(attribute_id) REFERENCES category_attributes (id) ON DELETE CASCADE
);

CREATE INDEX ix_product_attribute_values_attribute_id ON product_attribute_values (attribute_id);

CREATE TABLE product_images (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	product_id INTEGER NOT NULL, 
	filename VARCHAR(255) NOT NULL, 
	sort_order INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(product_id) REFERENCES products (id) ON DELETE CASCADE
);

