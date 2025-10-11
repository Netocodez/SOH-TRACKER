from datetime import datetime
from models import db, StockTransaction, Cluster, LGA, Facility, Product

def get_transaction_query(start_date=None, end_date=None, transaction_type=None,
                          cluster_id=None, lga_id=None, facility_id=None):
    query = db.session.query(
        StockTransaction.date,
        Cluster.name.label('cluster'),
        LGA.name.label('lga'),
        Facility.name.label('facility'),
        Product.name.label('product'),
        StockTransaction.quantity,
        StockTransaction.transaction_type,
        StockTransaction.reference_number,
        StockTransaction.batch_number,
        StockTransaction.expiry_date,
        StockTransaction.entered_by
    ).join(Facility, StockTransaction.facility_id == Facility.id) \
     .join(LGA, Facility.lga_id == LGA.id) \
     .join(Cluster, LGA.cluster_id == Cluster.id) \
     .join(Product, StockTransaction.product_id == Product.id)

    # Scope filters
    if cluster_id:
        query = query.filter(LGA.cluster_id == cluster_id)
    if lga_id:
        query = query.filter(Facility.lga_id == lga_id)
    if facility_id:
        query = query.filter(StockTransaction.facility_id == facility_id)

    # Transaction type
    if transaction_type and transaction_type != 'All':
        query = query.filter(StockTransaction.transaction_type == transaction_type)

    # Date filters
    if start_date:
        query = query.filter(StockTransaction.date >= datetime.strptime(start_date, "%Y-%m-%d"))
    if end_date:
        query = query.filter(StockTransaction.date <= datetime.strptime(end_date, "%Y-%m-%d"))

    return query.order_by(StockTransaction.date.asc())
