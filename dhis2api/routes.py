from flask import jsonify, request, render_template, send_from_directory
from . import dhis2api_bp
from .dhis2_utils import fetch_dhis2_data, load_dhis2_csv_to_df, aggregate_dhis2_data
from .db_utils import get_db_used_totals_with_keys
from .merge_utils import merge_db_and_dhis2
import os
import pandas as pd

# --- Define the export directory (same as in dhis2_utils) ---
EXPORT_DIR = os.path.join(os.getcwd(), "dhis2downloads")
os.makedirs(EXPORT_DIR, exist_ok=True)

@dhis2api_bp.route('/fetch_page')
def fetch_page():
    """Renders the DHIS2 Fetch UI page"""
    return render_template('dhis2_fetch.html')

@dhis2api_bp.route('/fetch', methods=['GET'])
def fetch_dhis2_data_route():
    start_date = request.args.get('start_date', '2025-10-01')
    end_date = request.args.get('end_date', '2025-10-13')

    # --- Fetch DHIS2 data ---
    result = fetch_dhis2_data(start_date, end_date)
    if result.get("status") != "success":
        return jsonify({
            "status": "error",
            "message": result.get("message", "Failed to fetch DHIS2 data.")
        }), 500

    # --- Load CSV to DataFrame ---
    csv_path = result.get("csv_file")
    df_raw = load_dhis2_csv_to_df(csv_file=csv_path)
    df_agg = aggregate_dhis2_data(df_raw)
    #db_data = get_db_used_totals_with_keys(start_date, end_date)
    # Filter by transaction type and product name
    db_data = get_db_used_totals_with_keys(
        start_date, end_date,
        transaction_types=["Issued", "Adjusted"],
        product_names=["Determine", "Unigold", "Stat Pak"]
    )

    # --- Merge DHIS2 with DB data ---
    merged_df = merge_db_and_dhis2(db_data, df_agg)

    # --- Save merged CSV for download ---
    merged_csv_filename = f"merged_db_dhis2_{start_date}_to_{end_date}.csv"
    merged_csv_path = os.path.join(EXPORT_DIR, merged_csv_filename)
    merged_df.to_csv(merged_csv_path, index=False)

    # --- Convert merged DataFrame to JSON-safe list ---
    merged_data_json = merged_df.fillna("").to_dict(orient="records")

    # --- Return only merged data ---
    return jsonify({
        "status": "success",
        "csv_file": merged_csv_filename,
        "columns": list(merged_df.columns),
        "rows": len(merged_df),
        "data": merged_data_json
    })
    
@dhis2api_bp.route('/csv/<path:filename>')
def download_csv(filename):
    """Serve CSV files from the dhis2downloads folder."""
    file_path = os.path.join(EXPORT_DIR, filename)
    if not os.path.exists(file_path):
        return jsonify({"status": "error", "message": f"File not found: {filename}"}), 404
    return send_from_directory(EXPORT_DIR, filename, as_attachment=True)