from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

db = SQLAlchemy()


# -----------------------
# USER MODEL
# -----------------------
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='facility')

    cluster_id = db.Column(db.Integer, db.ForeignKey('cluster.id'), nullable=True)
    lga_id = db.Column(db.Integer, db.ForeignKey('lga.id'), nullable=True)
    facility_id = db.Column(db.Integer, db.ForeignKey('facility.id'), nullable=True)

    active = db.Column(db.Boolean, default=True)

    # relationships
    cluster = db.relationship('Cluster', backref='users')
    lga = db.relationship('LGA', backref='users')
    facility = db.relationship('Facility', foreign_keys=[facility_id], backref='users')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f"<User {self.username}>"


# -----------------------
# CLUSTER / LGA / FACILITY MODELS
# -----------------------
class Cluster(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    lgas = db.relationship('LGA', backref='cluster', lazy=True)

    def __repr__(self):
        return f"<Cluster {self.id} {self.name}>"


class LGA(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    cluster_id = db.Column(db.Integer, db.ForeignKey('cluster.id'), nullable=False)
    facilities = db.relationship('Facility', backref='lga', lazy=True)

    def __repr__(self):
        return f"<LGA {self.id} {self.name}>"


class Facility(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    lga_id = db.Column(db.Integer, db.ForeignKey('lga.id'), nullable=False)

    facility_products = db.relationship('FacilityProduct', backref='facility', lazy=True)

    # No direct "transactions" relationship — handled via StockTransaction explicit FKs
    # Use facility.transactions_out and facility.transactions_in from backrefs

    def __repr__(self):
        return f"<Facility {self.id} {self.name}>"


# -----------------------
# PRODUCT / FACILITYPRODUCT
# -----------------------
class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    unit = db.Column(db.String(30))

    facility_products = db.relationship('FacilityProduct', backref='product', lazy=True)
    transactions = db.relationship('StockTransaction', backref='product', lazy=True)

    def __repr__(self):
        return f"<Product {self.id} {self.name}>"


class FacilityProduct(db.Model):
    __tablename__ = 'facility_product'
    id = db.Column(db.Integer, primary_key=True)
    facility_id = db.Column(db.Integer, db.ForeignKey('facility.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)

    min_stock = db.Column(db.Integer, default=0)
    beginning_balance = db.Column(db.Integer, default=0)  # initial stock at facility

    def __repr__(self):
        return f"<FacilityProduct f:{self.facility_id} p:{self.product_id} min:{self.min_stock} beg:{self.beginning_balance}>"


# -----------------------
# STOCK TRANSACTIONS
# -----------------------
class StockTransaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    facility_id = db.Column(db.Integer, db.ForeignKey('facility.id'), nullable=False)  # source facility
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)

    date = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    quantity = db.Column(db.Integer, nullable=False)
    transaction_type = db.Column(db.String(20), nullable=False)
    # Allowed types: Opening, Received, Issued, Adjusted, Lost, Damaged, Expired, Transfer

    reference_number = db.Column(db.String(50))
    batch_number = db.Column(db.String(50), nullable=True)
    expiry_date = db.Column(db.Date, nullable=True)

    entered_by = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # For transfers
    is_transfer_destination = db.Column(db.Boolean, default=False)
    destination_facility_id = db.Column(db.Integer, db.ForeignKey('facility.id'), nullable=True)
    comments = db.Column(db.Text)
    
    # ✅ New field to store the source facility for Transfer-In
    source_facility_id = db.Column(db.Integer, db.ForeignKey('facility.id'), nullable=True)

    # Relationships
    facility = db.relationship(   # ✅ source facility
        'Facility',
        foreign_keys=[facility_id],
        backref='transactions_out'
    )
    destination_facility = db.relationship(
        'Facility',
        foreign_keys=[destination_facility_id],
        backref='transactions_in'
    )
    
    source_facility = db.relationship(  # ✅ new relationship for Transfer-In source
        'Facility',
        foreign_keys=[source_facility_id],
        backref='transactions_source'
    )

    def __repr__(self):
        return (
            f"<Tx {self.id} src:{self.source_facility_id or self.facility_id} "
            f"dest:{self.destination_facility_id} "
            f"p:{self.product_id} q:{self.quantity} {self.transaction_type}>"
        )