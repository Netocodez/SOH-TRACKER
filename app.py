from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
from datetime import datetime, date
from sqlalchemy import text, func, case, and_, or_
import os

from models import db, Cluster, LGA, Facility, Product, FacilityProduct, StockTransaction

from admin.routes import admin_bp
from dashboard import dashboard_bp

# Create the app first
app = Flask(__name__, instance_relative_config=True)

# Ensure the instance folder exists
os.makedirs(app.instance_path, exist_ok=True)

# Now build the DB path inside the instance folder
DB_PATH = os.path.join(app.instance_path, 'stock.db')

# Configure SQLAlchemy
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'dev-secret'  # change for production

app.register_blueprint(admin_bp)  # register admin routes
app.register_blueprint(dashboard_bp, url_prefix='/dashboard')

db.init_app(app)

with app.app_context():
    db.create_all()

# -------------------
# Dashboard
# -------------------
@app.route('/')
def index():
    return redirect(url_for('dashboard.dashboard_home'))

@app.route('/facility_soh')
def facility_soh():
    # Only include facilities that have stock transactions
    sql = text("""
        SELECT l.name AS lga,
               f.name AS facility,
               p.name AS product,
               COALESCE(fp.min_stock, 0) AS min_stock,
               SUM(
                   CASE 
                       WHEN st.transaction_type IN ('Received','Opening') THEN st.quantity
                       WHEN st.transaction_type IN ('Issued','Lost','Damaged','Expired') THEN -st.quantity
                       WHEN st.transaction_type='Adjusted' THEN st.quantity
                       ELSE 0
                   END
               ) AS stock_at_hand
        FROM stock_transaction st
        JOIN facility f ON st.facility_id = f.id
        JOIN lga l ON f.lga_id = l.id
        JOIN product p ON st.product_id = p.id
        LEFT JOIN facility_product fp ON fp.facility_id = f.id AND fp.product_id = p.id
        GROUP BY l.name, f.name, p.name, fp.min_stock
        HAVING stock_at_hand IS NOT NULL AND stock_at_hand != 0
        ORDER BY l.name, f.name, p.name
    """)

    try:
        result = db.session.execute(sql).mappings().all()
        
        # Safely build the results list for template
        results = []
        for r in result:
            results.append({
                'lga': r.get('lga', 'N/A'),
                'facility': r.get('facility', 'N/A'),
                'product': r.get('product', 'N/A'),
                'min_stock': int(r.get('min_stock') or 0),
                'stock_at_hand': int(r.get('stock_at_hand') or 0)
            })

        return render_template('facility_soh.html', results=results)
    
    except Exception as e:
        import traceback
        return f"<h3>Error loading data:</h3><pre>{traceback.format_exc()}</pre>"


# -------------------
# Add transaction (Cluster -> LGA -> Facility cascading)
# -------------------
@app.route('/add_transaction', methods=['GET', 'POST'])
def add_transaction():
    clusters = Cluster.query.order_by(Cluster.name).all()
    products = Product.query.order_by(Product.name).all()

    if request.method == 'POST':
        facility_id = request.form.get('facility')
        product_id = request.form.get('product')
        date_str = request.form.get('date')
        quantity = request.form.get('quantity')
        transaction_type = request.form.get('transaction_type')
        reference_number = request.form.get('reference_number')
        batch_number = request.form.get('batch_number')
        expiry_date_str = request.form.get('expiry_date')
        entered_by = request.form.get('entered_by')

        errors = []

        # Validate required fields
        if not facility_id or not product_id:
            errors.append('Facility and Product are required.')

        # Validate date
        try:
            date_val = datetime.strptime(date_str, '%Y-%m-%d').date()
            if date_val > date.today():
                errors.append('Date cannot be in the future.')
        except Exception:
            errors.append('Invalid date format.')

        # Validate quantity
        try:
            quantity_val = int(quantity)
            if quantity_val <= 0:
                errors.append('Quantity must be greater than zero.')
        except Exception:
            errors.append('Quantity must be a valid integer.')

        # Validate expiry date
        expiry_date_val = None
        if expiry_date_str:
            try:
                expiry_date_val = datetime.strptime(expiry_date_str, '%Y-%m-%d').date()
            except Exception:
                errors.append('Invalid expiry date format.')

        # Check current stock for outflows
        current_stock = db.session.query(
            (
                func.coalesce(FacilityProduct.beginning_balance, 0) +
                func.coalesce(
                    func.sum(
                        case(
                            (StockTransaction.transaction_type.in_(['Received', 'Opening']), StockTransaction.quantity),
                            (StockTransaction.transaction_type.in_(['Issued','Lost','Damaged','Expired']), -StockTransaction.quantity),
                            (StockTransaction.transaction_type=='Adjusted', StockTransaction.quantity),
                            else_=0
                        )
                    ), 0
                )
            ).label('stock')
        ).select_from(StockTransaction).outerjoin(
            FacilityProduct,
            and_(
                FacilityProduct.product_id == StockTransaction.product_id,
                FacilityProduct.facility_id == StockTransaction.facility_id
            )
        ).filter(
            StockTransaction.product_id == product_id,
            StockTransaction.facility_id == facility_id
        ).scalar() or 0

        # Validate outflow does not exceed stock
        if transaction_type in ('Issued','Lost','Damaged','Expired') and quantity_val > current_stock:
            errors.append('Cannot issue more than stock on hand.')

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('add_transaction.html', clusters=clusters, products=products)

        # Record transaction
        tx = StockTransaction(
            facility_id=int(facility_id),
            product_id=int(product_id),
            date=date_val,
            quantity=quantity_val,
            transaction_type=transaction_type,
            reference_number=reference_number,
            batch_number=batch_number,
            expiry_date=expiry_date_val,
            entered_by=entered_by
        )
        db.session.add(tx)
        db.session.commit()
        flash('Transaction recorded', 'success')
        return redirect(url_for('dashboard.dashboard_home'))

    return render_template('add_transaction.html', clusters=clusters, products=products)

