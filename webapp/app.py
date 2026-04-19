#!/usr/bin/env python3
"""
Orange Bike Brewing — Production Web Application
Read-only data browser for ALY 6080 class members.
Deployed at crowdsaasing.com/orangebike via k8s + Cloudflare Tunnel.
"""

import sqlite3
import os
import io
import csv
import json
import base64
import zipfile
import shutil
from datetime import datetime, date
from pathlib import Path
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, jsonify, g, send_from_directory, Response, session,
    send_file, abort
)
from werkzeug.middleware.proxy_fix import ProxyFix

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False


# ── Configuration ──────────────────────────────────────────────────

APP_ROOT = Path(__file__).parent
DB_BUNDLED = APP_ROOT.parent / "orange_bike.db"   # baked into the image
DB_RUNTIME_DIR = Path(os.environ.get("DB_DIR", str(APP_ROOT.parent)))
DB_PATH = DB_RUNTIME_DIR / "orange_bike.db"

UPLOADS_DIR = Path(os.environ.get("UPLOADS_DIR", str(APP_ROOT / "uploads")))

READ_ONLY = os.environ.get("READ_ONLY", "false").lower() in ("true", "1", "yes")
OBB_PASSWORD = os.environ.get("OBB_PASSWORD", "")
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-in-production")
SESSION_HOURS = int(os.environ.get("SESSION_HOURS", "12"))


# ── App ────────────────────────────────────────────────────────────

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["PERMANENT_SESSION_LIFETIME"] = SESSION_HOURS * 3600

# Trust Cloudflare Tunnel + Ingress forwarded headers
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1, x_prefix=1)


# Expose flags + prefix to all templates
@app.context_processor
def inject_globals():
    return {
        "READ_ONLY": READ_ONLY,
        "URL_PREFIX": request.script_root if request else "",
        "authenticated": session.get("authenticated", False),
    }


# ── Database bootstrap ─────────────────────────────────────────────

def init_runtime_db():
    """On first boot with a PVC, copy the bundled DB if the runtime DB is missing."""
    DB_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    if not DB_PATH.exists() and DB_BUNDLED.exists() and str(DB_BUNDLED) != str(DB_PATH):
        print(f"Initializing runtime DB: copying {DB_BUNDLED} -> {DB_PATH}")
        shutil.copy2(DB_BUNDLED, DB_PATH)
    elif not DB_PATH.exists():
        print(f"WARNING: No database found at {DB_PATH} and no bundled DB at {DB_BUNDLED}")


def ensure_suggestions_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT,
            page_context TEXT,
            suggestion_text TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()


def ensure_shelf_scans_tables(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS shelf_scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_date TEXT NOT NULL,
            account_name TEXT,
            location_note TEXT,
            photo_filename TEXT,
            ai_raw_response TEXT,
            products_json TEXT,
            total_facings INTEGER,
            stock_level TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS shelf_scan_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_id INTEGER NOT NULL,
            style_name TEXT NOT NULL,
            estimated_count INTEGER,
            confidence TEXT,
            notes TEXT,
            FOREIGN KEY (scan_id) REFERENCES shelf_scans(id)
        )
    """)
    conn.commit()


def bootstrap():
    """Run once at app startup."""
    init_runtime_db()
    if DB_PATH.exists():
        conn = sqlite3.connect(str(DB_PATH))
        ensure_suggestions_table(conn)
        ensure_shelf_scans_tables(conn)
        conn.close()


bootstrap()


# ── Database helpers ───────────────────────────────────────────────

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(str(DB_PATH))
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    return (rv[0] if rv else None) if one else rv


# ── Auth ───────────────────────────────────────────────────────────

def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapper


def require_write(f):
    """Decorate POST handlers that mutate data. Blocked in READ_ONLY."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if READ_ONLY and request.method == "POST":
            if request.is_json or request.path.startswith("/api/"):
                return jsonify({"error": "This deployment is read-only"}), 403
            flash("This deployment is read-only. Use Suggestions to propose changes, or download the database.", "error")
            return redirect(url_for("suggestions_view"))
        return f(*args, **kwargs)
    return wrapper


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("authenticated"):
        return redirect(url_for("dashboard"))

    error = None
    if request.method == "POST":
        pw = request.form.get("password", "").strip()
        if not OBB_PASSWORD:
            error = "Server is misconfigured: OBB_PASSWORD not set."
        elif pw == OBB_PASSWORD:
            session["authenticated"] = True
            session.permanent = True
            next_url = request.args.get("next") or request.form.get("next") or url_for("dashboard")
            # Guard against open-redirect
            if not next_url.startswith("/"):
                next_url = url_for("dashboard")
            return redirect(next_url)
        else:
            error = "Incorrect password."

    return render_template("login.html", error=error, next_url=request.args.get("next", ""))


