from flask import Flask, request, redirect, url_for, session, render_template_string
import sqlite3
import os
from datetime import datetime
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "ganti-dengan-secret-key-sendiri"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "warung.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "images")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ADMIN_USER = "admin"
ADMIN_PASSWORD = "admin123"


def db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS menu (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nama TEXT NOT NULL,
            harga INTEGER NOT NULL,
            gambar TEXT,
            kategori TEXT,
            stok INTEGER DEFAULT 0,
            tersedia INTEGER DEFAULT 1
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS pesanan (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nama_pelanggan TEXT NOT NULL,
            no_hp TEXT NOT NULL,
            alamat TEXT NOT NULL,
            total INTEGER NOT NULL,
            status TEXT DEFAULT 'Baru',
            waktu TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS detail_pesanan (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pesanan_id INTEGER NOT NULL,
            menu_id INTEGER NOT NULL,
            nama_menu TEXT NOT NULL,
            harga INTEGER NOT NULL,
            jumlah INTEGER NOT NULL,
            subtotal INTEGER NOT NULL
        )
    """)

    conn.commit()

    # Menu contoh jika database masih kosong
    jumlah = cur.execute("SELECT COUNT(*) FROM menu").fetchone()[0]
    if jumlah == 0:
        contoh = [
            ("Seblak Original", 10000, "", "Seblak", 20, 1),
            ("Seblak Komplit", 15000, "", "Seblak", 20, 1),
            ("Mie Goreng", 12000, "", "Makanan", 20, 1),
            ("Es Teh", 5000, "", "Minuman", 30, 1),
        ]
        cur.executemany("""
            INSERT INTO menu (nama, harga, gambar, kategori, stok, tersedia)
            VALUES (?, ?, ?, ?, ?, ?)
        """, contoh)
        conn.commit()

    conn.close()


def rupiah(angka):
    return "Rp {:,}".format(angka).replace(",", ".")


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.template_filter("rupiah")
def rupiah_filter(value):
    return rupiah(int(value))


@app.route("/")
def index():
    conn = db()
    menus = conn.execute(
        "SELECT * FROM menu WHERE tersedia = 1 ORDER BY id DESC"
    ).fetchall()
    conn.close()

    cart = session.get("cart", {})
    jumlah_cart = sum(cart.values())

    return render_template_string(HOME_HTML, menus=menus, jumlah_cart=jumlah_cart)


@app.route("/tambah-keranjang", methods=["POST"])
def tambah_keranjang():
    menu_id = request.form.get("menu_id")
    jumlah = int(request.form.get("jumlah", 1))

    conn = db()
    menu = conn.execute(
        "SELECT * FROM menu WHERE id=? AND tersedia=1", (menu_id,)
    ).fetchone()
    conn.close()

    if not menu:
        return redirect(url_for("index"))

    if jumlah < 1:
        jumlah = 1

    cart = session.get("cart", {})
    key = str(menu_id)
    cart[key] = cart.get(key, 0) + jumlah
    session["cart"] = cart

    return redirect(url_for("keranjang"))


@app.route("/keranjang")
def keranjang():
    cart = session.get("cart", {})
    items = []
    total = 0

    conn = db()
    for menu_id, jumlah in cart.items():
        menu = conn.execute(
            "SELECT * FROM menu WHERE id=?", (menu_id,)
        ).fetchone()

        if menu:
            subtotal = menu["harga"] * jumlah
            total += subtotal
            items.append({
                "id": menu["id"],
                "nama": menu["nama"],
                "harga": menu["harga"],
                "jumlah": jumlah,
                "subtotal": subtotal,
                "stok": menu["stok"]
            })
    conn.close()

    return render_template_string(
        CART_HTML, items=items, total=total
    )


@app.route("/ubah-keranjang/<int:menu_id>", methods=["POST"])
def ubah_keranjang(menu_id):
    jumlah = int(request.form.get("jumlah", 1))
    cart = session.get("cart", {})

    if jumlah <= 0:
        cart.pop(str(menu_id), None)
    else:
        cart[str(menu_id)] = jumlah

    session["cart"] = cart
    return redirect(url_for("keranjang"))


@app.route("/hapus-keranjang/<int:menu_id>")
def hapus_keranjang(menu_id):
    cart = session.get("cart", {})
    cart.pop(str(menu_id), None)
    session["cart"] = cart
    return redirect(url_for("keranjang"))


@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    cart = session.get("cart", {})

    if not cart:
        return redirect(url_for("index"))

    conn = db()
    items = []
    total = 0

    for menu_id, jumlah in cart.items():
        menu = conn.execute(
            "SELECT * FROM menu WHERE id=?", (menu_id,)
        ).fetchone()

        if menu:
            subtotal = menu["harga"] * jumlah
            total += subtotal
            items.append((menu, jumlah, subtotal))

    if request.method == "POST":
        nama = request.form.get("nama", "").strip()
        no_hp = request.form.get("no_hp", "").strip()
        alamat = request.form.get("alamat", "").strip()

        if not nama or not no_hp or not alamat:
            conn.close()
            return render_template_string(
                CHECKOUT_HTML,
                items=items,
                total=total,
                error="Semua data harus diisi."
            )

        waktu = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cur = conn.cursor()
        cur.execute("""
            INSERT INTO pesanan
            (nama_pelanggan, no_hp, alamat, total, status, waktu)
            VALUES (?, ?, ?, ?, 'Baru', ?)
        """, (nama, no_hp, alamat, total, waktu))

        order_id = cur.lastrowid

        for menu, jumlah, subtotal in items:
            cur.execute("""
                INSERT INTO detail_pesanan
                (pesanan_id, menu_id, nama_menu, harga, jumlah, subtotal)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                order_id,
                menu["id"],
                menu["nama"],
                menu["harga"],
                jumlah,
                subtotal
            ))

            cur.execute("""
                UPDATE menu
                SET stok = MAX(stok - ?, 0)
                WHERE id=?
            """, (jumlah, menu["id"]))

        conn.commit()
        conn.close()

        session["cart"] = {}

        return render_template_string(
            SUCCESS_HTML,
            order_id=order_id,
            total=total
        )

    conn.close()
    return render_template_string(
        CHECKOUT_HTML, items=items, total=total, error=""
    )


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = ""

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if username == ADMIN_USER and password == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect(url_for("admin"))
        else:
            error = "Username atau password salah."

    return render_template_string(LOGIN_HTML, error=error)


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("admin_login"))


