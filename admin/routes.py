from flask import Blueprint, render_template, request, redirect, url_for, flash
from models import db, Cluster, LGA, Facility, Product

admin_bp = Blueprint('admin', __name__, url_prefix="/admin")

@admin_bp.route("/data")
def manage_data():
    clusters = Cluster.query.order_by(Cluster.name).all()
    lgas = LGA.query.order_by(LGA.name).all()
    facilities = Facility.query.order_by(Facility.name).all()
    products = Product.query.all() 
    return render_template("manage_data.html", clusters=clusters, lgas=lgas, facilities=facilities, products=products)

@admin_bp.route("/cluster/add", methods=["POST"])
def add_cluster():
    name = request.form.get("name")
    if name:
        db.session.add(Cluster(name=name))
        db.session.commit()
        flash("Cluster added!", "success")
    return redirect(url_for("admin.manage_data"))

@admin_bp.route("/cluster/delete/<int:id>")
def delete_cluster(id):
    c = Cluster.query.get_or_404(id)
    db.session.delete(c)
    db.session.commit()
    flash("Cluster deleted", "info")
    return redirect(url_for("admin.manage_data"))

@admin_bp.route("/lga/add", methods=["POST"])
def add_lga():
    name = request.form.get("name")
    cluster_id = request.form.get("cluster_id")
    if name and cluster_id:
        db.session.add(LGA(name=name, cluster_id=cluster_id))
        db.session.commit()
        flash("LGA added!", "success")
    return redirect(url_for("admin.manage_data"))

@admin_bp.route("/lga/delete/<int:id>")
def delete_lga(id):
    l = LGA.query.get_or_404(id)
    db.session.delete(l)
    db.session.commit()
    flash("LGA deleted", "info")
    return redirect(url_for("admin.manage_data"))

@admin_bp.route("/facility/add", methods=["POST"])
def add_facility():
    name = request.form.get("name")
    lga_id = request.form.get("lga_id")
    if name and lga_id:
        db.session.add(Facility(name=name, lga_id=lga_id))
        db.session.commit()
        flash("Facility added!", "success")
    return redirect(url_for("admin.manage_data"))

@admin_bp.route("/facility/delete/<int:id>")
def delete_facility(id):
    f = Facility.query.get_or_404(id)
    db.session.delete(f)
    db.session.commit()
    flash("Facility deleted", "info")
    return redirect(url_for("admin.manage_data"))

@admin_bp.route("/cluster/edit/<int:id>", methods=["POST"])
def edit_cluster(id):
    c = Cluster.query.get_or_404(id)
    c.name = request.form.get("name")
    db.session.commit()
    flash("Cluster updated!", "success")
    return redirect(url_for("admin.manage_data"))

@admin_bp.route("/lga/edit/<int:id>", methods=["POST"])
def edit_lga(id):
    l = LGA.query.get_or_404(id)
    l.name = request.form.get("name")
    l.cluster_id = request.form.get("cluster_id")
    db.session.commit()
    flash("LGA updated!", "success")
    return redirect(url_for("admin.manage_data"))

@admin_bp.route("/facility/edit/<int:id>", methods=["POST"])
def edit_facility(id):
    f = Facility.query.get_or_404(id)
    f.name = request.form.get("name")
    f.lga_id = request.form.get("lga_id")
    db.session.commit()
    flash("Facility updated!", "success")
    return redirect(url_for("admin.manage_data"))

@admin_bp.route('/add_product', methods=['POST'])
def add_product():
    name = request.form['name']
    if name:
        db.session.add(Product(name=name))
        db.session.commit()
        flash('Product added successfully', 'success')
    return redirect(url_for('admin.manage_data'))

@admin_bp.route('/edit_product/<int:id>', methods=['POST'])
def edit_product(id):
    product = Product.query.get_or_404(id)
    product.name = request.form['name']
    db.session.commit()
    flash('Product updated successfully', 'success')
    return redirect(url_for('admin.manage_data'))

@admin_bp.route('/delete_product/<int:id>')
def delete_product(id):
    product = Product.query.get_or_404(id)
    db.session.delete(product)
    db.session.commit()
    flash('Product deleted successfully', 'success')
    return redirect(url_for('admin.manage_data'))