@app.route("/logout")
def logout():
    session.clear()
    flash("Signed out.", "success")
    return redirect(url_for("login"))


@app.route("/health")
def health():
    """Unauthenticated liveness probe."""
    try:
        db = sqlite3.connect(str(DB_PATH))
        db.execute("SELECT 1").fetchone()
        db.close()
        return jsonify({"ok": True, "read_only": READ_ONLY})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ── Routes: Dashboard ──────────────────────────────────────────────

@app.route("/")
@require_auth
def dashboard():
    db = get_db()
    metrics = {}

    row = db.execute("SELECT COUNT(*) FROM accounts").fetchone()
    metrics["total_accounts"] = row[0]

    row = db.execute("SELECT COUNT(*), ROUND(SUM(net_sales),2) FROM taproom_transactions").fetchone()
    metrics["total_taproom_txns"] = f"{row[0]:,}"
    metrics["total_taproom_sales"] = f"${row[1]:,.2f}" if row[1] else "$0"

    metrics["annual_totals"] = db.execute("""
        SELECT year, ROUND(value, 2) as total FROM sales_summary_annual
        WHERE metric = 'Net Total' ORDER BY year
    """).fetchall()

    metrics["top_styles"] = db.execute("""
        SELECT style_name, ROUND(SUM(cases), 1) as total_cases
        FROM can_sales_weekly GROUP BY style_name
        ORDER BY total_cases DESC LIMIT 10
    """).fetchall()

    metrics["top_accounts"] = db.execute("""
        SELECT account_name, COUNT(*) as order_lines,
               ROUND(SUM(quantity), 1) as total_qty
        FROM wholesale_orders GROUP BY account_name
        ORDER BY total_qty DESC LIMIT 10
    """).fetchall()

    metrics["category_sales"] = db.execute("""
        SELECT category, ROUND(net_sales, 2) as net
        FROM category_sales_annual
        WHERE year = (SELECT MAX(year) FROM category_sales_annual)
        ORDER BY net_sales DESC
    """).fetchall()

    metrics["recent_orders"] = db.execute("""
        SELECT invoice_num, account_name, sku_name, quantity, week_date
        FROM wholesale_orders
        ORDER BY week_date DESC, invoice_num DESC LIMIT 15
    """).fetchall()

    return render_template("dashboard.html", metrics=metrics)


# ── Routes: Wholesale Orders ───────────────────────────────────────

@app.route("/orders")
@require_auth
def orders_list():
    orders = query_db("""
        SELECT id, invoice_num, account_name, sku_name, quantity, week_date, month
        FROM wholesale_orders
        ORDER BY week_date DESC, invoice_num DESC
    """)
    return render_template("orders.html", orders=orders)