def admin_required():
    return session.get("admin") is True


@app.route("/admin")
def admin():
    if not admin_required():
        return redirect(url_for("admin_login"))

    conn = db()
    menus = conn.execute("SELECT * FROM menu ORDER BY id DESC").fetchall()
    orders = conn.execute(
        "SELECT * FROM pesanan ORDER BY id DESC"
    ).fetchall()
    conn.close()

    return render_template_string(
        ADMIN_HTML, menus=menus, orders=orders
    )


@app.route("/admin/menu/tambah", methods=["GET", "POST"])
def tambah_menu():
    if not admin_required():
        return redirect(url_for("admin_login"))

    if request.method == "POST":
        nama = request.form.get("nama", "").strip()
        harga = int(request.form.get("harga", 0))
        kategori = request.form.get("kategori", "").strip()
        stok = int(request.form.get("stok", 0))

        gambar = ""
        file = request.files.get("gambar")

        if file and file.filename and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            nama_file = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
            file.save(os.path.join(UPLOAD_FOLDER, nama_file))
            gambar = nama_file

        conn = db()
        conn.execute("""
            INSERT INTO menu
            (nama, harga, gambar, kategori, stok, tersedia)
            VALUES (?, ?, ?, ?, ?, 1)
        """, (nama, harga, gambar, kategori, stok))
        conn.commit()
        conn.close()

        return redirect(url_for("admin"))

    return render_template_string(MENU_FORM_HTML, menu=None, judul="Tambah Menu")


@app.route("/admin/menu/edit/<int:menu_id>", methods=["GET", "POST"])
def edit_menu(menu_id):
    if not admin_required():
        return redirect(url_for("admin_login"))

    conn = db()
    menu = conn.execute(
        "SELECT * FROM menu WHERE id=?", (menu_id,)
    ).fetchone()

    if not menu:
        conn.close()
        return redirect(url_for("admin"))

    if request.method == "POST":
        nama = request.form.get("nama", "").strip()
        harga = int(request.form.get("harga", 0))
        kategori = request.form.get("kategori", "").strip()
        stok = int(request.form.get("stok", 0))
        tersedia = 1 if request.form.get("tersedia") == "1" else 0

        gambar = menu["gambar"] or ""
        file = request.files.get("gambar")

        if file and file.filename and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            nama_file = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
            file.save(os.path.join(UPLOAD_FOLDER, nama_file))
            gambar = nama_file

        conn.execute("""
            UPDATE menu
            SET nama=?, harga=?, gambar=?, kategori=?, stok=?, tersedia=?
            WHERE id=?
        """, (
            nama, harga, gambar, kategori, stok, tersedia, menu_id
        ))
        conn.commit()
        conn.close()

        return redirect(url_for("admin"))

    conn.close()
    return render_template_string(
        MENU_FORM_HTML, menu=menu, judul="Edit Menu"
    )


