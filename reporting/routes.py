from flask import Blueprint, render_template, request
from flask_login import login_required
from sqlalchemy import func, or_, extract
from datetime import datetime
from models import db, Cluster, LGA, Facility, StockTransaction
from auth.scope_utils import get_user_scope_filters

reporting_bp = Blueprint("reporting_bp", __name__)

@reporting_bp.route("/rate", methods=["GET", "POST"])
@login_required
def reporting_rate():
    """Track facility reporting rate by month."""
    
    # --- 1️⃣ Unpack user scope (cluster, lga, facility)
    scope_filters = get_user_scope_filters()
    cluster_id, lga_id, facility_id = scope_filters if isinstance(scope_filters, tuple) else (None, None, None)

    # --- 2️⃣ Load dropdown data
    clusters = Cluster.query.order_by(Cluster.name).all()
    lgas = LGA.query.order_by(LGA.name).all()
    facilities = Facility.query.order_by(Facility.name).all()

    reporting_rate = None
    facilities_expected = []

    # --- 3️⃣ If form submitted, compute reporting rate
    if request.method == "POST":
        selected_cluster = request.form.get("cluster_id") or None
        selected_lga = request.form.get("lga_id") or None
        selected_facility = request.form.get("facility_id") or None
        reporting_month = request.form.get("reporting_month")

        # Parse reporting month into year & month
        if reporting_month:
            try:
                selected_date = datetime.strptime(reporting_month, "%Y-%m")
                year = selected_date.year
                month = selected_date.month
            except ValueError:
                year, month = None, None
        else:
            year, month = None, None

        # --- 4️⃣ Get expected facilities
        facilities_query = Facility.query
        if selected_facility:
            facilities_query = facilities_query.filter(Facility.id == selected_facility)
        elif selected_lga:
            facilities_query = facilities_query.filter(Facility.lga_id == selected_lga)
        elif selected_cluster:
            facilities_query = facilities_query.join(LGA).filter(LGA.cluster_id == selected_cluster)
        facilities_expected = facilities_query.order_by(Facility.name).all()

        total_facilities = len(facilities_expected)
        reported_facilities = 0

        # --- 5️⃣ For each facility, check if it reported that month
        facility_status = []
        for f in facilities_expected:
            has_data = (
                db.session.query(StockTransaction)
                .filter(
                    StockTransaction.facility_id == f.id,
                    extract("year", StockTransaction.date) == year,
                    extract("month", StockTransaction.date) == month,
                )
                .first()
                is not None
            )
            facility_status.append({
                "facility_name": f.name,
                "reported": has_data
            })
            if has_data:
                reported_facilities += 1

        # --- 6️⃣ Compute reporting rate
        if total_facilities > 0:
            reporting_rate = round((reported_facilities / total_facilities) * 100, 1)
        else:
            reporting_rate = 0

        facilities_expected = facility_status

    # --- 7️⃣ Render page
    return render_template(
        "reporting_rate.html",
        clusters=clusters,
        lgas=lgas,
        facilities=facilities,
        reporting_rate=reporting_rate,
        facilities_expected=facilities_expected
    )