@app.route("/orders/new", methods=["GET", "POST"])
@require_auth
@require_write
def order_new():
    db = get_db()

    if request.method == "POST":
        invoice_num = request.form.get("invoice_num", "").strip()
        account_name = request.form.get("account_name", "").strip()
        week_date = request.form.get("week_date", "").strip()
        month = request.form.get("month", "").strip()

        styles = db.execute("SELECT style_name FROM beer_styles ORDER BY style_name").fetchall()
        inserted = 0
        for style in styles:
            qty = request.form.get(f"qty_{style['style_name']}", "").strip()
            if qty and float(qty) > 0:
                db.execute(
                    """INSERT INTO wholesale_orders
                       (invoice_num, account_name, sku_name, quantity, week_date, month)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (invoice_num, account_name, style["style_name"],
                     float(qty), week_date, int(month) if month else None),
                )
                inserted += 1

        db.commit()
        flash(f"Order saved: {inserted} line items for {account_name}", "success")
        return redirect(url_for("orders_list"))

    accounts = db.execute("SELECT account_name FROM accounts ORDER BY account_name").fetchall()
    styles = db.execute("SELECT style_name, format, category FROM beer_styles ORDER BY style_name").fetchall()
    today = date.today().isoformat()
    return render_template("order_form.html", accounts=accounts, styles=styles, today=today)


# ── Routes: Inventory ──────────────────────────────────────────────

@app.route("/inventory")
@require_auth
def inventory_view():
    data = query_db("""
        SELECT year, week_date, style_name, channel,
               ROUND(SUM(cases), 1) as total_cases
        FROM can_sales_weekly
        GROUP BY year, week_date, style_name, channel
        ORDER BY week_date DESC, style_name LIMIT 200
    """)
    return render_template("inventory.html", data=data)


@app.route("/inventory/new", methods=["GET", "POST"])
@require_auth
@require_write
def inventory_new():
    db = get_db()

    if request.method == "POST":
        week_date = request.form.get("week_date", "").strip()
        year = int(week_date[:4]) if week_date else date.today().year
        styles = db.execute("SELECT style_name FROM beer_styles ORDER BY style_name").fetchall()
        inserted = 0
        for style in styles:
            for channel in ["TR", "Distro", "Other"]:
                qty = request.form.get(f"qty_{style['style_name']}_{channel}", "").strip()
                if qty and float(qty) > 0:
                    db.execute(
                        """INSERT INTO can_sales_weekly
                           (year, week_date, style_name, channel, cases)
                           VALUES (?, ?, ?, ?, ?)""",
                        (year, week_date, style["style_name"], channel, float(qty)),
                    )
                    inserted += 1

        db.commit()
        flash(f"Inventory saved: {inserted} entries for week of {week_date}", "success")
        return redirect(url_for("inventory_view"))

    styles = db.execute("SELECT style_name, format, category FROM beer_styles ORDER BY style_name").fetchall()
    today = date.today().isoformat()
    return render_template("inventory_form.html", styles=styles, today=today)


# ── Routes: Accounts ───────────────────────────────────────────────

@app.route("/accounts")
@require_auth
def accounts_list():
    accounts = query_db("""
        SELECT a.*,
               (SELECT COUNT(*) FROM wholesale_orders w
                WHERE w.account_name = a.account_name) as order_count,
               (SELECT ROUND(SUM(w.quantity), 1) FROM wholesale_orders w
                WHERE w.account_name = a.account_name) as total_qty
        FROM accounts a ORDER BY a.account_name
    """)
    return render_template("accounts.html", accounts=accounts)


@app.route("/accounts/new", methods=["GET", "POST"])
@require_auth
@require_write
def account_new():
    if request.method == "POST":
        db = get_db()
        db.execute(
            """INSERT INTO accounts
               (account_name, territory, address, city, email, phone,
                buyer_name, pay_method, delivery_instructions, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                request.form.get("account_name", "").strip(),
                request.form.get("territory", "").strip() or None,
                request.form.get("address", "").strip() or None,
                request.form.get("city", "").strip() or None,
                request.form.get("email", "").strip() or None,
                request.form.get("phone", "").strip() or None,
                request.form.get("buyer_name", "").strip() or None,
                request.form.get("pay_method", "").strip() or None,
                request.form.get("delivery_instructions", "").strip() or None,
                request.form.get("notes", "").strip() or None,
            ),
        )
        db.commit()
        flash("Account added successfully", "success")
        return redirect(url_for("accounts_list"))

    return render_template("account_form.html")


# ── Routes: Browse / SQL Console ───────────────────────────────────

def get_table_list():
    db = get_db()
    tables = db.execute(
        """SELECT name FROM sqlite_master
           WHERE type='table' AND name NOT LIKE 'sqlite_%'
           ORDER BY name"""
    ).fetchall()
    result = []
    for (name,) in tables:
        count = db.execute(f"SELECT COUNT(*) FROM [{name}]").fetchone()[0]
        result.append({"name": name, "rows": count})
    return result


@app.route("/browse")
@require_auth
def browse():
    tables = get_table_list()
    return render_template("browse.html", tables=tables)


@app.route("/api/browse/tables")
@require_auth
def api_browse_tables():
    db = get_db()
    tables = get_table_list()
    for t in tables:
        cols = db.execute(f"PRAGMA table_info([{t['name']}])").fetchall()
        t["columns"] = [{"name": c[1], "type": c[2]} for c in cols]
    return jsonify(tables)