@app.route("/admin/menu/hapus/<int:menu_id>")
def hapus_menu(menu_id):
    if not admin_required():
        return redirect(url_for("admin_login"))

    conn = db()
    menu = conn.execute(
        "SELECT gambar FROM menu WHERE id=?", (menu_id,)
    ).fetchone()

    if menu and menu["gambar"]:
        path = os.path.join(UPLOAD_FOLDER, menu["gambar"])
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    conn.execute("DELETE FROM menu WHERE id=?", (menu_id,))
    conn.commit()
    conn.close()

    return redirect(url_for("admin"))


@app.route("/admin/status/<int:order_id>", methods=["POST"])
def ubah_status(order_id):
    if not admin_required():
        return redirect(url_for("admin_login"))

    status = request.form.get("status")

    if status not in {"Baru", "Diproses", "Selesai", "Dibatalkan"}:
        return redirect(url_for("admin"))

    conn = db()
    conn.execute(
        "UPDATE pesanan SET status=? WHERE id=?",
        (status, order_id)
    )
    conn.commit()
    conn.close()

    return redirect(url_for("admin"))


@app.route("/admin/pesanan/<int:order_id>")
def detail_pesanan(order_id):
    if not admin_required():
        return redirect(url_for("admin_login"))

    conn = db()
    order = conn.execute(
        "SELECT * FROM pesanan WHERE id=?", (order_id,)
    ).fetchone()

    details = conn.execute("""
        SELECT * FROM detail_pesanan
        WHERE pesanan_id=?
    """, (order_id,)).fetchall()

    conn.close()

    if not order:
        return redirect(url_for("admin"))

    return render_template_string(
        ORDER_DETAIL_HTML, order=order, details=details
    )


HOME_HTML = """
<!doctype html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Warung Makanan</title>
<style>
body{font-family:Arial;margin:0;background:#f5f5f5;color:#222}
header{background:#111;color:white;padding:20px;text-align:center}
nav{margin-top:10px}
a,button{background:#ff7a00;color:white;border:0;padding:10px 14px;border-radius:8px;text-decoration:none;cursor:pointer}
.container{max-width:1100px;margin:25px auto;padding:0 15px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:18px}
.card{background:white;border-radius:12px;padding:15px;box-shadow:0 2px 8px #ddd}
.card img{width:100%;height:170px;object-fit:cover;border-radius:10px;background:#eee}
.price{font-weight:bold;font-size:18px}
input,textarea,select{width:100%;padding:10px;margin:7px 0 12px;box-sizing:border-box;border:1px solid #ccc;border-radius:7px}
.cart{background:#198754}
.muted{color:#666}
</style>
</head>
<body>
<header>
<h1>🍜 WARUNG MAKANAN</h1>
<p>Pesan makanan dengan mudah</p>
<nav>
<a href="/">Menu</a>
<a href="/keranjang" class="cart">🛒 Keranjang ({{ jumlah_cart }})</a>
</nav>
</header>
<div class="container">
<h2>Daftar Menu</h2>
<div class="grid">
{% for m in menus %}
<div class="card">
{% if m['gambar'] %}
<img src="{{ url_for('static', filename='images/' + m['gambar']) }}">
{% endif %}
<h3>{{ m['nama'] }}</h3>
<p class="muted">{{ m['kategori'] or '' }}</p>
<p class="price">{{ m['harga']|rupiah }}</p>
<p>Stok: {{ m['stok'] }}</p>
{% if m['stok'] > 0 %}
<form method="post" action="/tambah-keranjang">
<input type="hidden" name="menu_id" value="{{ m['id'] }}">
<input type="number" name="jumlah" value="1" min="1" max="{{ m['stok'] }}">
<button type="submit">Tambah ke Keranjang</button>
</form>
{% else %}
<p><b>Stok habis</b></p>
{% endif %}
</div>
{% endfor %}
</div>
</div>
</body>
</html>
"""

