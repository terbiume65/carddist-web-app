# Card table

A tiny web app for dealing cards to phones on your home Wi-Fi. Build a deck on your NAS (or
laptop), let everyone join from their phone, deal one random card each, and reset for the next
round. Made for Werewolf-style role cards, Mahjong ability cards, or any game where you would
otherwise hand out bits of paper.

The old single-file version is still on `main`; this is v2.

## What it does

- **Deck builder** — card types with a title, description and quantity. Fifteen villagers is one
  row, not fifteen.
- **Deal / new round** — every player gets one random card, no repeats within the round. “New
  round” takes the cards back and returns everyone to the lobby. No restarting the server, no
  losing your deck.
- **Latecomers** — anyone who joins after the deal can be given a card from the reserve.
- **Admin PIN** — the panel (which sees everyone's cards) is behind a PIN. Players only ever see
  their own.
- **Phone-first** — big tap targets, a card that stays face down until you tap it, and a page that
  updates itself when the game master deals.
- **QR code** — the admin page shows a QR code for the join link, so nobody has to type an IP.
- **Persistent** — deck, players and round survive restarts; stored in SQLite under `./data`.

## Run it on the NAS (Docker)

```bash
git clone https://github.com/terbiume65/carddist-web-app
cd carddist-web-app
git checkout v2

cp .env.example .env
# edit .env and set ADMIN_PIN to something only you know

docker compose up -d --build
```

Open `http://<nas-ip>:8080/admin`, enter the PIN, build the deck, then show the QR code to the
table.

The container listens on `0.0.0.0:8080` inside Docker; the port is published in `compose.yaml`.
If your NAS runs its own reverse proxy, point it at port 8080 instead and leave the container
port alone.

### Without Docker

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export ADMIN_PIN=2468
python app.py          # serves http://0.0.0.0:8080 with waitress
```

## Configuration

| Variable     | Default            | What it does                                                        |
|--------------|--------------------|---------------------------------------------------------------------|
| `ADMIN_PIN`  | random, per run    | PIN for `/admin`. If unset, one is printed in the server log.       |
| `SECRET_KEY` | generated + saved  | Signs session cookies. Set it to keep admin sessions across rebuilds. |
| `PUBLIC_URL` | auto-detected      | The address shown in the QR code, e.g. `http://192.168.1.50:8080`.   |
| `PORT`       | `8080`             | Port for the built-in server.                                       |
| `DATA_DIR`   | `./data`           | Where the SQLite database and secret key live.                      |
| `DATABASE`   | `$DATA_DIR/carddist.db` | Full path to the database file, if you want it elsewhere.       |

Set `ADMIN_PIN` in a `.env` file next to `compose.yaml`; Docker Compose picks it up automatically.

## How a game goes

1. You open `/admin`, unlock with the PIN, and add card types and quantities.
2. Everyone opens the address on their phone and enters a name. Names must be unique.
3. Press **Deal the cards**. Each phone flips from “waiting” to a face-down card within a couple of
   seconds; players tap to reveal.
4. Latecomer? **Deal to latecomers** gives them a card from the reserve without touching anyone
   else's.
5. Next game: **New round** returns all cards to the deck and bumps the round number. Players keep
   their seats.

The deck itself is never consumed — quantity is how many copies a round can use.

## Notes on security

This is a local-network app, not an internet service:

- It speaks plain HTTP. Do not expose it to the internet without a reverse proxy and TLS.
- Admin auth is a single shared PIN in a signed, HTTP-only, SameSite=Lax session cookie. That is
  enough to stop a friend poking at `/admin`, not enough for a hostile network.
- Failed PIN attempts are delayed by ~0.8 s, which makes guessing slow but is not a lockout.
- The player view never receives the card text until the player taps reveal, so a curious
  neighbour reading the API gets nothing.

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python -m unittest discover -s tests -v
ADMIN_PIN=2468 python app.py
```

Layout:

```
app.py              routes, database access, deal logic
templates/          base, player, admin login, admin
static/style.css    all styling, light and dark
static/player.js    polls /api/state, handles the reveal tap
static/admin.js     polls /api/admin/state, copy link, confirmations
tests/test_app.py   end-to-end flow tests with Flask's test client
```

## Troubleshooting

**Phones cannot connect.** Use the NAS's LAN IP, not `localhost`. Check the host firewall allows
port 8080, and that the phone is on the same network (guest Wi-Fi often blocks this).

**The QR code points at the wrong address.** Set `PUBLIC_URL` to the exact address you want
(`http://192.168.1.50:8080`) and restart.

**Forgot the PIN.** If `ADMIN_PIN` is unset, the PIN is in the container log:
`docker compose logs card-table | grep PIN`.

**Starting over.** Stop the container and delete `./data/carddist.db`. Or press **Clear players**
in the admin panel, which keeps the deck.