@app.route("/api/browse/<table_name>")
@require_auth
def api_browse_table(table_name):
    db = get_db()
    valid_tables = [t["name"] for t in get_table_list()]
    if table_name not in valid_tables:
        return jsonify({"error": "Invalid table name"}), 400

    cols = db.execute(f"PRAGMA table_info([{table_name}])").fetchall()
    col_names = [c[1] for c in cols]
    col_types = {c[1]: c[2] for c in cols}

    page = max(1, int(request.args.get("page", 1)))
    per_page = min(200, max(10, int(request.args.get("per_page", 50))))
    sort_col = request.args.get("sort", col_names[0] if col_names else "rowid")
    sort_order = "DESC" if request.args.get("order", "asc").lower() == "desc" else "ASC"
    search = request.args.get("search", "").strip()

    if sort_col not in col_names:
        sort_col = col_names[0] if col_names else "rowid"

    if search:
        conditions = " OR ".join(f"CAST([{c}] AS TEXT) LIKE ?" for c in col_names)
        where_clause = f"WHERE ({conditions})"
        params = [f"%{search}%"] * len(col_names)
    else:
        where_clause = ""
        params = []

    total = db.execute(f"SELECT COUNT(*) FROM [{table_name}] {where_clause}", params).fetchone()[0]

    offset = (page - 1) * per_page
    data_sql = f"""
        SELECT * FROM [{table_name}] {where_clause}
        ORDER BY [{sort_col}] {sort_order} LIMIT ? OFFSET ?
    """
    rows = db.execute(data_sql, params + [per_page, offset]).fetchall()

    return jsonify({
        "table": table_name,
        "columns": [{"name": c, "type": col_types.get(c, "")} for c in col_names],
        "rows": [list(r) for r in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
        "sort": sort_col,
        "order": sort_order.lower(),
    })


@app.route("/api/query", methods=["POST"])
@require_auth
def api_run_query():
    data = request.get_json()
    sql = (data or {}).get("sql", "").strip()

    if not sql:
        return jsonify({"error": "No SQL provided"}), 400

    sql_upper = sql.upper().lstrip()
    if not any(sql_upper.startswith(s) for s in ("SELECT", "PRAGMA", "EXPLAIN", "WITH")):
        return jsonify({"error": "Only SELECT queries are allowed"}), 403

    for kw in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
               "ATTACH", "DETACH", "REPLACE", "VACUUM"):
        if kw in sql_upper:
            return jsonify({"error": f"'{kw}' is not allowed in queries"}), 403

    db = get_db()
    try:
        cursor = db.execute(sql)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchall()
        truncated = len(rows) > 5000
        if truncated:
            rows = rows[:5000]

        return jsonify({
            "columns": columns,
            "rows": [list(r) for r in rows],
            "row_count": len(rows),
            "truncated": truncated,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/query/csv", methods=["POST"])
@require_auth
def api_query_csv():
    data = request.get_json()
    columns = (data or {}).get("columns", [])
    rows = (data or {}).get("rows", [])

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(columns)
    for row in rows:
        writer.writerow(row)

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=query_result.csv"}
    )


# ── Routes: Suggestions (write-allowed even in read-only) ──────────

@app.route("/suggestions", methods=["GET", "POST"])
@require_auth
def suggestions_view():
    db = get_db()
    if request.method == "POST":
        text = request.form.get("suggestion_text", "").strip()
        if not text:
            flash("Suggestion cannot be empty.", "error")
            return redirect(url_for("suggestions_view"))
        db.execute(
            """INSERT INTO suggestions
               (name, email, page_context, suggestion_text) VALUES (?, ?, ?, ?)""",
            (
                request.form.get("name", "").strip() or None,
                request.form.get("email", "").strip() or None,
                request.form.get("page_context", "").strip() or None,
                text,
            ),
        )
        db.commit()
        flash("Suggestion submitted. Thanks!", "success")
        return redirect(url_for("suggestions_view"))

    recent = db.execute("""
        SELECT id, name, page_context, suggestion_text, created_at
        FROM suggestions ORDER BY created_at DESC LIMIT 50
    """).fetchall()
    return render_template("suggestions.html", recent=recent)


# ── Routes: Export ─────────────────────────────────────────────────

EXPORT_TABLES = [
    ("accounts", "Wholesale account directory"),
    ("beer_styles", "Master beer style list"),
    ("taproom_transactions", "Square POS line items"),
    ("accounting_transactions", "QuickBooks invoice records"),
    ("wholesale_orders", "2026 wholesale orders by SKU"),
    ("can_sales_weekly", "Weekly can sales by style and channel"),
    ("category_sales_annual", "Annual sales by product category"),
    ("sales_summary_annual", "Annual financial summaries"),
]


def table_to_csv_string(db, table_name):
    cursor = db.execute(f"SELECT * FROM [{table_name}]")
    columns = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(columns)
    for row in rows:
        writer.writerow(row)
    return output.getvalue()


@app.route("/export")
@require_auth
def export_page():
    db = get_db()
    tables_info = []
    for table_name, description in EXPORT_TABLES:
        try:
            count = db.execute(f"SELECT COUNT(*) FROM [{table_name}]").fetchone()[0]
            cols = [desc[1] for desc in db.execute(f"PRAGMA table_info([{table_name}])").fetchall()]
            tables_info.append({
                "name": table_name,
                "description": description,
                "rows": count,
                "columns": len(cols),
            })
        except sqlite3.OperationalError:
            pass
    total_rows = sum(t["rows"] for t in tables_info)
    return render_template("export.html", tables=tables_info, total_rows=total_rows)


@app.route("/export/csv/<table_name>")
@require_auth
def export_csv(table_name):
    valid = [t[0] for t in EXPORT_TABLES]
    if table_name not in valid:
        abort(400)
    db = get_db()
    return Response(
        table_to_csv_string(db, table_name),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={table_name}.csv"}
    )


@app.route("/export/zip")
@require_auth
def export_zip():
    db = get_db()
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for table_name, _ in EXPORT_TABLES:
            try:
                count = db.execute(f"SELECT COUNT(*) FROM [{table_name}]").fetchone()[0]
                if count > 0:
                    zf.writestr(f"orange_bike_exports/{table_name}.csv",
                                table_to_csv_string(db, table_name))
            except sqlite3.OperationalError:
                pass
    zip_buffer.seek(0)
    timestamp = datetime.now().strftime("%Y%m%d")
    return Response(
        zip_buffer.getvalue(),
        mimetype="application/zip",
        headers={"Content-Disposition": f"attachment; filename=orange_bike_tableau_{timestamp}.zip"}
    )


@app.route("/download/database")
@require_auth
def download_database():
    """Download the full SQLite database file for offline analysis."""
    if not DB_PATH.exists():
        abort(404)
    return send_file(
        str(DB_PATH),
        as_attachment=True,
        download_name="orange_bike.db",
        mimetype="application/x-sqlite3"
    )


# ── Photo AI (read-only in prod: view only) ────────────────────────

SHELF_ANALYSIS_PROMPT = """You are an inventory analyst for Orange Bike Brewing Company, a dedicated gluten-free craft brewery in Maine.

Analyze this photo of a retail shelf, cooler, or display. Identify and count Orange Bike Brewing products.

Orange Bike products (all 4-pack cans unless noted):
Pilsner, Hazy IPA, WC Pale Ale, ESB, Guava Sour, Stout, Helles Lager,
Summer Ale, Oktoberfest, Winter Lager, Belgian Wit / Spring, Pride Pale Ale, Premium Light.

Respond in EXACTLY this JSON format (no other text):
{
  "orange_bike_found": true or false,
  "products": [{"style": "...", "count": N, "confidence": "high|medium|low", "notes": "..."}],
  "total_facings": N,
  "stock_level": "green|yellow|red",
  "stock_explanation": "...",
  "other_observations": "...",
  "reorder_recommendation": "yes|no|monitor",
  "reorder_explanation": "..."
}

Stock: GREEN 4+ per style, YELLOW 1-3, RED empty/near-empty."""


def analyze_shelf_photo(image_data, media_type):
    if not ANTHROPIC_AVAILABLE:
        return {"error": "Anthropic SDK not available", "orange_bike_found": False,
                "products": [], "total_facings": 0, "stock_level": "red"}
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {"error": "ANTHROPIC_API_KEY not set", "orange_bike_found": False,
                "products": [], "total_facings": 0, "stock_level": "red"}

    client = anthropic.Anthropic(api_key=api_key)
    b64_image = base64.standard_b64encode(image_data).decode("utf-8")
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1500,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64_image}},
                {"type": "text", "text": SHELF_ANALYSIS_PROMPT},
            ],
        }],
    )
    response_text = message.content[0].text.strip()
    if response_text.startswith("```"):
        response_text = response_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        result = json.loads(response_text)
        result["ai_raw"] = response_text
        return result
    except json.JSONDecodeError:
        return {"error": "AI response was not valid JSON", "ai_raw": response_text,
                "orange_bike_found": False, "products": [], "total_facings": 0, "stock_level": "red"}