CART_HTML = """
<!doctype html>
<html lang="id"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Keranjang</title>
<style>
body{font-family:Arial;background:#f5f5f5;margin:0}.container{max-width:850px;margin:30px auto;padding:15px}
.box{background:white;padding:18px;margin-bottom:12px;border-radius:12px}
a,button{background:#ff7a00;color:white;border:0;padding:10px 14px;border-radius:8px;text-decoration:none;cursor:pointer}
input{padding:8px;width:70px}
.total{font-size:21px;font-weight:bold}
</style></head>
<body><div class="container">
<h1>🛒 Keranjang</h1>
{% if items %}
{% for i in items %}
<div class="box">
<h3>{{ i['nama'] }}</h3>
<p>{{ i['harga']|rupiah }} × {{ i['jumlah'] }} = <b>{{ i['subtotal']|rupiah }}</b></p>
<form method="post" action="/ubah-keranjang/{{ i['id'] }}">
<input type="number" name="jumlah" value="{{ i['jumlah'] }}" min="0" max="{{ i['stok'] }}">
<button type="submit">Ubah</button>
<a href="/hapus-keranjang/{{ i['id'] }}">Hapus</a>
</form>
</div>
{% endfor %}
<div class="box">
<p class="total">Total: {{ total|rupiah }}</p>
<a href="/checkout">Lanjut Checkout</a>
<a href="/">Tambah Menu</a>
</div>
{% else %}
<div class="box"><p>Keranjang masih kosong.</p><a href="/">Kembali ke Menu</a></div>
{% endif %}
</div></body></html>
"""

CHECKOUT_HTML = """
<!doctype html><html lang="id"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Checkout</title><style>
body{font-family:Arial;background:#f5f5f5;margin:0}.container{max-width:700px;margin:30px auto;padding:15px}.box{background:white;padding:20px;border-radius:12px}
input,textarea{width:100%;padding:11px;margin:6px 0 14px;box-sizing:border-box;border:1px solid #ccc;border-radius:7px}
button,a{background:#ff7a00;color:white;border:0;padding:11px 15px;border-radius:8px;text-decoration:none}
.error{background:#f8d7da;padding:10px;border-radius:7px}
</style></head><body><div class="container"><div class="box">
<h1>Checkout</h1>
{% if error %}<p class="error">{{ error }}</p>{% endif %}
{% for m,j,s in items %}<p>{{ m['nama'] }} × {{ j }} = <b>{{ s|rupiah }}</b></p>{% endfor %}
<hr><h2>Total: {{ total|rupiah }}</h2>
<form method="post">
<label>Nama</label><input name="nama" required>
<label>No. HP</label><input name="no_hp" required>
<label>Alamat</label><textarea name="alamat" rows="4" required></textarea>
<button type="submit">Buat Pesanan</button>
<a href="/keranjang">Kembali</a>
</form>
</div></div></body></html>
"""

SUCCESS_HTML = """
<!doctype html><html lang="id"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pesanan Berhasil</title><style>body{font-family:Arial;text-align:center;background:#f5f5f5;padding:40px}.box{background:white;padding:30px;border-radius:15px;max-width:500px;margin:auto}a{background:#ff7a00;color:white;padding:12px 18px;border-radius:8px;text-decoration:none}</style></head>
<body><div class="box"><h1>✅ Pesanan Berhasil</h1><p>Nomor pesanan: <b>#{{ order_id }}</b></p><p>Total: <b>{{ total|rupiah }}</b></p><a href="/">Kembali ke Menu</a></div></body></html>
"""

LOGIN_HTML = """
<!doctype html><html lang="id"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Admin Login</title><style>body{font-family:Arial;background:#f5f5f5;padding:40px}.box{max-width:400px;margin:auto;background:white;padding:25px;border-radius:12px}input,button{width:100%;box-sizing:border-box;padding:11px;margin:7px 0}button{background:#111;color:white;border:0;border-radius:7px}.error{color:red}</style></head>
<body><div class="box"><h2>🔐 Admin</h2>{% if error %}<p class="error">{{ error }}</p>{% endif %}
<form method="post"><input name="username" placeholder="Username" required><input type="password" name="password" placeholder="Password" required><button>Login</button></form>
</div></body></html>
"""

