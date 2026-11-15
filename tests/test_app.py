"""Smoke tests for the card table app.

Run with:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

TMP_DIR = tempfile.mkdtemp(prefix="cardtable-test-")
os.environ["DATA_DIR"] = TMP_DIR
os.environ["DATABASE"] = str(Path(TMP_DIR) / "test.db")
os.environ["ADMIN_PIN"] = "2468"
os.environ["SECRET_KEY"] = "test-secret"

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as cardapp  # noqa: E402


class CardTableTests(unittest.TestCase):
    def setUp(self):
        self.client = cardapp.app.test_client()
        with cardapp.app.app_context():
            db = cardapp.get_db()
            db.executescript(
                "DELETE FROM cards; DELETE FROM players; DELETE FROM stash;"
                " UPDATE game SET phase = 'lobby', round = 1 WHERE id = 1;"
            )
            db.commit()

    # ------------------------------------------------------------- helpers

    def join(self, name, client=None):
        client = client or self.client
        return client.post("/join", data={"name": name}, follow_redirects=True)

    def login(self, pin="2468"):
        return self.client.post("/admin/login", data={"pin": pin}, follow_redirects=True)

    def add_card(self, title, description="", quantity=1):
        return self.client.post(
            "/admin/cards",
            data={"title": title, "description": description, "quantity": str(quantity)},
            follow_redirects=True,
        )

    def state(self, client=None):
        client = client or self.client
        response = client.get("/api/state")
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def admin_state(self):
        response = self.client.get("/api/admin/state")
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    # --------------------------------------------------------------- tests

    def test_join_creates_player_and_session(self):
        self.join("Alice")
        state = self.state()
        self.assertTrue(state["joined"])
        self.assertEqual(state["name"], "Alice")
        self.assertEqual(state["phase"], "lobby")
        self.assertFalse(state["has_card"])

    def test_duplicate_name_is_rejected(self):
        self.join("Alice")
        other = cardapp.app.test_client()
        response = other.post("/join", data={"name": "alice"}, follow_redirects=True)
        self.assertIn(b"already at the table", response.data)
        self.assertFalse(other.get("/api/state").get_json()["joined"])

    def test_admin_requires_pin(self):
        self.assertEqual(self.client.get("/admin").status_code, 302)
        self.assertEqual(self.client.get("/api/admin/state").status_code, 401)
        response = self.login("0000")
        self.assertIn(b"not right", response.data)
        response = self.login()
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Round controls", response.data)

    def test_deal_gives_every_player_one_unique_card(self):
        self.login()
        self.add_card("Werewolf", "You are a Werewolf.", 1)
        self.add_card("Seer", "You can see other players' roles.", 1)

        alice = cardapp.app.test_client()
        bob = cardapp.app.test_client()
        self.join("Alice", alice)
        self.join("Bob", bob)

        self.client.post("/admin/deal", follow_redirects=True)

        cards = []
        for client in (alice, bob):
            state = self.state(client)
            self.assertTrue(state["has_card"])
            self.assertFalse(state["revealed"])
            self.assertIsNone(state["card"])
            client.post("/reveal", follow_redirects=True)
            revealed = self.state(client)
            self.assertTrue(revealed["revealed"])
            cards.append(revealed["card"]["title"])

        self.assertEqual(len(set(cards)), 2)
        self.assertTrue(set(cards) <= {"Werewolf", "Seer", "Villager"})

    def test_dealing_twice_is_blocked_until_new_round(self):
        self.login()
        self.add_card("Seer", "You can see roles.", 2)
        self.join("Alice")
        self.client.post("/admin/deal")
        self.assertEqual(self.admin_state()["phase"], "dealt")

        self.client.post("/admin/deal", follow_redirects=True)
        self.assertEqual(self.admin_state()["phase"], "dealt")

        self.client.post("/admin/new-round")
        state = self.admin_state()
        self.assertEqual(state["phase"], "lobby")
        self.assertEqual(state["round"], 2)
        self.assertEqual(state["players"][0]["has_card"], False)

    def test_latecomers_can_be_dealt_from_the_reserve(self):
        self.login()
        self.add_card("Villager", "", 3)
        self.join("Alice")
        self.client.post("/admin/deal")
        self.assertEqual(self.admin_state()["reserve"], 2)

        late = cardapp.app.test_client()
        self.join("Charlie", late)
        self.assertFalse(self.state(late)["has_card"])

        self.client.post("/admin/deal-late", follow_redirects=True)
        self.assertTrue(self.state(late)["has_card"])
        self.assertEqual(self.admin_state()["reserve"], 1)

    def test_empty_deck_and_empty_table_are_reported(self):
        self.login()
        self.client.post("/admin/deal", follow_redirects=True)
        self.assertEqual(self.admin_state()["phase"], "lobby")

        self.add_card("Villager", "", 1)
        self.client.post("/admin/deal", follow_redirects=True)
        self.assertEqual(self.admin_state()["phase"], "lobby")

    def test_removing_a_player_returns_their_card_to_the_reserve(self):
        self.login()
        self.add_card("Hunter", "You may shoot someone.", 2)
        self.join("Alice")
        self.join("Bob")
        self.client.post("/admin/deal")

        state = self.admin_state()
        self.assertEqual(state["reserve"], 0)
        victim = state["players"][0]

        self.client.post(f"/admin/players/{victim['id']}/delete", follow_redirects=True)
        state = self.admin_state()
        self.assertEqual(len(state["players"]), 1)
        self.assertEqual(state["reserve"], 1)

    def test_api_reveal_returns_the_card_immediately(self):
        self.login()
        self.add_card("Seer", "Ask about one player each night.", 1)
        self.join("Alice")
        self.client.post("/admin/deal")

        response = self.client.post("/api/reveal")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["revealed"])
        self.assertEqual(payload["card"]["title"], "Seer")
        self.assertIn("Ask about one player", payload["card"]["description"])

    def test_qr_route_and_healthcheck(self):
        self.assertEqual(self.client.get("/healthz").status_code, 200)
        self.login()
        self.add_card("Villager", "", 1)
        page = self.client.get("/admin")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"/admin/login", self.client.get("/").data)


if __name__ == "__main__":
    unittest.main()
