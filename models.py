from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

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
    transactions = db.relationship('StockTransaction', backref='facility', lazy=True)

    def __repr__(self):
        return f"<Facility {self.id} {self.name}>"

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
    beginning_balance = db.Column(db.Integer, default=0)  # NEW: initial stock at facility

    def __repr__(self):
        return f"<FacilityProduct f:{self.facility_id} p:{self.product_id} min:{self.min_stock} beg:{self.beginning_balance}>"

class StockTransaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    facility_id = db.Column(db.Integer, db.ForeignKey('facility.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    date = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    quantity = db.Column(db.Integer, nullable=False)
    transaction_type = db.Column(db.String(20), nullable=False)  
    # Allowed types: Opening, Received, Issued, Adjusted, Lost, Damaged, Expired
    reference_number = db.Column(db.String(50))
    batch_number = db.Column(db.String(50), nullable=True)
    expiry_date = db.Column(db.Date, nullable=True)
    entered_by = db.Column(db.String(120), nullable=True)  # audit field
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Tx {self.id} f:{self.facility_id} p:{self.product_id} q:{self.quantity} {self.transaction_type}>"