@app.route("/photo-inventory", methods=["GET", "POST"])
@require_auth
@require_write   # disables uploads in read-only mode
def photo_inventory():
    db = get_db()
    result = None

    if request.method == "POST" and "photo" in request.files:
        photo = request.files["photo"]
        if photo.filename:
            UPLOADS_DIR.mkdir(exist_ok=True, parents=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            safe_name = f"{timestamp}_{photo.filename}"
            filepath = UPLOADS_DIR / safe_name
            image_data = photo.read()
            filepath.write_bytes(image_data)

            ext = photo.filename.rsplit(".", 1)[-1].lower()
            media_types = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
                           "png": "image/png", "gif": "image/gif", "webp": "image/webp"}
            media_type = media_types.get(ext, "image/jpeg")

            account_name = request.form.get("account_name", "").strip() or None
            location_note = request.form.get("location_note", "").strip() or None

            analysis = analyze_shelf_photo(image_data, media_type)

            scan_id = db.execute(
                """INSERT INTO shelf_scans
                   (scan_date, account_name, location_note, photo_filename,
                    ai_raw_response, products_json, total_facings, stock_level)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    account_name, location_note, safe_name,
                    analysis.get("ai_raw", ""),
                    json.dumps(analysis.get("products", [])),
                    analysis.get("total_facings", 0),
                    analysis.get("stock_level", "red"),
                ),
            ).lastrowid

            for product in analysis.get("products", []):
                db.execute(
                    """INSERT INTO shelf_scan_items
                       (scan_id, style_name, estimated_count, confidence, notes)
                       VALUES (?, ?, ?, ?, ?)""",
                    (scan_id, product.get("style", "Unknown"),
                     product.get("count", 0), product.get("confidence", "low"),
                     product.get("notes", "")),
                )
            db.commit()

            result = {"status": "analyzed", "scan_id": scan_id,
                      "filename": photo.filename, "analysis": analysis,
                      "account_name": account_name, "location_note": location_note}

    recent_scans = db.execute("""
        SELECT id, scan_date, account_name, location_note,
               photo_filename, total_facings, stock_level
        FROM shelf_scans ORDER BY created_at DESC LIMIT 20
    """).fetchall()

    accounts = db.execute("SELECT account_name FROM accounts ORDER BY account_name").fetchall()
    return render_template("photo_inventory.html", result=result,
                           recent_scans=recent_scans, accounts=accounts)


@app.route("/photo-inventory/<int:scan_id>")
@require_auth
def scan_detail(scan_id):
    db = get_db()
    scan = db.execute("SELECT * FROM shelf_scans WHERE id = ?", (scan_id,)).fetchone()
    if not scan:
        flash("Scan not found", "error")
        return redirect(url_for("photo_inventory"))
    items = db.execute(
        "SELECT * FROM shelf_scan_items WHERE scan_id = ? ORDER BY estimated_count DESC",
        (scan_id,)
    ).fetchall()
    return render_template("scan_detail.html", scan=scan, items=items)


@app.route("/uploads/<filename>")
@require_auth
def uploaded_file(filename):
    return send_from_directory(str(UPLOADS_DIR), filename)


# ── JSON API (public sub-app consumption) ──────────────────────────

@app.route("/api/dashboard")
@require_auth
def api_dashboard():
    db = get_db()
    return jsonify({
        "annual_totals": [dict(r) for r in db.execute(
            "SELECT year, ROUND(value, 2) as total FROM sales_summary_annual "
            "WHERE metric = 'Net Total' ORDER BY year").fetchall()],
        "top_styles": [dict(r) for r in db.execute(
            "SELECT style_name, ROUND(SUM(cases), 1) as total_cases FROM can_sales_weekly "
            "GROUP BY style_name ORDER BY total_cases DESC LIMIT 10").fetchall()],
        "top_accounts": [dict(r) for r in db.execute(
            "SELECT account_name, ROUND(SUM(quantity), 1) as total_qty FROM wholesale_orders "
            "GROUP BY account_name ORDER BY total_qty DESC LIMIT 10").fetchall()],
    })


# ── Dev server ─────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"Database: {DB_PATH}")
    print(f"Read-only: {READ_ONLY}")
    print(f"Starting webapp on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
