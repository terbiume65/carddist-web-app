"""Card table — a small local web app for dealing cards to phones.

Designed for a home LAN: the host builds a deck (card types with quantities),
players join from their phones, and the host deals one card to each player.
Rounds can be reset without restarting the server.
"""

from __future__ import annotations

import hmac
import os
import random
import secrets
import socket
import sqlite3
import time
from datetime import timedelta, timezone, datetime
from functools import wraps
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from flask import (
    Flask,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

try:
    import segno
except ImportError:  # pragma: no cover - only relevant for bare installs
    segno = None


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR") or BASE_DIR / "data")
DB_PATH = Path(os.environ.get("DATABASE") or DATA_DIR / "carddist.db")

MAX_NAME = 24
MAX_TITLE = 40
MAX_DESC = 400
MAX_QTY = 99


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_secret_key() -> str:
    env = os.environ.get("SECRET_KEY", "").strip()
    if env:
        return env
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / "secret_key"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    key = secrets.token_hex(32)
    path.write_text(key, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return key


def _load_admin_pin() -> str:
    pin = os.environ.get("ADMIN_PIN", "").strip()
    if pin:
        return pin
    generated = str(secrets.randbelow(900_000) + 100_000)
    print(
        "\n  ADMIN_PIN is not set."
        f"\n  This run's admin PIN is: {generated}"
        "\n  Set the ADMIN_PIN environment variable to keep it fixed.\n",
        flush=True,
    )
    return generated


app = Flask(__name__)
app.secret_key = _load_secret_key()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_NAME="cardtable",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
    MAX_CONTENT_LENGTH=1 << 20,
    SEND_FILE_MAX_AGE_DEFAULT=0,
)
ADMIN_PIN = _load_admin_pin()
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").strip().rstrip("/")

SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    quantity    INTEGER NOT NULL CHECK (quantity BETWEEN 1 AND 99),
    created_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS players (
    id               TEXT    PRIMARY KEY,
    name             TEXT    NOT NULL,
    name_key         TEXT    NOT NULL UNIQUE,
    card_title       TEXT,
    card_description TEXT,
    revealed         INTEGER NOT NULL DEFAULT 0,
    joined_at        TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS stash (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    description TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS game (
    id    INTEGER PRIMARY KEY CHECK (id = 1),
    round INTEGER NOT NULL DEFAULT 1,
    phase TEXT    NOT NULL DEFAULT 'lobby'
);

INSERT OR IGNORE INTO game (id, round, phase) VALUES (1, 1, 'lobby');
"""


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        g.db = conn
    return g.db


@app.teardown_appcontext
def close_db(_exception=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def get_game(conn: sqlite3.Connection) -> sqlite3.Row:
    return conn.execute("SELECT round, phase FROM game WHERE id = 1").fetchone()


def current_player(conn: sqlite3.Connection):
    token = session.get("player_id")
    if not token:
        return None
    return conn.execute("SELECT * FROM players WHERE id = ?", (token,)).fetchone()


def deck_size(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COALESCE(SUM(quantity), 0) AS n FROM cards").fetchone()
    return int(row["n"])


def player_state(conn: sqlite3.Connection, player) -> dict:
    game = get_game(conn)
    state = {
        "round": game["round"],
        "phase": game["phase"],
        "joined": player is not None,
        "name": player["name"] if player else "",
        "has_card": bool(player and player["card_title"]),
        "revealed": bool(player and player["revealed"]),
        "card": None,
    }
    if player and player["card_title"] and player["revealed"] and game["phase"] == "dealt":
        state["card"] = {
            "title": player["card_title"],
            "description": player["card_description"] or "",
        }
    return state


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin_login", next=request.full_path))
        return view(*args, **kwargs)

    return wrapped


def admin_api(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin"):
            return jsonify({"error": "Not signed in as admin."}), 401
        return view(*args, **kwargs)

    return wrapped


def detect_lan_ip() -> str | None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


def public_base_url() -> str:
    """Best guess at the URL friends should open on their phones."""
    if PUBLIC_URL:
        return PUBLIC_URL
    parts = urlsplit(request.host_url)
    hostname = (parts.hostname or "").lower()
    if hostname in {"localhost", "127.0.0.1", "::1"}:
        lan_ip = detect_lan_ip()
        if lan_ip:
            host = f"[{lan_ip}]" if ":" in lan_ip else lan_ip
            netloc = f"{host}:{parts.port}" if parts.port else host
            return urlunsplit((parts.scheme, netloc, "", "", "")).rstrip("/")
    return request.host_url.rstrip("/")


def qr_data_uri(url: str) -> str | None:
    if segno is None:
        return None
    qr = segno.make(url, error="m")
    return qr.svg_data_uri(scale=6, border=2, dark="#101312", light="#ffffff")


@app.after_request
def security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


# ---------------------------------------------------------------- player views


@app.get("/")
def index():
    conn = get_db()
    player = current_player(conn)
    state = player_state(conn, player)
    return render_template(
        "player.html",
        state=state,
        deck=deck_size(conn),
        qr=None,
    )


@app.post("/join")
def join():
    conn = get_db()
    name = " ".join(request.form.get("name", "").split())
    if not name:
        flash("Please enter a name so the table knows who you are.", "error")
        return redirect(url_for("index"))
    if len(name) > MAX_NAME:
        flash(f"Names can be at most {MAX_NAME} characters.", "error")
        return redirect(url_for("index"))

    key = name.casefold()
    existing = conn.execute("SELECT id FROM players WHERE name_key = ?", (key,)).fetchone()
    if existing and existing["id"] != session.get("player_id"):
        flash(f"“{name}” is already at the table. Add an initial or a surname.", "error")
        return redirect(url_for("index"))

    token = secrets.token_urlsafe(18)
    conn.execute(
        "INSERT INTO players (id, name, name_key, joined_at) VALUES (?, ?, ?, ?)",
        (token, name, key, _timestamp()),
    )
    conn.commit()
    session["player_id"] = token
    return redirect(url_for("index"))


@app.post("/leave")
def leave():
    conn = get_db()
    player = current_player(conn)
    if player:
        # Put the card back so somebody else can be dealt it.
        if player["card_title"]:
            conn.execute(
                "INSERT INTO stash (title, description) VALUES (?, ?)",
                (player["card_title"], player["card_description"] or ""),
            )
        conn.execute("DELETE FROM players WHERE id = ?", (player["id"],))
        conn.commit()
    session.pop("player_id", None)
    flash("You have left the table.", "info")
    return redirect(url_for("index"))


@app.post("/reveal")
def reveal():
    conn = get_db()
    player = current_player(conn)
    if not player or not player["card_title"]:
        flash("There is no card to reveal yet.", "error")
        return redirect(url_for("index"))
    conn.execute("UPDATE players SET revealed = 1 WHERE id = ?", (player["id"],))
    conn.commit()
    return redirect(url_for("index"))


@app.get("/api/state")
def api_state():
    conn = get_db()
    player = current_player(conn)
    return jsonify(player_state(conn, player))


@app.post("/api/reveal")
def api_reveal():
    conn = get_db()
    player = current_player(conn)
    if not player or not player["card_title"]:
        return jsonify({"error": "There is no card to reveal yet."}), 409
    game = get_game(conn)
    if game["phase"] != "dealt":
        return jsonify({"error": "Waiting for the game master."}), 409
    conn.execute("UPDATE players SET revealed = 1 WHERE id = ?", (player["id"],))
    conn.commit()
    player = conn.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
    return jsonify(player_state(conn, player))


# ----------------------------------------------------------------- admin views


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get("admin"):
        return redirect(url_for("admin"))
    if request.method == "POST":
        pin = request.form.get("pin", "")
        if hmac.compare_digest(pin, ADMIN_PIN):
            session.permanent = True
            session["admin"] = True
            target = request.args.get("next") or url_for("admin")
            target = target.rstrip("?") or url_for("admin")
            if not target.startswith("/") or target.startswith("//"):
                target = url_for("admin")
            return redirect(target)
        time.sleep(0.8)
        flash("That PIN is not right.", "error")
    return render_template("admin_login.html")


@app.post("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    flash("Signed out of the admin panel.", "info")
    return redirect(url_for("index"))


@app.get("/admin")
@admin_required
def admin():
    conn = get_db()
    game = get_game(conn)
    cards = conn.execute("SELECT * FROM cards ORDER BY id").fetchall()
    players = conn.execute("SELECT * FROM players ORDER BY joined_at").fetchall()
    stash = conn.execute("SELECT COUNT(*) AS n FROM stash").fetchone()["n"]
    total = sum(card["quantity"] for card in cards)
    assigned = sum(1 for player in players if player["card_title"])
    player_url = public_base_url() + "/"

    return render_template(
        "admin.html",
        game=game,
        cards=cards,
        players=players,
        deck_total=total,
        assigned=assigned,
        stash=stash,
        waiting=sum(1 for player in players if not player["card_title"]),
        player_url=player_url,
        qr=qr_data_uri(player_url),
        lan_url=player_url,
    )


@app.post("/admin/cards")
@admin_required
def add_card():
    conn = get_db()
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    try:
        quantity = int(request.form.get("quantity", "1"))
    except ValueError:
        quantity = 0

    if not title:
        flash("A card needs a title.", "error")
    elif len(title) > MAX_TITLE:
        flash(f"Titles can be at most {MAX_TITLE} characters.", "error")
    elif len(description) > MAX_DESC:
        flash(f"Descriptions can be at most {MAX_DESC} characters.", "error")
    elif not 1 <= quantity <= MAX_QTY:
        flash(f"Quantity must be between 1 and {MAX_QTY}.", "error")
    else:
        conn.execute(
            "INSERT INTO cards (title, description, quantity, created_at) VALUES (?, ?, ?, ?)",
            (title, description, quantity, _timestamp()),
        )
        conn.commit()
        flash(f"Added {quantity} × {title}.", "success")
    return redirect(url_for("admin") + "#deck")


@app.post("/admin/cards/<int:card_id>")
@admin_required
def edit_card(card_id: int):
    conn = get_db()
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    try:
        quantity = int(request.form.get("quantity", "1"))
    except ValueError:
        quantity = 0

    if not title or len(title) > MAX_TITLE or len(description) > MAX_DESC:
        flash("Could not save that card — check the title and description length.", "error")
    elif not 1 <= quantity <= MAX_QTY:
        flash(f"Quantity must be between 1 and {MAX_QTY}.", "error")
    else:
        conn.execute(
            "UPDATE cards SET title = ?, description = ?, quantity = ? WHERE id = ?",
            (title, description, quantity, card_id),
        )
        conn.commit()
        flash("Card saved.", "success")
    return redirect(url_for("admin") + "#deck")


@app.post("/admin/cards/<int:card_id>/delete")
@admin_required
def delete_card(card_id: int):
    conn = get_db()
    conn.execute("DELETE FROM cards WHERE id = ?", (card_id,))
    conn.commit()
    flash("Card removed from the deck.", "info")
    return redirect(url_for("admin") + "#deck")


@app.post("/admin/deal")
@admin_required
def deal():
    conn = get_db()
    game = get_game(conn)
    if game["phase"] != "lobby":
        flash("Cards are already out. Start a new round before dealing again.", "error")
        return redirect(url_for("admin"))

    pool: list[tuple[str, str]] = []
    for row in conn.execute("SELECT title, description, quantity FROM cards ORDER BY id"):
        pool.extend([(row["title"], row["description"])] * row["quantity"])
    players = conn.execute("SELECT id, name FROM players ORDER BY joined_at").fetchall()

    if not pool:
        flash("The deck is empty — add some cards first.", "error")
        return redirect(url_for("admin") + "#deck")
    if not players:
        flash("Nobody has joined yet. Share the link first.", "error")
        return redirect(url_for("admin"))

    random.SystemRandom().shuffle(pool)
    conn.execute("DELETE FROM stash")
    for player, (title, description) in zip(players, pool):
        conn.execute(
            "UPDATE players SET card_title = ?, card_description = ?, revealed = 0 WHERE id = ?",
            (title, description, player["id"]),
        )
    for title, description in pool[len(players) :]:
        conn.execute("INSERT INTO stash (title, description) VALUES (?, ?)", (title, description))
    conn.execute("UPDATE game SET phase = 'dealt' WHERE id = 1")
    conn.commit()

    dealt = min(len(pool), len(players))
    message = f"Dealt {dealt} card{'s' if dealt != 1 else ''} to {len(players)} player{'s' if len(players) != 1 else ''}."
    if len(players) > dealt:
        message += f" The deck ran out — {len(players) - dealt} went without."
    if len(pool) > dealt:
        message += f" {len(pool) - dealt} left in reserve."
    flash(message, "success")
    return redirect(url_for("admin"))


@app.post("/admin/deal-late")
@admin_required
def deal_late():
    conn = get_db()
    game = get_game(conn)
    if game["phase"] != "dealt":
        flash("Deal the round first, then latecomers can be given a card.", "error")
        return redirect(url_for("admin"))

    waiting = conn.execute(
        "SELECT id, name FROM players WHERE card_title IS NULL ORDER BY joined_at"
    ).fetchall()
    stash = conn.execute("SELECT id, title, description FROM stash ORDER BY id").fetchall()

    if not waiting:
        flash("Everyone at the table already has a card.", "info")
        return redirect(url_for("admin"))
    if not stash:
        flash("No cards left in reserve for latecomers — start a new round.", "error")
        return redirect(url_for("admin"))

    random.SystemRandom().shuffle(stash)
    dealt = 0
    for player, card in zip(waiting, stash):
        conn.execute(
            "UPDATE players SET card_title = ?, card_description = ?, revealed = 0 WHERE id = ?",
            (card["title"], card["description"], player["id"]),
        )
        conn.execute("DELETE FROM stash WHERE id = ?", (card["id"],))
        dealt += 1
    conn.commit()
    flash(f"Dealt {dealt} reserve card{'s' if dealt != 1 else ''} to late arrivals.", "success")
    return redirect(url_for("admin"))


@app.post("/admin/new-round")
@admin_required
def new_round():
    conn = get_db()
    conn.execute(
        "UPDATE players SET card_title = NULL, card_description = NULL, revealed = 0"
    )
    conn.execute("DELETE FROM stash")
    conn.execute("UPDATE game SET phase = 'lobby', round = round + 1 WHERE id = 1")
    conn.commit()
    game = get_game(conn)
    flash(f"Round {game['round']} — cards returned. Deal when everyone is ready.", "success")
    return redirect(url_for("admin"))


@app.post("/admin/players/<player_id>/delete")
@admin_required
def remove_player(player_id: str):
    conn = get_db()
    player = conn.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone()
    if player:
        if player["card_title"]:
            conn.execute(
                "INSERT INTO stash (title, description) VALUES (?, ?)",
                (player["card_title"], player["card_description"] or ""),
            )
        conn.execute("DELETE FROM players WHERE id = ?", (player_id,))
        conn.commit()
        flash(f"{player['name']} was removed from the table.", "info")
    return redirect(url_for("admin") + "#players")


@app.post("/admin/clear-players")
@admin_required
def clear_players():
    conn = get_db()
    conn.execute("DELETE FROM players")
    conn.execute("DELETE FROM stash")
    conn.execute("UPDATE game SET phase = 'lobby' WHERE id = 1")
    conn.commit()
    session.pop("player_id", None)
    flash("Table cleared. Everyone can join again with a fresh link.", "info")
    return redirect(url_for("admin"))


@app.get("/api/admin/state")
@admin_api
def api_admin_state():
    conn = get_db()
    game = get_game(conn)
    players = conn.execute("SELECT * FROM players ORDER BY joined_at").fetchall()
    stash = conn.execute("SELECT COUNT(*) AS n FROM stash").fetchone()["n"]
    return jsonify(
        {
            "round": game["round"],
            "phase": game["phase"],
            "deck_total": deck_size(conn),
            "reserve": stash,
            "waiting": sum(1 for player in players if not player["card_title"]),
            "players": [
                {
                    "id": player["id"],
                    "name": player["name"],
                    "has_card": bool(player["card_title"]),
                    "revealed": bool(player["revealed"]),
                    "title": player["card_title"] or "",
                }
                for player in players
            ],
        }
    )


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True})


init_db()


if __name__ == "__main__":
    from waitress import serve

    port = int(os.environ.get("PORT", "8080"))
    print(f"\n  Card table running at http://0.0.0.0:{port}\n", flush=True)
    serve(app, host="0.0.0.0", port=port, threads=8)
