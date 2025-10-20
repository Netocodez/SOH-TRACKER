from flask import Blueprint, render_template, send_file, request, redirect, flash, url_for, current_app
import os
import sqlite3
import shutil
from werkzeug.utils import secure_filename

#backup_bp = Blueprint("backup", __name__)
backup_bp = Blueprint('backup', __name__, url_prefix='/backup')

def get_db_path():
    """Return the correct database path depending on environment."""
    if os.getenv("RENDER") == "true" or os.getenv("RENDER_INTERNAL_HOSTNAME"):
        db_dir = "/data"
    else:
        db_dir = current_app.instance_path

    os.makedirs(db_dir, exist_ok=True)
    return os.path.join(db_dir, "stock.db")


@backup_bp.route("/", methods=["GET"])
def backup_page():
    return render_template("backup.html")

@backup_bp.route("/export", methods=["GET"])
def export_db():
    #db_path = os.path.join(current_app.instance_path, "stock.db")
    db_path = get_db_path()
    
    if not os.path.exists(db_path):
        return "Database not found", 404
    
    return send_file(db_path, as_attachment=True, download_name="stock_backup.db")

@backup_bp.route('/import', methods=['GET', 'POST'])
def import_backup():
    if request.method == 'POST':
        file = request.files['file']
        if file and file.filename.endswith('.db'):
            temp_path = os.path.join(current_app.instance_path, 'temp_import.db')
            file.save(temp_path)

            live_db_path = get_db_path()

            try:
                # Open connections
                source_conn = sqlite3.connect(temp_path)
                dest_conn = sqlite3.connect(live_db_path)

                source_cursor = source_conn.cursor()
                dest_cursor = dest_conn.cursor()

                # Disable foreign key checks
                dest_cursor.execute('PRAGMA foreign_keys = OFF')

                # Get all table names
                source_cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
                tables = source_cursor.fetchall()

                for (table_name,) in tables:
                    if table_name.startswith("sqlite_"):
                        continue  # skip internal SQLite tables

                    # Optional: Clear existing data
                    dest_cursor.execute(f'DELETE FROM {table_name}')

                    # Copy data
                    rows = source_cursor.execute(f'SELECT * FROM {table_name}').fetchall()
                    if rows:
                        # Get column count
                        columns = [desc[0] for desc in source_cursor.description]
                        placeholders = ','.join(['?'] * len(columns))
                        dest_cursor.executemany(
                            f'INSERT INTO {table_name} ({",".join(columns)}) VALUES ({placeholders})',
                            rows
                        )

                dest_conn.commit()
                flash("Backup imported successfully", "success")
            except Exception as e:
                flash(f"Import failed: {e}", "danger")
            finally:
                source_conn.close()
                dest_conn.close()
                os.remove(temp_path)

            return redirect(url_for('backup.import_backup'))

    return render_template('backup.html')

