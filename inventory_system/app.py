# app.py
import os
import re
import sys
import io
import json
import datetime
from datetime import timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, session, flash, jsonify, url_for, send_file, abort, send_from_directory
import mysql.connector
from werkzeug.security import generate_password_hash, check_password_hash
import pandas as pd
from io import BytesIO, StringIO
from werkzeug.utils import secure_filename

# Ensure UTF-8 stdout in some Windows environments
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# ---------------------------
# Flask app setup
# ---------------------------
app = Flask(__name__, template_folder='templates')
app.secret_key = os.getenv("FLASK_SECRET", "change_this_in_prod")
app.permanent_session_lifetime = timedelta(hours=2)

# Upload folder setup
UPLOAD_FOLDER = 'uploads/invoices'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ---------------------------
# Database connection
# ---------------------------
def get_db_connection():
    try:
        conn = mysql.connector.connect(
            host=os.getenv("DB_HOST", "localhost"),
            user=os.getenv("DB_USER", "root"),
            password=os.getenv("DB_PASS", "Root@123"),
            database=os.getenv("DB_NAME", "botbruz_inventory")
        )
        return conn
    except mysql.connector.Error as err:
        print(f"Database connection error: {err}")
        return None

# ---------------------------
# Database initialization
# ---------------------------
def init_database():
    conn = get_db_connection()
    if not conn:
        print("Could not connect to database!")
        return False
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS components (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            sku VARCHAR(100) DEFAULT NULL,
            quantity INT NOT NULL DEFAULT 0,
            unit_price DECIMAL(10,2) NOT NULL,
            gst_applicable TINYINT(1) DEFAULT 0,
            gst_percent DECIMAL(5,2) DEFAULT 0.00,
            gst_value DECIMAL(10,2) DEFAULT 0.00,
            ordered_by VARCHAR(255) DEFAULT NULL,
            category VARCHAR(50) DEFAULT 'Electronics',
            date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            invoice_file TEXT DEFAULT NULL,
            INDEX idx_name (name),
            INDEX idx_sku (sku),
            INDEX idx_date (date_added)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS admin_users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(50) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("SELECT COUNT(*) as cnt FROM admin_users WHERE username='admin'")
    if cursor.fetchone()["cnt"] == 0:
        default_password = generate_password_hash('admin123')
        cursor.execute("INSERT INTO admin_users (username, password_hash) VALUES (%s, %s)", ('admin', default_password))
        print("✅ Default admin user created: admin / admin123")
    conn.commit()
    conn.close()
    print("✅ Database initialized & migrated successfully!")
    return True

# ---------------------------
# Login required decorator
# ---------------------------
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to access this page.", "error")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

# ---------------------------
# Login/logout routes
# ---------------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        conn = get_db_connection()
        if conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT id, password_hash FROM admin_users WHERE username=%s", (username,))
            user = cursor.fetchone()
            conn.close()
            if user and check_password_hash(user['password_hash'], password):
                session.permanent = True
                session['user_id'] = user['id']
                session['username'] = username
                flash('Login successful!', 'success')
                return redirect(url_for('dashboard'))
            else:
                flash('Invalid username or password!', 'error')
        else:
            flash('Database connection error!', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

# ---------------------------
# Dashboard
# ---------------------------
@app.route('/')
@login_required
def dashboard():
    conn = get_db_connection()
    if not conn:
        flash('Database connection error!', 'error')
        return render_template('dashboard.html', stats={})
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT COUNT(*) as cnt FROM components")
    total_components = cursor.fetchone()["cnt"] or 0
    cursor.execute("SELECT SUM(quantity) as qty FROM components")
    total_quantity = cursor.fetchone()["qty"] or 0
    cursor.execute("SELECT SUM(quantity * unit_price) as amt FROM components")
    total_amount = cursor.fetchone()["amt"] or 0.0
    cursor.execute("SELECT SUM(gst_value) as gst FROM components")
    total_gst = cursor.fetchone()["gst"] or 0.0
    cursor.execute("SELECT id, name, quantity, unit_price, gst_value, date_added FROM components ORDER BY date_added DESC LIMIT 5")
    recent_data = cursor.fetchall()
    conn.close()

    recent_entries = []
    for row in recent_data:
        unit_price = float(row['unit_price'])
        quantity = row['quantity']
        gst_value = float(row['gst_value']) if row['gst_value'] else 0.0
        total = (unit_price * quantity) + gst_value
        recent_entries.append({
            'id': row['id'],
            'name': row['name'],
            'unit_price': unit_price,
            'quantity': quantity,
            'gst_value': gst_value,
            'total': total,
            'date_added': row['date_added']
        })

    stats = {
        'total_components': total_components,
        'total_quantity': total_quantity,
        'total_amount': float(total_amount),
        'total_value': float(total_amount),
        'total_gst': float(total_gst),
        'total_entries': total_components,
        'recent_entries': recent_entries,
    }
    return render_template('dashboard.html', stats=stats)

# ---------------------------
# Inventory route
# ---------------------------
@app.route('/inventory')
@login_required
def inventory():
    search = request.args.get('search', '').strip()
    sort_by = request.args.get('sort', 'date_added')
    order = request.args.get('order', 'desc')
    gst_filter = request.args.get('gst_filter', 'all')
    category_filter = request.args.get('category', 'all')

    valid_sort_columns = ['id', 'name', 'sku', 'quantity', 'unit_price', 'date_added']
    if sort_by not in valid_sort_columns:
        sort_by = 'date_added'
    if order not in ['asc', 'desc']:
        order = 'desc'

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    query = "SELECT * FROM components WHERE 1=1"
    params = []

    if search:
        query += " AND (name LIKE %s OR sku LIKE %s)"
        params.extend([f"%{search}%", f"%{search}%"])

    if gst_filter == 'with':
        query += " AND gst_applicable = 1"
    elif gst_filter == 'without':
        query += " AND (gst_applicable = 0 OR gst_applicable IS NULL)"

    if category_filter in ['Hardware', 'Electronics']:
        query += " AND category = %s"
        params.append(category_filter)

    query += f" ORDER BY {sort_by} {order}"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    components = []
    total_value = 0.0
    for row in rows:
        qty = float(row['quantity']) if row['quantity'] else 0.0
        unit_price = float(row['unit_price']) if row['unit_price'] else 0.0
        gst_value = float(row['gst_value']) if row['gst_value'] else 0.0
        total = (qty * unit_price) + gst_value
        total_value += total

        components.append({
            'id': row['id'],
            'name': row['name'],
            'sku': row['sku'] or '-',
            'quantity': int(qty),
            'unit_price': unit_price,
            'gst_applicable': bool(row['gst_applicable']),
            'gst_percent': float(row['gst_percent'] or 0),
            'gst_value': gst_value,
            'total_value': total,
            'ordered_by': row.get('ordered_by'),
            'date_added': row['date_added'],
            'invoice_file': row.get('invoice_file')
        })

    return render_template(
        'inventory.html',
        components=components,
        search=search,
        sort_by=sort_by,
        order=order,
        gst_filter=gst_filter,
        category_filter=category_filter,
        total_value=total_value
    )

# ---------------------------
# Add Components
# ---------------------------
@app.route('/add-components', methods=['GET', 'POST'])
@login_required
def add_components():
    if request.method == 'POST':
        method = request.form.get('method')
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            if method == "manual":
                name = request.form['name'].strip()
                quantity = int(request.form['quantity'])
                unit_price = float(request.form['unit_price'])
                gst_applicable = 1 if request.form.get("gst_applicable") else 0
                gst_percent = float(request.form.get("gst_percent", 0.0)) if gst_applicable else 0.0
                gst_value = round((quantity * unit_price) * (gst_percent / 100), 2) if gst_applicable else 0.0
                category = request.form.get("category", "Electronics").strip()
                ordered_by = request.form.get("ordered_by", "").strip()
                sku = request.form.get("sku", "").strip() or re.sub(r'[^A-Za-z0-9]+', '_', name).lower()[:15]

                invoice_file = None
                if 'invoice_file' in request.files:
                    file = request.files['invoice_file']
                    if file and allowed_file(file.filename):
                        filename = secure_filename(file.filename)
                        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                        invoice_file = filename

                cursor.execute("SELECT id, quantity FROM components WHERE sku=%s", (sku,))
                existing = cursor.fetchone()
                if existing:
                    new_qty = existing['quantity'] + quantity
                    cursor.execute("""
                        UPDATE components
                        SET quantity=%s, unit_price=%s, gst_applicable=%s, gst_percent=%s,
                            gst_value=%s, ordered_by=%s, category=%s, invoice_file=%s
                        WHERE id=%s
                    """, (new_qty, unit_price, gst_applicable, gst_percent, gst_value, ordered_by, category, invoice_file, existing['id']))
                else:
                    cursor.execute("""
                        INSERT INTO components
                        (name, sku, quantity, unit_price, gst_applicable, gst_percent, gst_value, ordered_by, category, invoice_file)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (name, sku, quantity, unit_price, gst_applicable, gst_percent, gst_value, ordered_by, category, invoice_file))
                conn.commit()

            elif method == "invoice":
                invoice_text = request.form.get("items_json", "").strip()
                gst_applicable = 1 if request.form.get("gst_applicable") else 0
                gst_percent = float(request.form.get("gst_percent", 0.0)) if gst_applicable else 0.0
                ordered_by = request.form.get("ordered_by", "").strip()
                category = request.form.get("category", "Electronics").strip()
                sku_input = request.form.get("sku", "").strip()

                invoice_file = None
                if 'invoice' in request.files:
                    file = request.files['invoice']
                    if file and allowed_file(file.filename):
                        filename = secure_filename(file.filename)
                        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                        invoice_file = filename

                if not invoice_text:
                    conn.close()
                    return "No invoice data provided", 400

                parsed_items = {}
                for line in invoice_text.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        price_match = re.search(r"[₹$]\s*([\d,]+(?:\.\d+)?)", line)
                        price = float(price_match.group(1).replace(",", "")) if price_match else 0.0

                        qty = 1
                        qty_match = None
                        if price_match:
                            before_price = line[:price_match.start()]
                            qty_match = re.search(r"(\d+)\s*$", before_price)
                            if qty_match:
                                qty = int(qty_match.group(1))

                        name = line[:price_match.start()].strip() if price_match else line
                        if qty_match:
                            name = name[:qty_match.start()].strip()
                        if not name:
                            name = "Unknown Item"

                        sku = sku_input or re.sub(r'[^A-Za-z0-9]+', '_', name).lower()[:15]

                        gst_value = round((qty * price * (gst_percent / 100)), 2) if gst_applicable else 0.0
                        total_value = round((qty * price) + gst_value, 2)

                        if sku in parsed_items:
                            parsed_items[sku]['qty'] += qty
                            parsed_items[sku]['total_value'] += total_value
                            parsed_items[sku]['gst_value'] += gst_value
                        else:
                            parsed_items[sku] = {
                                'name': name,
                                'sku': sku,
                                'qty': qty,
                                'price': price,
                                'gst_applicable': gst_applicable,
                                'gst_percent': gst_percent,
                                'gst_value': gst_value,
                                'total_value': total_value,
                                'ordered_by': ordered_by,
                                'category': category,
                                'invoice_file': invoice_file
                            }

                    except Exception as e:
                        print(f"❌ Could not parse line: {line} → {e}")

                for sku, item in parsed_items.items():
                    cursor.execute("SELECT id, quantity FROM components WHERE sku=%s", (sku,))
                    existing = cursor.fetchone()
                    if existing:
                        new_qty = existing['quantity'] + item['qty']
                        cursor.execute("""
                            UPDATE components
                            SET quantity=%s, unit_price=%s, gst_applicable=%s, gst_percent=%s,
                                gst_value=%s, ordered_by=%s, category=%s, invoice_file=%s
                            WHERE id=%s
                        """, (new_qty, item['price'], item['gst_applicable'], item['gst_percent'],
                              item['gst_value'], item['ordered_by'], item['category'], item['invoice_file'], existing['id']))
                    else:
                        cursor.execute("""
                            INSERT INTO components
                            (name, sku, quantity, unit_price, gst_applicable, gst_percent, gst_value, ordered_by, category, invoice_file)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, (item['name'], item['sku'], item['qty'], item['price'], item['gst_applicable'],
                              item['gst_percent'], item['gst_value'], item['ordered_by'], item['category'], item['invoice_file']))
                conn.commit()

        except Exception as e:
            print(f"❌ Error saving components: {e}")
            conn.rollback()
            conn.close()
            return f"Error: {e}", 500

        conn.close()
        return redirect(url_for('inventory'))

    return render_template('add_components.html')


# ---------------------------
# parse invoice API
# ---------------------------
# ---------------------------
# Parse invoice API
# ---------------------------
@app.route('/api/parse-invoice', methods=['POST'])
@login_required
def api_parse_invoice():
    try:
        invoice_text = request.form.get("invoice_text", "").strip()
        gst_flag = request.form.get("gst_applicable", "0").strip()
        ordered_by = request.form.get("ordered_by", "").strip()

        invoice_file = None
        if 'invoice_file' in request.files:
            file = request.files['invoice_file']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                invoice_file = filename

        if not invoice_text and not invoice_file:
            return jsonify({"success": False, "error": "No invoice text or file provided"}), 400

        gst_applicable = 1 if str(gst_flag).lower() in ("1", "true", "yes", "on") else 0
        gst_percent = 18.0 if gst_applicable else 0.0

        parsed_items = {}

        for line in invoice_text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                price_match = re.search(r"[₹$]?\s*([\d,]+(?:\.\d+)?)", line)
                qty_match = re.search(r"\bquantity\s*(\d+)\b", line, re.IGNORECASE)

                if price_match:
                    price = float(price_match.group(1).replace(",", ""))
                else:
                    raise ValueError("Price not found in line")

                qty = int(qty_match.group(1)) if qty_match else 1

                if qty_match:
                    name = line[:qty_match.start()].strip()
                else:
                    name = line[:price_match.start()].strip()

                if not name:
                    name = "Unknown Item"

                sku = re.sub(r'[^A-Za-z0-9]+', '_', name).lower()[:15]

                gst_value = (qty * price * gst_percent / 100) if gst_applicable else 0.0
                total_value = (qty * price) + gst_value

                if sku in parsed_items:
                    parsed_items[sku]['qty'] += qty
                    parsed_items[sku]['gst_value'] += gst_value
                    parsed_items[sku]['total_value'] += total_value
                else:
                    parsed_items[sku] = {
                        "name": name,
                        "sku": sku,
                        "qty": qty,
                        "price": price,
                        "gst_applicable": gst_applicable,
                        "gst_percent": gst_percent,
                        "gst_value": round(gst_value, 2),
                        "total_value": round(total_value, 2),
                        "ordered_by": ordered_by,
                        "invoice_file": invoice_file
                    }

            except Exception as e:
                print(f"❌ Could not parse line: {line} → {e}")

        if not parsed_items:
            return jsonify({"success": False, "error": "No valid items parsed"}), 400

        return jsonify({"success": True, "items": list(parsed_items.values())})

    except Exception as e:
        print(f"❌ Invoice parsing failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ---------------------------
# Edit component
# ---------------------------
@app.route('/edit-component/<int:component_id>', methods=['GET', 'POST'])
@login_required
def edit_component(component_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    if request.method == 'POST':
        try:
            name = request.form['component_name'].strip()
            quantity = int(request.form['quantity'])
            unit_price = float(request.form['unit_price'])
            cursor.execute("UPDATE components SET name=%s, quantity=%s, unit_price=%s WHERE id=%s",
                           (name, quantity, unit_price, component_id))
            conn.commit()
            conn.close()
            flash('Component updated successfully!', 'success')
            return redirect(url_for('inventory'))
        except Exception as e:
            flash(f"Error updating component: {e}", "error")
    cursor.execute("SELECT id, name, quantity, unit_price FROM components WHERE id=%s", (component_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        flash('Component not found!', 'error')
        return redirect(url_for('inventory'))
    component = {'id': row['id'], 'name': row['name'], 'quantity': row['quantity'], 'unit_price': float(row['unit_price'])}
    return render_template('edit_component.html', component=component)

# ---------------------------
# Delete component
# ---------------------------
@app.route('/delete-component/<int:component_id>')
@login_required
def delete_component(component_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM components WHERE id=%s", (component_id,))
    conn.commit()
    conn.close()
    flash('Component deleted successfully!', 'success')
    return redirect(url_for('inventory'))

# ---------------------------
# Export inventory
# ---------------------------
def fetch_inventory_df(category=None):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    query = """
        SELECT id, name, sku, quantity, unit_price, gst_applicable, 
               gst_percent, gst_value, ordered_by, date_added, category
        FROM components
        WHERE 1=1
    """
    params = []
    if category:
        query += " AND category=%s"
        params.append(category)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return pd.DataFrame(rows)

def make_filename(base, ext):
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{base}_{timestamp}.{ext}"

def export_inventory_file(format="csv", category=None, include_gst=True):
    df = fetch_inventory_df(category=category)
    if df.empty:
        return None

    if include_gst and format=="xlsx":
        df['price_with_gst'] = (df['quantity'] * df['unit_price']) + df['gst_value']

    if format == "csv":
        if not include_gst:
            df = df.drop(columns=['gst_applicable', 'gst_percent', 'gst_value'], errors='ignore')
        csv_buf = StringIO()
        df.to_csv(csv_buf, index=False)
        mem = BytesIO(csv_buf.getvalue().encode('utf-8'))
        return mem
    elif format == "xlsx":
        output = BytesIO()
        df.to_excel(output, index=False, engine='openpyxl')
        output.seek(0)
        return output

@app.route('/export/<string:file_type>')
@login_required
def export_file(file_type):
    if file_type == "with_gst":
        file = export_inventory_file(format="xlsx", include_gst=True)
        name = make_filename("inventory_with_gst", "xlsx")
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif file_type == "without_gst":
        file = export_inventory_file(format="csv", include_gst=False)
        name = make_filename("inventory_without_gst", "csv")
        mimetype="text/csv"
    elif file_type in ["electronics", "hardware", "all"]:
        category = None if file_type=="all" else file_type.capitalize()
        file = export_inventory_file(format="csv", category=category)
        name = make_filename(f"inventory_{file_type}", "csv")
        mimetype="text/csv"
    else:
        flash("Invalid export type", "error")
        return redirect(url_for("inventory"))

    if not file:
        flash("No data to export", "error")
        return redirect(url_for("inventory"))

    return send_file(file, as_attachment=True, download_name=name, mimetype=mimetype)

# ---------------------------
# Delete all components
# ---------------------------
DELETE_PIN = "botbruz@123"

@app.route('/delete-all', methods=['POST', 'GET'])
@login_required
def delete_all_components():
    if request.method == 'POST':
        entered_pin = request.form.get('pin', '').strip()
        if entered_pin == DELETE_PIN:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM components")
            conn.commit()
            conn.close()
            flash("✅ All components deleted successfully!", "success")
            return redirect(url_for("inventory"))
        else:
            flash("❌ Incorrect PIN! Components not deleted.", "error")
            return redirect(url_for("inventory"))
    return render_template("delete_all_pin.html")

# ---------------------------
# View invoice
# ---------------------------
@app.route('/view_invoice/<filename>')
@login_required
def view_invoice(filename):
    invoice_folder = app.config['UPLOAD_FOLDER']
    if not os.path.exists(os.path.join(invoice_folder, filename)):
        flash(f"Invoice '{filename}' not found on server.", "danger")
        return redirect(request.referrer)
    return send_from_directory(invoice_folder, filename)


# ---------------------------
# Run the app
# ---------------------------
if __name__ == "__main__":
    if init_database():
        print("Starting app...")
        app.run(debug=True, host='0.0.0.0', port=5000)
    else:
        print("Failed to initialize database")
