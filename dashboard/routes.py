from flask import render_template, jsonify, request
from sqlalchemy import func, case, extract
from datetime import datetime, timedelta

from models import db, Cluster, LGA, Facility, Product, FacilityProduct, StockTransaction
from . import dashboard_bp

# dashboard page
@dashboard_bp.route('/')
def dashboard_home():
    clusters = Cluster.query.order_by(Cluster.name).all()
    products = Product.query.order_by(Product.name).all()
    return render_template('dashboard.html', clusters=clusters, products=products)


@dashboard_bp.route('/get_lgas/<int:cluster_id>')
def get_lgas(cluster_id):
    lgas = LGA.query.filter_by(cluster_id=cluster_id).order_by(LGA.name).all()
    return jsonify([{"id": l.id, "name": l.name} for l in lgas])


@dashboard_bp.route('/get_facilities/<int:lga_id>')
def get_facilities(lga_id):
    facilities = Facility.query.filter_by(lga_id=lga_id).order_by(Facility.name).all()
    return jsonify([{"id": f.id, "name": f.name} for f in facilities])


@dashboard_bp.route('/api/dashboard_data')
def api_dashboard_data():
    """
    Returns:
      - product_stock: [[product_name, stock_at_hand, min_stock], ...]
      - top_facilities: [[facility_name, stock_at_hand], ...]
      - summary: { total_stock, facilities_in_stockout, facilities_below_min, average_mos, products_near_expiry }
      - consumption_trend: { months: [...], values: [...] }
      - wastage_breakdown: { labels: [...], values: [...] }
      - expiry_list: [ {product, batch, facility, expiry_date, quantity}, ... ]
      - expired: { total_expired_qty, by_product: [...], by_facility: [...] }
      - alerts: [ string, ... ]
    """
    cluster_id = request.args.get('cluster_id', type=int)
    lga_id = request.args.get('lga_id', type=int)
    facility_id = request.args.get('facility_id', type=int)
    product_id = request.args.get('product_id', type=int)
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    try:
        if start_date_str:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        else:
            start_date = (datetime.utcnow() - timedelta(days=365)).date()
        if end_date_str:
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        else:
            end_date = datetime.utcnow().date()
    except Exception:
        start_date = (datetime.utcnow() - timedelta(days=365)).date()
        end_date = datetime.utcnow().date()

    tx = StockTransaction

    # CASE expression for stock movement
    stock_case = case(
        (tx.transaction_type.in_(['Received', 'Opening']), tx.quantity),
        (tx.transaction_type == 'Adjusted', tx.quantity),
        (tx.transaction_type.in_(['Issued', 'Lost', 'Damaged', 'Expired']), -tx.quantity),
        else_=0
    )

    ## --- PRODUCT STOCK ---
    prod_q = (
        db.session.query(
            Product.id.label('product_id'),
            Product.name.label('product_name'),
            func.coalesce(func.sum(stock_case), 0).label('stock_delta'),
            func.coalesce(func.sum(FacilityProduct.min_stock), 0).label('min_stock_sum')
        )
        .join(tx, tx.product_id == Product.id)
        .outerjoin(FacilityProduct, FacilityProduct.product_id == Product.id)
        .group_by(Product.id)
    )
    if cluster_id:
        prod_q = prod_q.join(Facility, Facility.id == tx.facility_id).join(LGA).filter(LGA.cluster_id == cluster_id)
    if lga_id:
        prod_q = prod_q.join(Facility, Facility.id == tx.facility_id).filter(Facility.lga_id == lga_id)
    if facility_id:
        prod_q = prod_q.filter(tx.facility_id == facility_id)
    if product_id:
        prod_q = prod_q.filter(Product.id == product_id)

    product_rows = prod_q.all()
    product_stock = []
    for r in product_rows:
        beginning_total = (
            db.session.query(func.coalesce(func.sum(FacilityProduct.beginning_balance), 0))
            .filter(FacilityProduct.product_id == r.product_id)
            .scalar()
        )
        stock_at_hand = int((r.stock_delta or 0) + (beginning_total or 0))
        min_stock = int(r.min_stock_sum or 0)
        product_stock.append([r.product_name, stock_at_hand, min_stock])

    ## --- TOP FACILITIES ---
    fac_q = (
        db.session.query(
            Facility.id.label('facility_id'),
            Facility.name.label('facility_name'),
            func.coalesce(func.sum(stock_case), 0).label('stock_delta')
        )
        .join(tx, tx.facility_id == Facility.id)
        .group_by(Facility.id)
    )
    if cluster_id:
        fac_q = fac_q.join(LGA).filter(LGA.cluster_id == cluster_id)
    if lga_id:
        fac_q = fac_q.filter(Facility.lga_id == lga_id)
    if facility_id:
        fac_q = fac_q.filter(Facility.id == facility_id)
    if product_id:
        fac_q = fac_q.filter(tx.product_id == product_id)

    fac_rows = fac_q.all()
    top_facilities = []
    for f in fac_rows:
        beginning_total = (
            db.session.query(func.coalesce(func.sum(FacilityProduct.beginning_balance), 0))
            .filter(FacilityProduct.facility_id == f.facility_id)
            .scalar()
        )
        stock_at_hand = int((f.stock_delta or 0) + (beginning_total or 0))
        top_facilities.append((f.facility_name, stock_at_hand))
    top_facilities = sorted(top_facilities, key=lambda x: x[1], reverse=True)[:5]

    ## --- SUMMARY ---
    total_stock = sum([p[1] for p in product_stock])
    # facilities_in_stockout & below_min
    fac_stock_q = (
        db.session.query(
            Facility.id.label('facility_id'),
            func.coalesce(func.sum(stock_case), 0).label('stock_delta')
        )
        .join(tx, tx.facility_id == Facility.id)
        .group_by(Facility.id)
    )
    if cluster_id:
        fac_stock_q = fac_stock_q.join(LGA).filter(LGA.cluster_id == cluster_id)
    if lga_id:
        fac_stock_q = fac_stock_q.filter(Facility.lga_id == lga_id)
    if facility_id:
        fac_stock_q = fac_stock_q.filter(Facility.id == facility_id)
    if product_id:
        fac_stock_q = fac_stock_q.filter(tx.product_id == product_id)

    facility_stock_rows = fac_stock_q.all()
    facilities_in_stockout_count = 0
    facilities_below_min_count = 0
    for f in facility_stock_rows:
        beginning_total = (
            db.session.query(func.coalesce(func.sum(FacilityProduct.beginning_balance), 0))
            .filter(FacilityProduct.facility_id == f.facility_id)
            .scalar()
        )
        stock_total = int((f.stock_delta or 0) + (beginning_total or 0))
        min_total_q = db.session.query(func.coalesce(func.sum(FacilityProduct.min_stock), 0)).filter(FacilityProduct.facility_id == f.facility_id)
        if product_id:
            min_total_q = min_total_q.filter(FacilityProduct.product_id == product_id)
        min_total = int(min_total_q.scalar() or 0)
        if stock_total <= 0:
            facilities_in_stockout_count += 1
        if min_total > 0 and stock_total < min_total:
            facilities_below_min_count += 1

    average_mos = 0
    mos_values = []
    for prod in product_stock:
        prod_name, stock_val, min_sum = prod
        if min_sum and min_sum > 0:
            mos_values.append(stock_val / min_sum)
    if mos_values:
        average_mos = round(sum(mos_values)/len(mos_values), 1)

    now = datetime.utcnow().date()
    three_months = now + timedelta(days=90)
    six_months = now + timedelta(days=180)
    expiry_count_q = db.session.query(func.count(func.distinct(StockTransaction.product_id))).filter(
        StockTransaction.expiry_date != None,
        StockTransaction.expiry_date >= three_months,
        StockTransaction.expiry_date <= six_months
    )
    if cluster_id:
        expiry_count_q = expiry_count_q.join(Facility).join(LGA).filter(LGA.cluster_id == cluster_id)
    if lga_id:
        expiry_count_q = expiry_count_q.join(Facility).filter(Facility.lga_id == lga_id)
    if facility_id:
        expiry_count_q = expiry_count_q.filter(Facility.id == facility_id)
    if product_id:
        expiry_count_q = expiry_count_q.filter(StockTransaction.product_id == product_id)
    products_near_expiry = int(expiry_count_q.scalar() or 0)

    summary = {
        "total_stock": total_stock,
        "facilities_in_stockout": facilities_in_stockout_count,
        "facilities_below_min": facilities_below_min_count,
        "average_mos": average_mos,
        "products_near_expiry": products_near_expiry
    }

    ## --- CONSUMPTION TREND ---
    ct_q = db.session.query(
        extract('year', tx.date).label('yr'),
        extract('month', tx.date).label('mo'),
        func.coalesce(func.sum(
            case(((tx.transaction_type == 'Issued'), tx.quantity), else_=0)
        ), 0).label('issued_qty')
    ).filter(tx.transaction_type == 'Issued', tx.date >= start_date, tx.date <= end_date)
    if cluster_id:
        ct_q = ct_q.join(Facility).join(LGA).filter(LGA.cluster_id == cluster_id)
    if lga_id:
        ct_q = ct_q.join(Facility).filter(Facility.lga_id == lga_id)
    if facility_id:
        ct_q = ct_q.filter(tx.facility_id == facility_id)
    if product_id:
        ct_q = ct_q.filter(tx.product_id == product_id)
    ct_q = ct_q.group_by('yr', 'mo').order_by('yr', 'mo')
    ct_rows = ct_q.all()
    months = []
    vals = []
    cur = start_date.replace(day=1)
    end_month = end_date.replace(day=1)
    ct_map = {(int(r.yr), int(r.mo)): int(r.issued_qty or 0) for r in ct_rows}
    while cur <= end_month:
        months.append(cur.strftime("%b %Y"))
        key = (cur.year, cur.month)
        vals.append(ct_map.get(key, 0))
        next_month = cur.month % 12 + 1
        next_year = cur.year + (cur.month // 12)
        cur = cur.replace(year=next_year, month=next_month)
    consumption_trend = {"months": months, "values": vals}

    ## --- WASTAGE ---
    wastage_types = ['Lost', 'Damaged', 'Expired']
    wastage_q = db.session.query(
        tx.transaction_type,
        func.coalesce(func.sum(tx.quantity), 0).label('qty')
    ).filter(tx.transaction_type.in_(wastage_types), tx.date >= start_date, tx.date <= end_date)
    if cluster_id:
        wastage_q = wastage_q.join(Facility).join(LGA).filter(LGA.cluster_id == cluster_id)
    if lga_id:
        wastage_q = wastage_q.join(Facility).filter(Facility.lga_id == lga_id)
    if facility_id:
        wastage_q = wastage_q.filter(tx.facility_id == facility_id)
    if product_id:
        wastage_q = wastage_q.filter(tx.product_id == product_id)
    wastage_q = wastage_q.group_by(tx.transaction_type)
    wastage_rows = {r.transaction_type: int(r.qty or 0) for r in wastage_q.all()}
    wastage_labels = wastage_types
    wastage_values = [wastage_rows.get(t, 0) for t in wastage_types]
    wastage_breakdown = {"labels": wastage_labels, "values": wastage_values}

    ## --- EXPIRY LIST ---
    expiry_threshold = now + timedelta(days=180)
    expiry_q = db.session.query(
        Product.name.label('product'),
        tx.batch_number.label('batch'),
        Facility.name.label('facility'),
        tx.expiry_date.label('expiry_date'),
        func.coalesce(func.sum(stock_case), 0).label('quantity')
    ).join(Product, Product.id == tx.product_id).join(Facility, Facility.id == tx.facility_id) \
     .filter(tx.expiry_date != None, tx.expiry_date <= expiry_threshold, tx.expiry_date >= now)
    if cluster_id:
        expiry_q = expiry_q.join(LGA).filter(LGA.cluster_id == cluster_id)
    if lga_id:
        expiry_q = expiry_q.filter(Facility.lga_id == lga_id)
    if facility_id:
        expiry_q = expiry_q.filter(Facility.id == facility_id)
    if product_id:
        expiry_q = expiry_q.filter(tx.product_id == product_id)
    expiry_q = expiry_q.group_by('product', 'batch', 'facility', 'expiry_date').order_by('expiry_date')
    expiry_rows = expiry_q.having(func.sum(stock_case) > 0).all()
    expiry_list = [
        {"product": r.product, "batch": (r.batch or ""), "facility": r.facility,
         "expiry_date": (r.expiry_date.isoformat() if r.expiry_date else None),
         "quantity": max(int(r.quantity or 0), 0)}
        for r in expiry_rows
    ]

    ## --- EXPIRED STOCK ---
    expired_q = db.session.query(
        Product.name.label('product'),
        Facility.name.label('facility'),
        func.coalesce(func.sum(stock_case), 0).label('qty')
    ).join(Product, Product.id == tx.product_id).join(Facility, Facility.id == tx.facility_id) \
     .filter(tx.expiry_date != None, tx.expiry_date < now)
    if cluster_id:
        expired_q = expired_q.join(LGA).filter(LGA.cluster_id == cluster_id)
    if lga_id:
        expired_q = expired_q.filter(Facility.lga_id == lga_id)
    if facility_id:
        expired_q = expired_q.filter(Facility.id == facility_id)
    if product_id:
        expired_q = expired_q.filter(tx.product_id == product_id)

    total_expired_qty = int(db.session.query(func.coalesce(func.sum(stock_case), 0))
                             .filter(tx.expiry_date != None, tx.expiry_date < now)
                             .scalar() or 0)

    expired_by_product = []
    expired_prod_rows = expired_q.group_by('product').all()
    for r in expired_prod_rows:
        expired_by_product.append({"product": r.product, "quantity": int(r.qty or 0)})

    expired_by_facility = []
    expired_fac_rows = expired_q.group_by('facility').all()
    for r in expired_fac_rows:
        expired_by_facility.append({"facility": r.facility, "quantity": int(r.qty or 0)})

    ## --- ALERTS ---
    alerts = []
    fprod_q = db.session.query(FacilityProduct.facility_id, FacilityProduct.product_id, FacilityProduct.min_stock)
    if facility_id:
        fprod_q = fprod_q.filter(FacilityProduct.facility_id == facility_id)
    if product_id:
        fprod_q = fprod_q.filter(FacilityProduct.product_id == product_id)
    fprod_rows = fprod_q.all()
    for fp in fprod_rows:
        delta = db.session.query(func.coalesce(func.sum(stock_case), 0)).filter(
            tx.facility_id == fp.facility_id, tx.product_id == fp.product_id).scalar() or 0
        beginning = db.session.query(func.coalesce(func.sum(FacilityProduct.beginning_balance), 0)).filter(
            FacilityProduct.facility_id == fp.facility_id, FacilityProduct.product_id == fp.product_id).scalar() or 0
        current_stock = int(delta + beginning)
        if current_stock < fp.min_stock:
            fac = Facility.query.get(fp.facility_id)
            prod = Product.query.get(fp.product_id)
            alerts.append(f"{prod.name} below minimum stock in {fac.name} (Current: {current_stock}, Min: {fp.min_stock})")
        if len(alerts) >= 20:
            break

    expiry_alert_threshold = now + timedelta(days=60)
    exp_alert_q = db.session.query(tx).filter(tx.expiry_date != None, tx.expiry_date <= expiry_alert_threshold, tx.expiry_date >= now)
    if product_id:
        exp_alert_q = exp_alert_q.filter(tx.product_id == product_id)
    if cluster_id or lga_id or facility_id:
        exp_alert_q = exp_alert_q.join(Facility)
        if cluster_id:
            exp_alert_q = exp_alert_q.join(LGA).filter(LGA.cluster_id == cluster_id)
        if lga_id:
            exp_alert_q = exp_alert_q.filter(Facility.lga_id == lga_id)
        if facility_id:
            exp_alert_q = exp_alert_q.filter(Facility.id == facility_id)
    exp_rows = exp_alert_q.order_by(tx.expiry_date).limit(20).all()
    for e in exp_rows:
        prod = Product.query.get(e.product_id)
        fac = Facility.query.get(e.facility_id)
        days_left = (e.expiry_date - now).days if e.expiry_date else None
        alerts.append(f"{prod.name} batch #{(e.batch_number or '')} expiring in {days_left} days at {fac.name}")
        if len(alerts) >= 40:
            break

    return jsonify({
        "product_stock": product_stock,
        "top_facilities": top_facilities,
        "summary": summary,
        "consumption_trend": consumption_trend,
        "wastage_breakdown": wastage_breakdown,
        "expiry_list": expiry_list,
        "expired": {
            "total_expired_qty": total_expired_qty,
            "by_product": expired_by_product,
            "by_facility": expired_by_facility
        },
        "alerts": alerts
    })
