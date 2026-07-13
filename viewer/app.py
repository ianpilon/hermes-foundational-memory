#!/usr/bin/env python3
"""Foundational Memory — unified viewer app (control + dashboard, one port, authed).

One always-on localhost service that serves BOTH the control UI and the live
dashboard on a single port, so it works behind a single tunnel hostname. Access
requires a password (HTTP Basic Auth) because this can be exposed publicly — the
tunnel terminates TLS, so credentials travel encrypted.

On-demand semantics without a second process: "Start"/"Stop" flip a serving flag.
While stopped, /api/bank refuses to return memory data even to an authed client.

    python3 app.py                 # http://127.0.0.1:8748  (bank at ~/.hermes/foundational_memory)

Auth: password read from ~/.hermes/.fm_token (auto-generated on first run, chmod 600).
Any username works; the password must match. Retrieve it with:  cat ~/.hermes/.fm_token
"""
import base64, hmac, json, os, secrets, stat, http.server, socketserver
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
HOST = os.environ.get("FM_HOST", "127.0.0.1")
PORT = int(os.environ.get("FM_CTRL_PORT", os.environ.get("FM_PORT", "8748")))
BANK = os.path.expanduser(os.environ.get("FM_BANK", "~/.hermes/foundational_memory"))
TOKEN_FILE = os.path.expanduser(os.environ.get("FM_TOKEN_FILE", "~/.hermes/.fm_token"))
REALM = "Foundational Memory"
BASE = os.environ.get("FM_BASE_PATH", "").rstrip("/")  # e.g. "/memory" when served under a path

_serving = False  # on-demand flag; starts stopped


def _load_token():
    """Read the access password, generating a strong one on first run."""
    try:
        tok = open(TOKEN_FILE).read().strip()
        if tok:
            return tok
    except FileNotFoundError:
        pass
    tok = secrets.token_urlsafe(24)
    with open(TOKEN_FILE, "w") as f:
        f.write(tok + "\n")
    try:
        os.chmod(TOKEN_FILE, stat.S_IRUSR | stat.S_IWUSR)  # 0600
    except OSError:
        pass
    return tok


TOKEN = _load_token()


def _read(name):
    try:
        return open(os.path.join(BANK, name), encoding="utf-8").read()
    except FileNotFoundError:
        return ""


def _jsonl(name):
    out = []
    for line in _read(name).splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def build_data():
    l1, l2, cycles = _jsonl("raw.jsonl"), _jsonl("records.jsonl"), _jsonl("cycles.jsonl")
    try:
        status = json.loads(_read("status.json") or "{}")
    except json.JSONDecodeError:
        status = {}
    try:
        cursor = json.loads(_read("cursor.json") or "{}").get("processed", 0)
    except json.JSONDecodeError:
        cursor = 0
    by_id = {r.get("id"): r for r in l1}
    for rec in l2:
        rec["_prov"] = [{"role": by_id[i]["role"], "content": by_id[i]["content"][:180]}
                        for i in rec.get("source_ids", []) if i in by_id]
    return {
        "generated": max([r.get("timestamp", "") for r in l1] + [""]),
        "l1_count": len(l1), "l1_roles": dict(Counter(r.get("role") for r in l1)),
        "l2_count": len(l2), "l2_types": dict(Counter(r.get("type") for r in l2)),
        "cursor": cursor, "pending": max(0, len(l1) - cursor),
        "status": status, "records": l2, "cycles": cycles,
        "profile": _read("profile.md"), "bank_path": BANK,
    }


class Handler(http.server.BaseHTTPRequestHandler):
    # -- auth ---------------------------------------------------------------
    def _authed(self):
        hdr = self.headers.get("Authorization", "")
        if not hdr.startswith("Basic "):
            return False
        try:
            _, pw = base64.b64decode(hdr[6:]).decode("utf-8", "replace").split(":", 1)
        except Exception:
            return False
        return hmac.compare_digest(pw, TOKEN)

    def _need_auth(self):
        self.send_response(401)
        self.send_header("WWW-Authenticate", f'Basic realm="{REALM}"')
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"authentication required")

    # -- helpers ------------------------------------------------------------
    def _send(self, code, body, ctype):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj), "application/json")

    # -- routes -------------------------------------------------------------
    def _strip_base(self, raw):
        """Strip the BASE prefix. Returns (path, redirect_to|None)."""
        if not BASE:
            return raw, None
        if raw == BASE:
            return raw, BASE + "/"          # bare base without slash -> add slash
        if raw.startswith(BASE + "/"):
            return raw[len(BASE):], None    # /memory/api/x -> /api/x
        return raw, None                    # not under base -> will 404

    def _redirect(self, to):
        self.send_response(302)
        self.send_header("Location", to)
        self.end_headers()

    def do_GET(self):
        raw = self.path.split("?", 1)[0]
        path, redir = self._strip_base(raw)
        if redir:
            return self._redirect(redir)
        if not self._authed():
            return self._need_auth()
        if path == "/api/status":
            self._json({"serving": _serving, "bank": os.path.basename(BANK)})
        elif path == "/api/bank":
            if not _serving:
                self._json({"stopped": True}, 409)
            else:
                try:
                    self._json(build_data())
                except Exception as e:
                    self._json({"error": str(e)}, 500)
        elif path in ("/", "/index.html", "/app.html"):
            try:
                self._send(200, open(os.path.join(HERE, "app.html"), encoding="utf-8").read(),
                           "text/html; charset=utf-8")
            except FileNotFoundError:
                self._send(404, "app.html not found next to app.py", "text/plain")
        else:
            self._send(404, "not found", "text/plain")

    def do_POST(self):
        global _serving
        raw = self.path.split("?", 1)[0]
        path, _ = self._strip_base(raw)
        if not self._authed():
            return self._need_auth()
        if path == "/api/start":
            _serving = True
            self._json({"serving": True})
        elif path == "/api/stop":
            _serving = False
            self._json({"serving": False})
        else:
            self._send(404, "not found", "text/plain")

    def log_message(self, *args):
        pass


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    if not os.path.isdir(BANK):
        raise SystemExit(f"bank not found: {BANK}")
    with Server((HOST, PORT), Handler) as httpd:
        print(f"Foundational memory app  →  http://{HOST}:{PORT}   (password in {TOKEN_FILE})")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped.")
