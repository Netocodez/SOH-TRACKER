from models import db, Cluster, LGA, Facility, Product, StockTransaction
import pandas as pd
from sqlalchemy import func

def get_db_used_totals_with_keys(start_date, end_date):
    """
    Aggregate total 'Used' quantity from StockTransaction per facility, product, and date,
    including facility, LGA, cluster, and orgunitid for DHIS2 comparison.
    """
    totals = (
        db.session.query(
            StockTransaction.facility_id,
            Facility.name.label("facility_name"),
            Facility.newdpt_orgunitid.label("orgunitid"),
            LGA.id.label("lga_id"),
            LGA.name.label("lga_name"),
            Cluster.id.label("cluster_id"),
            Cluster.name.label("cluster_name"),
            StockTransaction.product_id,
            Product.name.label("product_name"),
            StockTransaction.date.label("date"),
            func.sum(StockTransaction.quantity).label("total_used")
        )
        .join(Facility, StockTransaction.facility_id == Facility.id)
        .join(LGA, Facility.lga_id == LGA.id)
        .join(Cluster, LGA.cluster_id == Cluster.id)
        .join(Product, StockTransaction.product_id == Product.id)
        .filter(
            StockTransaction.transaction_type == "Issued",
            StockTransaction.date.between(start_date, end_date)
        )
        .group_by(
            StockTransaction.facility_id,
            Facility.name,
            Facility.newdpt_orgunitid,
            LGA.id,
            LGA.name,
            Cluster.id,
            Cluster.name,
            StockTransaction.product_id,
            Product.name,
            StockTransaction.date
        )
        .all()
    )

    result = []
    for r in totals:
        result.append({
            "facility_id": r.facility_id,
            "facility_name": r.facility_name,
            "orgunitid": r.orgunitid,
            "lga_id": r.lga_id,
            "lga_name": r.lga_name,
            "cluster_id": r.cluster_id,
            "cluster_name": r.cluster_name,
            "product_id": r.product_id,
            "product_name": r.product_name,
            "date": r.date.strftime("%Y-%m-%d"),
            "total_used": r.total_used
        })
    return result

def fetch_facility_hierarchy():
    """
    Fetch all facilities with LGA and Cluster info for filling missing data.
    Returns a DataFrame with:
    orgunitid, facility_id, facility_name, lga_id, lga_name, cluster_id, cluster_name
    """
    query = (
        db.session.query(
            Facility.newdpt_orgunitid.label("orgunitid"),
            Facility.id.label("facility_id"),
            Facility.name.label("facility_name"),
            LGA.id.label("lga_id"),
            LGA.name.label("lga_name"),
            Cluster.id.label("cluster_id"),
            Cluster.name.label("cluster_name"),
        )
        .join(LGA, Facility.lga_id == LGA.id)
        .join(Cluster, LGA.cluster_id == Cluster.id)
        .all()
    )

    # Convert to DataFrame
    df = pd.DataFrame(query, columns=[
        "orgunitid", "facility_id", "facility_name",
        "lga_id", "lga_name", "cluster_id", "cluster_name"
    ])
    
    # Strip orgunitid whitespace
    if 'orgunitid' in df.columns:
        df['orgunitid'] = df['orgunitid'].astype(str).str.strip()
    
    return df