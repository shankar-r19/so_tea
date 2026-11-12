#!/usr/bin/env python3
import base64
import json
import os
import smtplib
import sqlite3
from email.message import EmailMessage
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "preorders.db")
ADMIN_USERNAME = os.environ.get("SO_TEA_ADMIN_USERNAME", "your_username")
ADMIN_PASSWORD = os.environ.get("SO_TEA_ADMIN_PASSWORD", "your_password")
EMAIL_TO = os.environ.get("PREORDER_EMAIL_TO", "shankar@sotea.co.uk")
SMTP_HOST = os.environ.get("SMTP_HOST")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")


def ensure_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS preorder_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT,
            colour TEXT,
            product TEXT,
            size TEXT,
            source TEXT,
            preorder_price TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()


def fetch_preorders():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT id, name, email, colour, product, size, source, preorder_price, created_at
        FROM preorder_records
        ORDER BY created_at DESC
        """
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def send_preorder_email(payload):
    if not SMTP_HOST or not SMTP_USER or not SMTP_PASSWORD:
        print(f"Email not sent: SMTP config missing. Payload: {payload}")
        return True

    message = EmailMessage()
    message["Subject"] = "New so tea preorder"
    message["From"] = SMTP_USER
    message["To"] = EMAIL_TO
    message.set_content(
        "\n".join([
            "New so tea preorder received.",
            "",
            f"Name: {payload.get('name') or 'N/A'}",
            f"Email: {payload.get('email') or 'N/A'}",
            f"Colour: {payload.get('colour') or 'N/A'}",
            f"Product: {payload.get('product') or 'N/A'}",
            f"Size: {payload.get('size') or 'N/A'}",
            f"Source: {payload.get('source') or 'N/A'}",
            f"Preorder price: {payload.get('preorder_price') or 'N/A'}",
        ])
    )

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(message)
        return True
    except Exception as exc:  # pragma: no cover - runtime safeguard
        print(f"Email send failed: {exc}")
        return False


def check_admin_credentials(auth_header):
    if not auth_header or not auth_header.startswith("Basic "):
        return False
    try:
        raw = base64.b64decode(auth_header.split(" ", 1)[1]).decode("utf-8")
        username, password = raw.split(":", 1)
    except Exception:
        return False
    return username == ADMIN_USERNAME and password == ADMIN_PASSWORD


class PreorderHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/admin", "/admin.html"):
            self._serve_admin_page()
            return
        if parsed.path == "/api/preorders":
            if not check_admin_credentials(self.headers.get("Authorization", "")):
                payload = {"status": "error", "message": "Unauthorized"}
                body = json.dumps(payload).encode("utf-8")
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("WWW-Authenticate", 'Basic realm="so tea admin"')
                self.end_headers()
                self.wfile.write(body)
                return
            self._send_json(fetch_preorders())
            return
        if parsed.path == "/api/preorder":
            self._send_json({"status": "ok", "message": "Use POST to save a preorder."})
            return
        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/preorder":
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                payload = {}

            name = (payload.get("name") or "").strip()
            email = (payload.get("email") or "").strip()
            colour = (payload.get("colour") or "").strip()
            product = (payload.get("product") or "").strip()
            size = (payload.get("size") or "").strip()
            source = (payload.get("source") or "").strip()
            preorder_price = (payload.get("preorder_price") or "").strip()

            if not email or not product:
                self._send_json({"status": "error", "message": "Email and product are required."}, status=400)
                return

            try:
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.execute(
                    """
                    INSERT INTO preorder_records (name, email, colour, product, size, source, preorder_price)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (name, email, colour, product, size, source, preorder_price),
                )
                conn.commit()
                conn.close()
            except Exception as exc:  # pragma: no cover - runtime safeguard
                self._send_json({"status": "error", "message": f"Database insert failed: {exc}"}, status=500)
                return

            send_preorder_email(payload)
            self._send_json({"status": "success", "message": "Preorder saved."}, status=201)
            return

        if parsed.path == "/api/admin/login":
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                body = {}
            username = (body.get("username") or "").strip()
            password = (body.get("password") or "").strip()
            if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
                self._send_json({"status": "success", "message": "Authenticated."})
                return
            self._send_json({"status": "error", "message": "Invalid username or password."}, status=401)
            return

        self.send_error(404, "Not found")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        return

    def _serve_admin_page(self):
        html = """
        <!doctype html>
        <html lang="en">
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <title>so tea admin</title>
          <style>
            body{font-family:system-ui,sans-serif;background:#f6efe6;color:#1d1d1d;padding:40px 20px}
            .wrap{max-width:980px;margin:0 auto}
            .card{background:#fff;padding:24px;border-radius:16px;box-shadow:0 10px 30px rgba(0,0,0,.08)}
            input,button{font:inherit;padding:12px 14px;border-radius:10px;border:1px solid #d7d0c9;width:100%;margin-top:10px}
            button{background:#3a2a22;color:#fff;border:none;cursor:pointer}
            table{width:100%;border-collapse:collapse;margin-top:20px}
            th,td{padding:10px 12px;border-bottom:1px solid #eee;text-align:left;vertical-align:top}
            .hidden{display:none}
            .status{margin-top:10px;font-size:.95rem}
          </style>
        </head>
        <body>
          <div class="wrap">
            <div class="card" id="login-card">
              <h2>so tea admin</h2>
              <input id="username" placeholder="Username" />
              <input id="password" type="password" placeholder="Password" />
              <button id="login-btn">Login</button>
              <div id="login-status" class="status"></div>
            </div>

            <div class="card hidden" id="records-card">
              <h2>Preorders</h2>
              <table>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Email</th>
                    <th>Colour</th>
                    <th>Product</th>
                    <th>Size</th>
                    <th>Price</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody id="records-body"></tbody>
              </table>
            </div>
          </div>

          <script>
            const loginCard = document.getElementById('login-card');
            const recordsCard = document.getElementById('records-card');
            const statusEl = document.getElementById('login-status');
            const localState = { token: null };

            async function login() {
              const username = document.getElementById('username').value;
              const password = document.getElementById('password').value;
              statusEl.textContent = 'Checking credentials...';

              const res = await fetch('/api/admin/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password })
              });

              const payload = await res.json();
              if (!res.ok) {
                statusEl.textContent = payload.message || 'Login failed.';
                return;
              }

              localState.token = btoa(username + ':' + password);
              loginCard.classList.add('hidden');
              recordsCard.classList.remove('hidden');
              loadRecords();
            }

            async function loadRecords() {
              const res = await fetch('/api/preorders', {
                headers: { Authorization: 'Basic ' + localState.token }
              });

              if (!res.ok) {
                statusEl.textContent = 'Session expired. Please log in again.';
                loginCard.classList.remove('hidden');
                recordsCard.classList.add('hidden');
                return;
              }

              const data = await res.json();
              const body = document.getElementById('records-body');
              body.innerHTML = data.map(item => `
                <tr>
                  <td>${item.name || '—'}</td>
                  <td>${item.email || '—'}</td>
                  <td>${item.colour || '—'}</td>
                  <td>${item.product || '—'}</td>
                  <td>${item.size || '—'}</td>
                  <td>${item.preorder_price || '—'}</td>
                  <td>${item.created_at || '—'}</td>
                </tr>
              `).join('');
            }

            document.getElementById('login-btn').addEventListener('click', login);
          </script>
        </body>
        </html>
        """
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    ensure_db()
    port = int(os.environ.get("PORT", "8000"))
    handler = lambda *args, **kwargs: PreorderHandler(*args, directory=BASE_DIR, **kwargs)
    with ThreadingHTTPServer(("0.0.0.0", port), handler) as httpd:
        print(f"Serving so tea on http://localhost:{port}")
        httpd.serve_forever()
