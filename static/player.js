(function () {
  "use strict";

  var root = document.getElementById("player");
  if (!root) return;

  var panelJoin = document.getElementById("panel-join");
  var panelHand = document.getElementById("panel-hand");
  var leaveForm = document.getElementById("leave-form");
  var nameEl = document.getElementById("player-name");
  var roundLine = document.getElementById("round-line");
  var waiting = document.getElementById("hand-waiting");
  var none = document.getElementById("hand-none");
  var back = document.getElementById("hand-back");
  var front = document.getElementById("hand-front");
  var titleEl = document.getElementById("card-title");
  var descEl = document.getElementById("card-desc");
  var cardRound = document.getElementById("card-round");
  var revealForm = document.getElementById("reveal-form");

  function show(element, visible) {
    if (element) element.hidden = !visible;
  }

  function apply(state) {
    roundLine.textContent = "Round " + state.round;

    var joined = !!state.joined;
    show(panelJoin, !joined);
    show(panelHand, joined);
    show(leaveForm, joined);
    if (!joined) return;

    nameEl.textContent = state.name;

    var lobby = state.phase === "lobby";
    var hasCard = !!state.has_card;
    var revealed = !!state.revealed;

    show(waiting, lobby);
    show(none, !lobby && !hasCard);
    show(back, !lobby && hasCard && !revealed);
    show(front, !lobby && hasCard && revealed);

    if (state.card) {
      titleEl.textContent = state.card.title;
      descEl.textContent = state.card.description || "";
      cardRound.textContent = state.round;
    }
  }

  var current = {};
  try {
    current = JSON.parse(root.getAttribute("data-state") || "{}");
  } catch (error) {
    current = {};
  }
  apply(current);

  if (revealForm) {
    // The reveal is a normal form POST: it always works, even if this script fails.
    // After the reload the polling below keeps the page in sync with the table.
    revealForm.addEventListener("submit", function () {
      var button = revealForm.querySelector("button");
      if (button) button.disabled = true;
    });
  }

  var stopped = false;

  function poll() {
    if (stopped) return;
    if (document.hidden) {
      window.setTimeout(poll, 5000);
      return;
    }
    fetch("/api/state", {
      headers: { Accept: "application/json" },
      cache: "no-store"
    })
      .then(function (response) {
        if (!response.ok) return null;
        return response.json();
      })
      .then(function (state) {
        if (!state) return;
        if (JSON.stringify(state) !== JSON.stringify(current)) {
          current = state;
          apply(state);
        }
      })
      .catch(function () {
        /* keep polling — the host may still be starting up */
      })
      .then(function () {
        window.setTimeout(poll, 2000);
      });
  }

  window.setTimeout(poll, 1200);
  window.addEventListener("beforeunload", function () {
    stopped = true;
  });
})();
