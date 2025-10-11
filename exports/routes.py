from flask import render_template, request, send_file, Response, flash, redirect, url_for, g, stream_with_context, jsonify
from io import BytesIO, StringIO
import csv
import pandas as pd
from datetime import datetime
from flask_login import login_required
from . import export_bp
from .utils import get_transaction_query
from models import Product, LGA, Facility
from auth.scope_utils import restrict_scope, get_dropdowns

# ------------------------------
# AJAX: Get LGAs & Facilities
# ------------------------------
@export_bp.route('/get_lgas/<int:cluster_id>')
@login_required
def get_lgas(cluster_id):
    """Return LGAs under a selected cluster."""
    lgas = LGA.query.filter_by(cluster_id=cluster_id).order_by(LGA.name).all()
    return jsonify([{'id': l.id, 'name': l.name} for l in lgas])


@export_bp.route('/get_facilities/<int:lga_id>')
@login_required
def get_facilities(lga_id):
    """Return facilities under a selected LGA."""
    facilities = Facility.query.filter_by(lga_id=lga_id).order_by(Facility.name).all()
    return jsonify([{'id': f.id, 'name': f.name} for f in facilities])

# ------------------------------
# EXPORT PAGE (Form + Filters)
# ------------------------------
@export_bp.route('/', methods=['GET'])
@login_required
@restrict_scope
def export_transactions_page():
    """Renders the export filters page."""
    clusters, lgas, facilities = get_dropdowns(g.cluster_id, g.lga_id, g.facility_id)
    products = Product.query.order_by(Product.name).all()

    # now template is directly inside /templates
    return render_template(
        'export_transactions.html',
        clusters=clusters,
        lgas=lgas,
        facilities=facilities,
        products=products,
    )


# ------------------------------
# EXPORT TO EXCEL
# ------------------------------
@export_bp.route('/excel', methods=['POST'])
@login_required
@restrict_scope
def export_transactions_excel():
    """Exports filtered transactions to Excel."""
    filters = {
        'cluster_id': request.form.get('cluster_id', type=int),
        'lga_id': request.form.get('lga_id', type=int),
        'facility_id': request.form.get('facility_id', type=int),
        'start_date': request.form.get('start_date'),
        'end_date': request.form.get('end_date'),
        'transaction_type': request.form.get('transaction_type'),
    }

    query = get_transaction_query(**filters)
    transactions = query.all()

    if not transactions:
        flash("No transactions found for selected filters.", "warning")
        return redirect(url_for('exports.export_transactions_page'))

    df = pd.DataFrame(transactions, columns=[
        'Date', 'Cluster', 'LGA', 'Facility', 'Product',
        'Quantity', 'Type', 'Reference', 'Batch', 'Expiry', 'Entered By'
    ])

    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Transactions')
        worksheet = writer.sheets['Transactions']
        for i, col in enumerate(df.columns):
            width = max(df[col].astype(str).map(len).max(), len(col)) + 2
            worksheet.set_column(i, i, width)

    output.seek(0)
    filename = f"StockTransactions_{datetime.now():%Y%m%d_%H%M%S}.xlsx"

    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


# ------------------------------
# EXPORT TO CSV (Streamed)
# ------------------------------
@export_bp.route('/csv', methods=['POST'])
@login_required
@restrict_scope
def export_transactions_csv():
    """Streams filtered transactions to CSV to avoid memory load."""
    filters = {
        'cluster_id': request.form.get('cluster_id', type=int),
        'lga_id': request.form.get('lga_id', type=int),
        'facility_id': request.form.get('facility_id', type=int),
        'start_date': request.form.get('start_date'),
        'end_date': request.form.get('end_date'),
        'transaction_type': request.form.get('transaction_type'),
    }

    query = get_transaction_query(**filters)

    def generate():
        output = StringIO()
        writer = csv.writer(output)
        header = [
            "Date", "Cluster", "LGA", "Facility", "Product",
            "Quantity", "Type", "Reference", "Batch", "Expiry", "Entered By"
        ]
        writer.writerow(header)
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)

        for row in query:
            writer.writerow([
                row.date.strftime("%Y-%m-%d") if row.date else "",
                row.cluster or "",
                row.lga or "",
                row.facility or "",
                row.product or "",
                row.quantity or "",
                row.transaction_type or "",
                row.reference_number or "",
                row.batch_number or "",
                row.expiry_date.strftime("%Y-%m-%d") if row.expiry_date else "",
                row.entered_by or ""
            ])
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)

    filename = f"StockTransactions_{datetime.now():%Y%m%d_%H%M%S}.csv"

    return Response(
        stream_with_context(generate()),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )