from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
from flask_login import LoginManager, login_required, current_user
from datetime import datetime, date
from sqlalchemy import text, func, case, and_, or_
import os

from models import db, User, Cluster, LGA, Facility, Product, FacilityProduct, StockTransaction

from admin.routes import admin_bp
from dashboard import dashboard_bp
from auth import auth_bp

# Create the app first
app = Flask(__name__, instance_relative_config=True)

# login manager
from flask_login import LoginManager
login_manager = LoginManager(app)
login_manager.login_view = 'auth.login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

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
app.register_blueprint(auth_bp, url_prefix='/auth')

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
    cluster_id = request.args.get('cluster')
    lga_id = request.args.get('lga')
    facility_id = request.args.get('facility')

    # <<< CHANGED: only override if nothing selected >>>
    if current_user.role != 'super':
        if current_user.role == 'cluster' and not cluster_id:
            cluster_id = current_user.cluster_id
        elif current_user.role == 'lga':
            lga_id = current_user.lga_id
            cluster_id = current_user.lga.cluster_id
        elif current_user.role == 'facility':
            facility_id = current_user.facility_id
            lga_id = current_user.facility.lga_id
            cluster_id = current_user.facility.lga.cluster_id

    base_sql = """
        SELECT c.name AS cluster,
               l.id   AS lga_id,
               l.name AS lga,
               f.id   AS facility_id,
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
        JOIN cluster c ON l.cluster_id = c.id
        JOIN product p ON st.product_id = p.id
        LEFT JOIN facility_product fp ON fp.facility_id = f.id AND fp.product_id = p.id
        WHERE 1=1
    """

    # build filter clauses
    filters = []
    params = {}
    if cluster_id:
        filters.append("AND l.cluster_id = :cluster_id")
        params["cluster_id"] = cluster_id
    if lga_id:
        filters.append("AND f.lga_id = :lga_id")
        params["lga_id"] = lga_id
    if facility_id:
        filters.append("AND f.id = :facility_id")
        params["facility_id"] = facility_id

    sql = text(base_sql + " ".join(filters) + """
        GROUP BY c.name, l.id, l.name, f.id, f.name, p.name, fp.min_stock
        HAVING stock_at_hand IS NOT NULL AND stock_at_hand != 0
        ORDER BY c.name, l.name, f.name, p.name
    """)

    # run query
    result = db.session.execute(sql, params).mappings().all()

    results = [{
        'cluster': r.get('cluster','N/A'),
        'lga': r.get('lga','N/A'),
        'facility': r.get('facility','N/A'),
        'product': r.get('product','N/A'),
        'min_stock': int(r.get('min_stock') or 0),
        'stock_at_hand': int(r.get('stock_at_hand') or 0)
    } for r in result]

    # --- 4. Dropdown lists restricted by role ---
    # <<< CHANGED: always use selected lga_id for facilities >>>
    if current_user.role == 'super':
        clusters = Cluster.query.order_by(Cluster.name).all()
        lgas = LGA.query.filter_by(cluster_id=cluster_id).order_by(LGA.name).all() if cluster_id else []
        facilities = Facility.query.filter_by(lga_id=lga_id).order_by(Facility.name).all() if lga_id else []

    elif current_user.role == 'cluster':
        clusters = Cluster.query.filter_by(id=current_user.cluster_id).all()
        lgas = LGA.query.filter_by(cluster_id=current_user.cluster_id).order_by(LGA.name).all()
        facilities = Facility.query.filter_by(lga_id=lga_id).order_by(Facility.name).all() if lga_id else []

    elif current_user.role == 'lga':
        clusters = Cluster.query.filter_by(id=cluster_id).all()
        lgas = LGA.query.filter_by(id=current_user.lga_id).all()
        facilities = Facility.query.filter_by(lga_id=lga_id).order_by(Facility.name).all() if lga_id else []

    elif current_user.role == 'facility':
        clusters = Cluster.query.filter_by(id=cluster_id).all()
        lgas = LGA.query.filter_by(id=lga_id).all()
        facilities = Facility.query.filter_by(id=current_user.facility_id).all()


    return render_template(
        'facility_soh.html',
        results=results,
        clusters=clusters,
        lgas=lgas,
        facilities=facilities,
        selected_cluster=cluster_id,
        selected_lga=lga_id,
        selected_facility=facility_id
    )



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
            #entered_by=entered_by
            entered_by=current_user.username
        )
        db.session.add(tx)
        db.session.commit()
        flash('Transaction recorded', 'success')
        return redirect(url_for('transactions'))

    return render_template('add_transaction.html', clusters=clusters, products=products)

