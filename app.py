from flask import Flask, render_template, request, redirect, url_for, jsonify, flash, Response, g, abort, send_file, stream_with_context
from flask_login import LoginManager, login_required, current_user
from flask_migrate import Migrate
from datetime import datetime, date
from sqlalchemy import text, func, case, and_, or_, and_
from sqlalchemy.orm import aliased
import os, io, csv

from models import db, User, Cluster, LGA, Facility, Product, FacilityProduct, StockTransaction
from auth.scope_utils import restrict_scope, get_dropdowns, get_user_scope_filters
from reporting.routes import reporting_bp
from exports import export_bp
from dhis2api import dhis2api_bp



from admin.routes import admin_bp
from dashboard import dashboard_bp
from auth import auth_bp
from backup import backup_bp

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

#db.init_app(app)
#migrate = Migrate(app, db)

app.register_blueprint(admin_bp)  # register admin routes
app.register_blueprint(dashboard_bp, url_prefix='/dashboard')
app.register_blueprint(auth_bp, url_prefix='/auth')
app.register_blueprint(backup_bp)
app.register_blueprint(reporting_bp, url_prefix='/reporting')
app.register_blueprint(export_bp, url_prefix='/exports')
app.register_blueprint(dhis2api_bp)

db.init_app(app)
migrate = Migrate(app, db)

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
                       WHEN st.transaction_type IN ('Received','Opening','Transfer-In') THEN st.quantity
                       WHEN st.transaction_type IN ('Issued','Lost','Damaged','Expired','Transfer') THEN -st.quantity
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
# --- Add Transaction ---
@app.route('/add_transaction', methods=['GET', 'POST'])
@restrict_scope
def add_transaction():
    # Apply dropdowns restricted to user scope
    clusters, lgas, facilities = get_dropdowns(g.cluster_id, g.lga_id, g.facility_id)
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
        dest_facility_id = request.form.get('destination_facility')
        comments = request.form.get('comments')

        errors = []

        # --- Date Validation ---
        try:
            date_val = datetime.strptime(date_str, '%Y-%m-%d').date()
            if date_val > date.today():
                errors.append('Date cannot be in the future.')
        except Exception:
            errors.append('Invalid date format.')

        # --- Quantity Validation ---
        try:
            quantity_val = int(quantity)
            if quantity_val <= 0:
                errors.append('Quantity must be greater than zero.')
        except Exception:
            errors.append('Quantity must be a valid integer.')

        # --- Expiry Date Validation ---
        expiry_date_val = None
        if expiry_date_str:
            try:
                expiry_date_val = datetime.strptime(expiry_date_str, '%Y-%m-%d').date()
            except Exception:
                errors.append('Invalid expiry date format.')

        # --- Current Stock Check ---
        current_stock = db.session.query(
            (
                func.coalesce(FacilityProduct.beginning_balance, 0) +
                func.coalesce(
                    func.sum(
                        case(
                            (StockTransaction.transaction_type.in_(['Received', 'Opening', 'Transfer-In']), StockTransaction.quantity),
                            (StockTransaction.transaction_type.in_(['Issued', 'Lost', 'Damaged', 'Expired', 'Transfer']), -StockTransaction.quantity),
                            (StockTransaction.transaction_type == 'Adjusted', StockTransaction.quantity),
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

        if transaction_type in ('Issued', 'Lost', 'Damaged', 'Expired', 'Transfer') and quantity_val > current_stock:
            errors.append('Cannot issue/transfer more than stock on hand.')

        # --- Handle Errors ---
        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template(
                'add_transaction.html',
                clusters=clusters,
                lgas=lgas,
                facilities=facilities,
                products=products,
                selected_cluster=g.cluster_id,
                selected_lga=g.lga_id,
                selected_facility=g.facility_id
            )

        # --- Handle Transfers ---
        if transaction_type == "Transfer":
            if not dest_facility_id:
                flash("Destination facility must be selected for transfers.", "danger")
                return render_template(
                    'add_transaction.html',
                    clusters=clusters,
                    lgas=lgas,
                    facilities=facilities,
                    products=products,
                    selected_cluster=g.cluster_id,
                    selected_lga=g.lga_id,
                    selected_facility=g.facility_id
                )

            # Prevent self-transfer
            if int(dest_facility_id) == int(facility_id):
                flash("Cannot transfer to the same facility.", "danger")
                return render_template(
                    'add_transaction.html',
                    clusters=clusters,
                    lgas=lgas,
                    facilities=facilities,
                    products=products,
                    selected_cluster=g.cluster_id,
                    selected_lga=g.lga_id,
                    selected_facility=g.facility_id
                )

            # --- Outflow from Source ---
            tx_out = StockTransaction(
                facility_id=int(facility_id),
                product_id=int(product_id),
                date=date_val,
                quantity=quantity_val,
                transaction_type="Transfer",
                reference_number=reference_number,
                batch_number=batch_number,
                expiry_date=expiry_date_val,
                entered_by=current_user.username,
                destination_facility_id=int(dest_facility_id),
                comments=comments
            )

            # --- Inflow to Destination ---
            tx_in = StockTransaction(
                facility_id=int(dest_facility_id),
                product_id=int(product_id),
                date=date_val,
                quantity=quantity_val,
                transaction_type="Transfer-In",
                reference_number=reference_number,
                batch_number=batch_number,
                expiry_date=expiry_date_val,
                entered_by=current_user.username,
                comments=comments,
                source_facility_id=int(facility_id),  # ✅ new link
                destination_facility_id=int(dest_facility_id)  # ✅ keep symmetrical
            )

            db.session.add_all([tx_out, tx_in])
            db.session.commit()
            flash("Transfer recorded successfully", "success")

        else:
            # --- Normal single-entry transaction ---
            tx = StockTransaction(
                facility_id=int(facility_id),
                product_id=int(product_id),
                date=date_val,
                quantity=quantity_val,
                transaction_type=transaction_type,
                reference_number=reference_number,
                batch_number=batch_number,
                expiry_date=expiry_date_val,
                entered_by=current_user.username,
                comments=comments
            )
            db.session.add(tx)
            db.session.commit()
            flash('Transaction recorded', 'success')

        return redirect(url_for('transactions'))

    # --- Initial Page Load ---
    return render_template(
        'add_transaction.html',
        clusters=clusters,
        lgas=lgas,
        facilities=facilities,
        products=products,
        selected_cluster=g.cluster_id,
        selected_lga=g.lga_id,
        selected_facility=g.facility_id
    )
    

# --- Transactions List ---
@app.route('/transactions')
@restrict_scope
def transactions():
    from datetime import datetime
    from sqlalchemy.orm import aliased

    # Aliases for both destination and source facilities
    FacilityDest = aliased(Facility)
    FacilitySource = aliased(Facility)

    # --- Read filters from GET params ---
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    transaction_types = ['Received', 'Opening', 'Transfer-In','Issued', 'Lost', 'Damaged', 'Expired', 'Transfer','Adjusted']
    selected_transaction_type = request.args.get("transaction_type", "")
    batch_number = request.args.get('batch_number', '').strip()

    # --- Base Query ---
    query = db.session.query(
        StockTransaction.id,
        StockTransaction.date,
        StockTransaction.quantity,
        StockTransaction.transaction_type,
        StockTransaction.reference_number,
        StockTransaction.batch_number,
        StockTransaction.expiry_date,
        StockTransaction.entered_by,

        # Facility details
        Facility.id.label('facility_id'),
        Facility.name.label('facility'),

        # Destination & Source facilities
        FacilityDest.id.label('destination_facility_id'),
        FacilityDest.name.label('destination_facility'),
        FacilitySource.id.label('source_facility_id'),
        FacilitySource.name.label('source_facility'),

        # Metadata
        LGA.id.label('lga_id'),
        LGA.name.label('lga'),
        Cluster.id.label('cluster_id'),
        Cluster.name.label('cluster'),
        Product.name.label('product')
    ).join(Facility, StockTransaction.facility_id == Facility.id) \
     .outerjoin(FacilityDest, StockTransaction.destination_facility_id == FacilityDest.id) \
     .outerjoin(FacilitySource, StockTransaction.source_facility_id == FacilitySource.id) \
     .join(LGA, Facility.lga_id == LGA.id) \
     .join(Cluster, LGA.cluster_id == Cluster.id) \
     .join(Product, StockTransaction.product_id == Product.id) \
     .filter(
         (g.cluster_id is None or LGA.cluster_id == g.cluster_id),
         (g.lga_id is None or Facility.lga_id == g.lga_id),
         (g.facility_id is None or StockTransaction.facility_id == g.facility_id)
     )

    # --- Batch Number Filter ---
    if batch_number:
        query = query.filter(StockTransaction.batch_number.ilike(f"%{batch_number}%"))

    # --- Transaction Type Filter ---
    if selected_transaction_type:
        query = query.filter(StockTransaction.transaction_type == selected_transaction_type)

    # --- Apply Date Filters ---
    if start_date:
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d").date()
            query = query.filter(StockTransaction.date >= start)
        except ValueError:
            pass

    if end_date:
        try:
            end = datetime.strptime(end_date, "%Y-%m-%d").date()
            query = query.filter(StockTransaction.date <= end)
        except ValueError:
            pass

    # --- Execute Query ---
    transactions = query.order_by(StockTransaction.date.desc()).all()

    # --- Dropdowns restricted by role ---
    clusters, lgas, facilities = get_dropdowns(g.cluster_id, g.lga_id, g.facility_id)

    return render_template(
        'transactions.html',
        transactions=transactions,
        clusters=clusters,
        lgas=lgas,
        facilities=facilities,
        selected_cluster=g.cluster_id,
        selected_lga=g.lga_id,
        selected_facility=g.facility_id,
        transaction_types=transaction_types,
        selected_transaction_type=selected_transaction_type,
        start_date=start_date,
        end_date=end_date,
        batch_number=batch_number
    )
    
@app.route('/transaction/<int:id>/edit', methods=['GET', 'POST'])
@restrict_scope
def edit_transaction(id):
    # Fetch transaction or 404
    tx = StockTransaction.query.get_or_404(id)
    
    # --- Prevent editing transfer-in at destination ---
    if tx.transaction_type == "Transfer-In":
        flash("You cannot edit transactions that are Transfer-In at destination.", "danger")
        return redirect(url_for('transactions'))

    # --- Security: ensure user can edit ---
    if g.cluster_id and tx.facility.lga.cluster_id != g.cluster_id:
        abort(403)
    if g.lga_id and tx.facility.lga_id != g.lga_id:
        abort(403)
    if g.facility_id and tx.facility_id != g.facility_id:
        abort(403)

    # Dropdowns
    clusters, lgas, facilities = get_dropdowns(g.cluster_id, g.lga_id, g.facility_id)
    products = Product.query.order_by(Product.name).all()

    if request.method == 'POST':
        errors = []

        # --- Common fields ---
        facility_id = int(request.form.get('facility'))
        product_id = int(request.form.get('product'))

        # Date
        try:
            date_val = datetime.strptime(request.form.get('date'), '%Y-%m-%d').date()
            if date_val > date.today():
                errors.append("Date cannot be in the future.")
        except Exception:
            errors.append("Invalid date format.")

        # Quantity
        try:
            quantity_val = int(request.form.get('quantity'))
            if quantity_val <= 0:
                errors.append("Quantity must be greater than zero.")
        except Exception:
            errors.append("Quantity must be a valid integer.")

        transaction_type = request.form.get('transaction_type')
        reference_number = request.form.get('reference_number')
        batch_number = request.form.get('batch_number')
        expiry_str = request.form.get('expiry_date')
        expiry_date_val = datetime.strptime(expiry_str, '%Y-%m-%d').date() if expiry_str else None

        # --- NEW: Comments ---
        comments = request.form.get('comments')  # --- NEW / UPDATED ---

        # --- Handle Transfer ---
        dest_facility_id = None
        if transaction_type == 'Transfer':
            dest_facility_id = request.form.get('destination_facility')
            if not dest_facility_id:
                errors.append("Destination facility must be selected for transfers.")
            elif int(dest_facility_id) == facility_id:
                errors.append("Cannot transfer to the same facility.")
            else:
                dest_facility_id = int(dest_facility_id)

        # --- Stock check for issue/loss/transfer ---
        current_stock = db.session.query(
            (func.coalesce(FacilityProduct.beginning_balance, 0) +
             func.coalesce(
                 func.sum(
                     case(
                         (StockTransaction.transaction_type.in_(['Received', 'Opening','Transfer-In']), StockTransaction.quantity),
                         (StockTransaction.transaction_type.in_(['Issued', 'Lost', 'Damaged', 'Expired', 'Transfer']), -StockTransaction.quantity),
                         (StockTransaction.transaction_type == 'Adjusted', StockTransaction.quantity),
                         else_=0
                     )
                 ),
                 0
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
            StockTransaction.facility_id == facility_id,
            StockTransaction.id != tx.id  # exclude current transaction
        ).scalar() or 0

        if transaction_type in ('Issued', 'Lost', 'Damaged', 'Expired', 'Transfer') and quantity_val > current_stock:
            errors.append('Cannot issue/transfer more than stock on hand.')

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template(
                'edit_transaction.html',
                tx=tx,
                clusters=clusters,
                lgas=lgas,
                facilities=facilities,
                products=products,
                selected_cluster=g.cluster_id,
                selected_lga=g.lga_id,
                selected_facility=g.facility_id,
            )

        # --- Update source transaction ---
        tx.facility_id = facility_id
        tx.product_id = product_id
        tx.date = date_val
        tx.quantity = quantity_val
        tx.transaction_type = transaction_type
        tx.reference_number = reference_number
        tx.batch_number = batch_number
        tx.expiry_date = expiry_date_val
        tx.entered_by = current_user.username

        # --- NEW: update comments ---
        tx.comments = comments  # --- NEW / UPDATED ---

        # --- Update or create destination transaction if Transfer ---
        if transaction_type == 'Transfer':
            # Find existing Received transaction at destination
            received_tx = StockTransaction.query.filter_by(
                product_id=product_id,
                transaction_type='Transfer-In',
                reference_number=reference_number,
                facility_id=tx.destination_facility_id  # old destination
            ).first()

            if received_tx:
                # Update to match new quantity/destination/date
                received_tx.facility_id = dest_facility_id
                received_tx.quantity = quantity_val
                received_tx.date = date_val
                received_tx.batch_number = batch_number
                received_tx.expiry_date = expiry_date_val
                received_tx.entered_by = current_user.username

                # --- NEW: update comments on destination transaction ---
                received_tx.comments = comments  # --- NEW / UPDATED ---
            else:
                # Create Received transaction if missing
                received_tx = StockTransaction(
                    facility_id=dest_facility_id,
                    product_id=product_id,
                    date=date_val,
                    quantity=quantity_val,
                    transaction_type='Transfer-In',
                    reference_number=reference_number,
                    batch_number=batch_number,
                    expiry_date=expiry_date_val,
                    entered_by=current_user.username,
                    comments=comments  # --- NEW / UPDATED ---
                )
                db.session.add(received_tx)

            tx.destination_facility_id = dest_facility_id
        else:
            # Not a transfer → remove any existing destination transaction
            if tx.destination_facility_id:
                received_tx = StockTransaction.query.filter_by(
                    product_id=product_id,
                    transaction_type='Transfer-In',
                    reference_number=reference_number,
                    facility_id=tx.destination_facility_id
                ).first()
                if received_tx:
                    db.session.delete(received_tx)
                tx.destination_facility_id = None

        db.session.commit()
        flash('Transaction updated successfully', 'success')
        return redirect(url_for('transactions'))

    return render_template(
        'edit_transaction.html',
        tx=tx,
        clusters=clusters,
        lgas=lgas,
        facilities=facilities,
        products=products,
        selected_cluster=g.cluster_id,
        selected_lga=g.lga_id,
        selected_facility=g.facility_id,
    )

@app.route('/transaction/<int:id>/delete', methods=['POST'])
@restrict_scope
def delete_transaction(id):
    tx = StockTransaction.query.get_or_404(id)

    # --- Security: check scope before deleting ---
    if g.cluster_id and tx.facility.lga.cluster_id != g.cluster_id:
        abort(403)
    if g.lga_id and tx.facility.lga_id != g.lga_id:
        abort(403)
    if g.facility_id and tx.facility_id != g.facility_id:
        abort(403)

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
# --- Report Page ---

# --- Shared function to build report rows ---
def build_stock_report_rows(cluster_id=None, lga_id=None, facility_id=None, auto_update_min_stock=True):
    """Efficiently build stock report rows and optionally update min_stock."""
    
    # --- 1️⃣ Fetch all relevant FacilityProduct entries ---
    facility_ids = []
    product_ids = []

    # We'll fill these after query to filter relevant FacilityProduct records

    # --- 2️⃣ Compute avg_monthly_issued and stock_at_hand in a single CTE ---
    sql = text("""
    WITH monthly_issued_cte AS (
        SELECT 
            f.id AS facility_id,
            p.id AS product_id,
            STRFTIME('%Y-%m', st.date) AS month_key,
            SUM(CASE WHEN st.transaction_type='Issued' THEN st.quantity ELSE 0 END) AS monthly_issued
        FROM stock_transaction st
        JOIN product p ON p.id = st.product_id
        JOIN facility f ON f.id = st.facility_id
        JOIN lga l ON l.id = f.lga_id
        WHERE (:cluster_id IS NULL OR l.cluster_id = :cluster_id)
          AND (:lga_id IS NULL OR f.lga_id = :lga_id)
          AND (:facility_id IS NULL OR f.id = :facility_id)
          -- ✅ Highlighted change: Only last 3 months
          AND st.date >= DATE('now','-3 months')
        GROUP BY f.id, p.id, month_key
    )
    SELECT 
        c.name AS cluster_name,
        l.name AS lga_name,
        f.name AS facility_name,
        f.id AS facility_id,
        p.id AS product_id,
        p.name AS product_name,
        COALESCE(AVG(m.monthly_issued),0) AS avg_monthly_issued,
        COALESCE(
            SUM(CASE WHEN st.transaction_type IN ('Received','Opening','Transfer-In') THEN st.quantity ELSE 0 END) -
            SUM(CASE WHEN st.transaction_type IN ('Issued','Lost','Damaged','Expired','Transfer') THEN st.quantity ELSE 0 END) +
            SUM(CASE WHEN st.transaction_type='Adjusted' THEN st.quantity ELSE 0 END), 0
        ) AS stock_at_hand,
        COALESCE(fp.min_stock,0) AS min_stock
    FROM product p
    JOIN stock_transaction st ON st.product_id = p.id
    JOIN facility f ON f.id = st.facility_id
    JOIN lga l ON l.id = f.lga_id
    JOIN cluster c ON c.id = l.cluster_id
    LEFT JOIN monthly_issued_cte m ON m.facility_id = f.id AND m.product_id = p.id
    LEFT JOIN facility_product fp ON fp.facility_id = f.id AND fp.product_id = p.id
    WHERE (:cluster_id IS NULL OR l.cluster_id = :cluster_id)
      AND (:lga_id IS NULL OR f.lga_id = :lga_id)
      AND (:facility_id IS NULL OR f.id = :facility_id)
    GROUP BY c.name, l.name, f.name, p.id
    """)
    
    rows = db.session.execute(sql, {
        "cluster_id": cluster_id,
        "lga_id": lga_id,
        "facility_id": facility_id
    }).mappings().all()

    # Collect IDs for preloading FacilityProduct
    facility_ids = [r['facility_id'] for r in rows]
    product_ids = [r['product_id'] for r in rows]

    # --- 3️⃣ Preload FacilityProduct entries to avoid N+1 ---
    fps = FacilityProduct.query.filter(
        FacilityProduct.facility_id.in_(facility_ids),
        FacilityProduct.product_id.in_(product_ids)
    ).all()
    fp_map = {(fp.facility_id, fp.product_id): fp for fp in fps}

    # --- 4️⃣ Build report and update min_stock ---
    report_rows = []
    updates_made = 0

    for r in rows:
        avg = r['avg_monthly_issued']
        stock = r['stock_at_hand']
        mos = round(stock / avg, 2) if avg > 0 else None

        # Determine status
        if stock < r['min_stock']:
            status = "Below Min"
        elif avg > 0 and mos > 6:
            status = "Overstocked"
        else:
            status = "OK"

        # Auto-update min_stock if needed
        suggested_min = round(avg * 1.5)
        fp = fp_map.get((r['facility_id'], r['product_id']))

        if auto_update_min_stock and avg > 0:
            if not fp:
                # create new
                fp = FacilityProduct(
                    facility_id=r['facility_id'],
                    product_id=r['product_id'],
                    min_stock=suggested_min
                )
                db.session.add(fp)
                fp_map[(r['facility_id'], r['product_id'])] = fp
                updates_made += 1
            elif fp.min_stock == 0 or fp.min_stock < suggested_min * 0.5:
                fp.min_stock = suggested_min
                updates_made += 1

        # Add to report
        report_rows.append({
            "cluster": r['cluster_name'],
            "lga": r['lga_name'],
            "facility": r['facility_name'],
            "product": r['product_name'],
            "stock_at_hand": stock,
            "min_stock": fp.min_stock if fp else suggested_min,
            "avg_monthly_issued": round(avg,2),
            "mos": mos if mos is not None else "N/A",
            "status": status
        })

    # --- 5️⃣ Commit updates ---
    if auto_update_min_stock and updates_made > 0:
        db.session.commit()

    return report_rows


# --- Report view ---
@app.route('/report')
def report():
    # UPDATED: Use reusable scope filter
    cluster_id, lga_id, facility_id = get_user_scope_filters(
        request.args.get("cluster_id", type=int),
        request.args.get("lga_id", type=int),
        request.args.get("facility_id", type=int)
    )

    # UPDATED: Reuse dropdown function
    clusters, lgas, facilities = get_dropdowns(cluster_id, lga_id, facility_id)

    # UPDATED: Use shared function to build report rows
    report_rows = build_stock_report_rows(cluster_id, lga_id, facility_id)

    return render_template(
        "report.html",
        clusters=clusters,
        lgas=lgas,
        facilities=facilities,
        cluster_id=cluster_id,
        lga_id=lga_id,
        facility_id=facility_id,
        rows=report_rows
    )


# --- Export CSV ---
@app.route('/report/export')
def export_report():
    cluster_id, lga_id, facility_id = get_user_scope_filters(
        request.args.get("cluster_id", type=int),
        request.args.get("lga_id", type=int),
        request.args.get("facility_id", type=int)
    )

    # UPDATED: Use shared function to build report rows
    report_rows = build_stock_report_rows(cluster_id, lga_id, facility_id)

    # --- Stream CSV safely ---
    def generate():
        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_ALL)

        header = ["Cluster", "LGA", "Facility", "Product",
                  "Stock at Hand", "Min Stock", "Avg Monthly Issued", "MOS", "Status"]
        writer.writerow(header)
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)

        for r in report_rows:
            writer.writerow([
                r['cluster'], r['lga'], r['facility'], r['product'],
                r['stock_at_hand'], r['min_stock'], r['avg_monthly_issued'],
                r['mos'], r['status']
            ])
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)

    return Response(
        generate(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=stock_report.csv"}
    )


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