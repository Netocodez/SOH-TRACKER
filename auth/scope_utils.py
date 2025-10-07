from functools import wraps
from flask import g, request
from flask_login import current_user
from models import Cluster, LGA, Facility


# --- Role-based scope filters ---
def get_user_scope_filters(cluster_id=None, lga_id=None, facility_id=None):
    """
    Returns restricted cluster_id, lga_id, facility_id
    based on current_user role and requested filters.
    """
    if current_user.role in ['super', 'admin']:
        return cluster_id, lga_id, facility_id

    if current_user.role == 'cluster':
        if not cluster_id:
            cluster_id = current_user.cluster_id
        return cluster_id, lga_id, facility_id

    if current_user.role == 'lga':
        lga_id = current_user.lga_id
        cluster_id = current_user.lga.cluster_id
        return cluster_id, lga_id, facility_id

    if current_user.role == 'facility':
        facility_id = current_user.facility_id
        lga_id = current_user.facility.lga_id
        cluster_id = current_user.facility.lga.cluster_id
        return cluster_id, lga_id, facility_id

    return cluster_id, lga_id, facility_id


# --- Decorator to apply filters automatically ---
def restrict_scope(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        cluster_id = request.args.get("cluster", type=int)
        lga_id = request.args.get("lga", type=int)
        facility_id = request.args.get("facility", type=int)

        g.cluster_id, g.lga_id, g.facility_id = get_user_scope_filters(
            cluster_id, lga_id, facility_id
        )
        return f(*args, **kwargs)
    return wrapper


# --- Dropdown builder ---
def get_dropdowns(cluster_id=None, lga_id=None, facility_id=None):
    """Return (clusters, lgas, facilities) restricted to user role."""
    clusters, lgas, facilities = [], [], []

    # Super admin
    if current_user.role in ["super", "admin"]:
        clusters = Cluster.query.order_by(Cluster.name).all()
        if cluster_id:
            lgas = LGA.query.filter_by(cluster_id=cluster_id).order_by(LGA.name).all()
        if lga_id:
            facilities = Facility.query.filter_by(lga_id=lga_id).order_by(Facility.name).all()

    # Cluster-level
    elif current_user.role == "cluster":
        clusters = Cluster.query.filter_by(id=current_user.cluster_id).all()
        lgas = LGA.query.filter_by(cluster_id=current_user.cluster_id).order_by(LGA.name).all()
        if lga_id:
            facilities = Facility.query.filter_by(lga_id=lga_id).order_by(Facility.name).all()

    # LGA-level
    elif current_user.role == "lga":
        clusters = Cluster.query.filter_by(id=cluster_id).all()
        lgas = LGA.query.filter_by(id=current_user.lga_id).all()
        if lga_id:
            facilities = Facility.query.filter_by(lga_id=lga_id).order_by(Facility.name).all()

    # Facility-level
    elif current_user.role == "facility":
        clusters = Cluster.query.filter_by(id=cluster_id).all()
        lgas = LGA.query.filter_by(id=lga_id).all()
        facilities = Facility.query.filter_by(id=current_user.facility_id).all()

    return clusters, lgas, facilities