@app.route('/transactions')
def transactions():
    # get filter parameters from query string
    cluster_id = request.args.get('cluster')
    lga_id = request.args.get('lga')
    facility_id = request.args.get('facility')

    # base query with all joins
    query = db.session.query(
        StockTransaction.id,
        StockTransaction.date,
        StockTransaction.quantity,
        StockTransaction.transaction_type,
        StockTransaction.reference_number,
        StockTransaction.batch_number,
        StockTransaction.expiry_date,
        StockTransaction.entered_by,
        Facility.id.label('facility_id'),
        Facility.name.label('facility'),
        LGA.id.label('lga_id'),
        LGA.name.label('lga'),
        Cluster.id.label('cluster_id'),
        Cluster.name.label('cluster'),
        Product.name.label('product')
    ).join(Facility, StockTransaction.facility_id == Facility.id) \
     .join(LGA, Facility.lga_id == LGA.id) \
     .join(Cluster, LGA.cluster_id == Cluster.id) \
     .join(Product, StockTransaction.product_id == Product.id)

    # apply filters if present
    if cluster_id:
        query = query.filter(LGA.cluster_id == cluster_id)
    if lga_id:
        query = query.filter(Facility.lga_id == lga_id)
    if facility_id:
        query = query.filter(StockTransaction.facility_id == facility_id)

    transactions = query.order_by(StockTransaction.date.desc()).all()

    # populate dropdowns for filters
    clusters = Cluster.query.order_by(Cluster.name).all()
    lgas = LGA.query.filter_by(cluster_id=cluster_id).order_by(LGA.name).all() if cluster_id else []
    facilities = Facility.query.filter_by(lga_id=lga_id).order_by(Facility.name).all() if lga_id else []

    return render_template(
        'transactions.html',
        transactions=transactions,
        clusters=clusters,
        lgas=lgas,
        facilities=facilities,
        selected_cluster=cluster_id,
        selected_lga=lga_id,
        selected_facility=facility_id
    )
    
@app.route('/transaction/<int:id>/edit', methods=['GET', 'POST'])
def edit_transaction(id):
    tx = StockTransaction.query.get_or_404(id)
    clusters = Cluster.query.order_by(Cluster.name).all()
    products = Product.query.order_by(Product.name).all()

    if request.method == 'POST':
        tx.facility_id = request.form.get('facility')
        tx.product_id = request.form.get('product')
        tx.date = datetime.strptime(request.form.get('date'), '%Y-%m-%d').date()
        tx.quantity = int(request.form.get('quantity'))
        tx.transaction_type = request.form.get('transaction_type')
        tx.reference_number = request.form.get('reference_number')
        tx.batch_number = request.form.get('batch_number')
        expiry_str = request.form.get('expiry_date')
        tx.expiry_date = datetime.strptime(expiry_str, '%Y-%m-%d').date() if expiry_str else None
        #tx.entered_by = request.form.get('entered_by')
        tx.entered_by=current_user.username
        db.session.commit()
        flash('Transaction updated', 'success')
        return redirect(url_for('transactions'))

    return render_template('edit_transaction.html', tx=tx, clusters=clusters, products=products)

@app.route('/transaction/<int:id>/delete', methods=['POST'])
def delete_transaction(id):
    tx = StockTransaction.query.get_or_404(id)
    db.session.delete(tx)
    db.session.commit()
    flash('Transaction deleted', 'success')
    return redirect(url_for('transactions'))


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