ADMIN_HTML = """
<!doctype html><html lang="id"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Admin Warung</title><style>
body{font-family:Arial;background:#f5f5f5;margin:0}.container{max-width:1100px;margin:25px auto;padding:15px}.box{background:white;padding:18px;border-radius:12px;margin-bottom:20px}
table{width:100%;border-collapse:collapse}th,td{padding:10px;border-bottom:1px solid #ddd;text-align:left}a,button{background:#ff7a00;color:white;border:0;padding:8px 12px;border-radius:7px;text-decoration:none;cursor:pointer}.danger{background:#dc3545}.green{background:#198754}select{padding:7px}
</style></head><body><div class="container">
<h1>⚙️ Admin Warung</h1><a href="/admin/menu/tambah">+ Tambah Menu</a> <a href="/admin/logout" class="danger">Logout</a>
<div class="box"><h2>Menu</h2><table><tr><th>Nama</th><th>Harga</th><th>Kategori</th><th>Stok</th><th>Aksi</th></tr>
{% for m in menus %}<tr><td>{{ m['nama'] }}</td><td>{{ m['harga']|rupiah }}</td><td>{{ m['kategori'] }}</td><td>{{ m['stok'] }}</td>
<td><a href="/admin/menu/edit/{{ m['id'] }}">Edit</a> <a class="danger" href="/admin/menu/hapus/{{ m['id'] }}" onclick="return confirm('Hapus menu?')">Hapus</a></td></tr>{% endfor %}
</table></div>
<div class="box"><h2>Pesanan</h2><table><tr><th>No</th><th>Pelanggan</th><th>Total</th><th>Status</th><th>Waktu</th><th>Aksi</th></tr>
{% for o in orders %}<tr><td>#{{ o['id'] }}</td><td>{{ o['nama_pelanggan'] }}<br>{{ o['no_hp'] }}</td><td>{{ o['total']|rupiah }}</td>
<td><form method="post" action="/admin/status/{{ o['id'] }}"><select name="status"><option {% if o['status']=='Baru' %}selected{% endif %}>Baru</option><option {% if o['status']=='Diproses' %}selected{% endif %}>Diproses</option><option {% if o['status']=='Selesai' %}selected{% endif %}>Selesai</option><option {% if o['status']=='Dibatalkan' %}selected{% endif %}>Dibatalkan</option></select><button class="green">Simpan</button></form></td>
<td>{{ o['waktu'] }}</td><td><a href="/admin/pesanan/{{ o['id'] }}">Detail</a></td></tr>{% endfor %}
</table></div>
</div></body></html>
"""

MENU_FORM_HTML = """
<!doctype html><html lang="id"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ judul }}</title><style>body{font-family:Arial;background:#f5f5f5;padding:30px}.box{background:white;max-width:600px;margin:auto;padding:25px;border-radius:12px}input,select{width:100%;box-sizing:border-box;padding:10px;margin:6px 0 15px}button,a{background:#ff7a00;color:white;border:0;padding:10px 15px;border-radius:7px;text-decoration:none}</style></head>
<body><div class="box"><h1>{{ judul }}</h1>
<form method="post" enctype="multipart/form-data">
<label>Nama Menu</label><input name="nama" value="{{ menu['nama'] if menu else '' }}" required>
<label>Harga</label><input type="number" name="harga" value="{{ menu['harga'] if menu else '' }}" required>
<label>Kategori</label><input name="kategori" value="{{ menu['kategori'] if menu else '' }}">
<label>Stok</label><input type="number" name="stok" value="{{ menu['stok'] if menu else 0 }}" min="0">
<label>Gambar</label><input type="file" name="gambar" accept=".jpg,.jpeg,.png,.webp">
{% if menu %}<label>Status</label><select name="tersedia"><option value="1" {% if menu['tersedia'] %}selected{% endif %}>Tersedia</option><option value="0" {% if not menu['tersedia'] %}selected{% endif %}>Tidak tersedia</option></select>{% endif %}
<button type="submit">Simpan</button> <a href="/admin">Batal</a>
</form></div></body></html>
"""

ORDER_DETAIL_HTML = """
<!doctype html><html lang="id"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Detail Pesanan</title><style>body{font-family:Arial;background:#f5f5f5;padding:25px}.box{max-width:700px;margin:auto;background:white;padding:20px;border-radius:12px}table{width:100%;border-collapse:collapse}td{padding:9px;border-bottom:1px solid #ddd}a{display:inline-block;background:#ff7a00;color:white;padding:10px 15px;border-radius:7px;text-decoration:none}</style></head>
<body><div class="box"><h1>Pesanan #{{ order['id'] }}</h1>
<p><b>Pelanggan:</b> {{ order['nama_pelanggan'] }}</p><p><b>No HP:</b> {{ order['no_hp'] }}</p><p><b>Alamat:</b> {{ order['alamat'] }}</p><p><b>Status:</b> {{ order['status'] }}</p>
<table>{% for d in details %}<tr><td>{{ d['nama_menu'] }}</td><td>{{ d['jumlah'] }} × {{ d['harga']|rupiah }}</td><td>{{ d['subtotal']|rupiah }}</td></tr>{% endfor %}</table>
<h2>Total: {{ order['total']|rupiah }}</h2><a href="/admin">Kembali</a></div></body></html>
"""


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