# -------------------
# AJAX: get LGAs by cluster and facilities by LGA
# -------------------
@app.route('/get_lgas/<int:cluster_id>')
def get_lgas(cluster_id):
    lgas = LGA.query.filter_by(cluster_id=cluster_id).order_by(LGA.name).all()
    return jsonify([{'id': l.id, 'name': l.name} for l in lgas])

@app.route('/get_facilities/<int:lga_id>')
def get_facilities(lga_id):
    facilities = Facility.query.filter_by(lga_id=lga_id).order_by(Facility.name).all()
    return jsonify([{'id': f.id, 'name': f.name} for f in facilities])

# -------------------
# Reports: consumption and months of stock (MOS)
# -------------------
@app.route('/report')
def report():
    # Average monthly consumption per product
    sql_avg = text("""
    SELECT p.id AS product_id, p.name AS product_name, AVG(monthly_issued) AS avg_monthly_issued
    FROM (
        SELECT p.id AS pid, STRFTIME('%Y-%m', st.date) AS month_key,
               SUM(CASE WHEN st.transaction_type='Issued' THEN st.quantity ELSE 0 END) AS monthly_issued
        FROM stock_transaction st
        JOIN product p ON p.id = st.product_id
        GROUP BY pid, month_key
    ) AS monthly
    JOIN product p ON p.id = monthly.pid
    GROUP BY p.id
    """)
    avg_rows = db.session.execute(sql_avg).mappings().all()
    avg_map = {r['product_id']: r['avg_monthly_issued'] or 0 for r in avg_rows}

    # Current stock at hand per product (all facilities)
    sql_stock = text("""
    SELECT p.id AS product_id, p.name AS product_name,
           COALESCE(SUM(CASE WHEN st.transaction_type IN ('Received','Opening') THEN st.quantity ELSE 0 END),0) -
           COALESCE(SUM(CASE WHEN st.transaction_type IN ('Issued','Lost','Damaged','Expired') THEN st.quantity ELSE 0 END),0) +
           COALESCE(SUM(CASE WHEN st.transaction_type='Adjusted' THEN st.quantity ELSE 0 END),0) AS stock_at_hand,
           COALESCE(SUM(fp.min_stock),0) AS min_stock
    FROM product p
    LEFT JOIN stock_transaction st ON st.product_id = p.id
    LEFT JOIN facility_product fp ON fp.product_id = p.id
    GROUP BY p.id
    """)
    stock_rows = db.session.execute(sql_stock).mappings().all()

    report_rows = []
    for r in stock_rows:
        avg = avg_map.get(r['product_id'], 0)
        stock = r['stock_at_hand'] or 0
        mos = round(stock / avg, 2) if avg > 0 else None
        status = "Below Min" if stock < r['min_stock'] else "OK"
        report_rows.append({
            'product_id': r['product_id'],
            'product': r['product_name'],
            'avg_monthly_issued': avg,
            'stock_at_hand': stock,
            'mos': mos,
            'min_stock': r['min_stock'],
            'status': status
        })

    return render_template('report.html', rows=report_rows)

# -------------------
# Seed helper route (DEV ONLY) - run once if you want to auto-seed
# -------------------
@app.route('/_seed_dev', methods=['POST'])
def seed_dev():
    # WARNING: this is for development/demo only. It will not drop existing DB.
    # Only insert data if not present.
    from datetime import date, timedelta

    # simple sample data
    if not Cluster.query.first():
        c1 = Cluster(name='Cluster A')
        c2 = Cluster(name='Cluster B')
        db.session.add_all([c1, c2])
        db.session.commit()

        l1 = LGA(name='LGA One', cluster_id=c1.id)
        l2 = LGA(name='LGA Two', cluster_id=c1.id)
        l3 = LGA(name='LGA Three', cluster_id=c2.id)
        db.session.add_all([l1, l2, l3])
        db.session.commit()

        f1 = Facility(name='Facility Alpha', lga_id=l1.id)
        f2 = Facility(name='Facility Beta', lga_id=l2.id)
        db.session.add_all([f1, f2])
        db.session.commit()

        p1 = Product(name='ARV', unit='Box')
        p2 = Product(name='Test Kit', unit='Pack')
        db.session.add_all([p1, p2])
        db.session.commit()

        fp1 = FacilityProduct(facility_id=f1.id, product_id=p1.id, min_stock=10)
        fp2 = FacilityProduct(facility_id=f2.id, product_id=p2.id, min_stock=5)
        db.session.add_all([fp1, fp2])
        db.session.commit()

        tx1 = StockTransaction(facility_id=f1.id, product_id=p1.id, date=date.today(), quantity=50, transaction_type='Received', reference_number='seed1')
        tx2 = StockTransaction(facility_id=f2.id, product_id=p2.id, date=date.today(), quantity=8, transaction_type='Received', reference_number='seed2')
        tx3 = StockTransaction(facility_id=f1.id, product_id=p1.id, date=date.today(), quantity=5, transaction_type='Issued', reference_number='seed3')
        db.session.add_all([tx1, tx2, tx3])
        db.session.commit()

    return ('Seeded (if empty)', 200)

if __name__ == '__main__':
    app.run(debug=True)