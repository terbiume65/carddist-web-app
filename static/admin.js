(function () {
  "use strict";

  var admin = document.getElementById("admin");
  if (!admin) return;

  // Confirmation prompts for destructive buttons.
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    var message =
      form.getAttribute("data-confirm") ||
      (event.submitter && event.submitter.getAttribute("data-confirm"));
    if (message && !window.confirm(message)) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  });

  // Copy the join link.
  var copyButton = document.getElementById("copy-url");
  if (copyButton) {
    copyButton.addEventListener("click", function () {
      var url = copyButton.getAttribute("data-url") || "";
      var done = function () {
        copyButton.textContent = "Copied";
        window.setTimeout(function () {
          copyButton.textContent = "Copy link";
        }, 1600);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(done, function () {
          window.prompt("Copy this link:", url);
        });
      } else {
        window.prompt("Copy this link:", url);
      }
    });
  }

  function tag(text, extra) {
    var span = document.createElement("span");
    span.className = "tag" + (extra ? " " + extra : "");
    span.textContent = text;
    return span;
  }

  function renderPlayers(players) {
    var list = document.getElementById("player-list");
    if (!list) return;

    if (!players.length) {
      var empty = document.createElement("li");
      empty.className = "empty";
      empty.textContent = "Nobody has joined yet — share the link above.";
      list.replaceChildren(empty);
      return;
    }

    var rows = players.map(function (player) {
      var row = document.createElement("li");
      row.setAttribute("data-player", player.id);

      var nameWrap = document.createElement("div");
      nameWrap.className = "player-name";
      var strong = document.createElement("strong");
      strong.textContent = player.name;
      nameWrap.appendChild(strong);

      if (player.has_card) {
        nameWrap.appendChild(tag(player.title));
        nameWrap.appendChild(tag(player.revealed ? "seen" : "face down", "soft"));
      } else {
        nameWrap.appendChild(tag("waiting", "ghost"));
      }
      row.appendChild(nameWrap);

      var form = document.createElement("form");
      form.method = "post";
      form.action = "/admin/players/" + encodeURIComponent(player.id) + "/delete";
      form.setAttribute("data-confirm", "Remove " + player.name + " from the table?");
      var button = document.createElement("button");
      button.type = "submit";
      button.className = "linkish danger-text";
      button.textContent = "Remove";
      form.appendChild(button);
      row.appendChild(form);

      return row;
    });

    list.replaceChildren.apply(list, rows);
  }

  function setText(id, value) {
    var element = document.getElementById(id);
    if (element) element.textContent = value;
  }

  function apply(state) {
    setText("status-phase", state.phase === "lobby" ? "Lobby · waiting to deal" : "Cards dealt");
    setText("status-round", "Round " + state.round);
    setText("count-players", state.players.length);
    setText("count-cards", state.deck_total);
    setText("count-reserve", state.reserve);
    setText("players-badge", state.players.length);

    var dealButton = document.getElementById("deal-button");
    if (dealButton) dealButton.disabled = state.phase !== "lobby";

    var lateButton = document.querySelector('form[action$="/admin/deal-late"] button');
    if (lateButton) lateButton.disabled = state.phase !== "dealt";

    renderPlayers(state.players);

    var warning = document.getElementById("short-warning");
    if (warning) {
      if (state.deck_total === 0) {
        warning.textContent = "The deck is empty. Add cards below before dealing.";
        warning.hidden = false;
      } else if (state.deck_total < state.players.length) {
        warning.textContent =
          "Fewer cards than players — somebody will go without. Add cards or reduce quantities.";
        warning.hidden = false;
      } else {
        warning.hidden = true;
      }
    }
  }

  function poll() {
    if (document.hidden) {
      window.setTimeout(poll, 6000);
      return;
    }
    fetch("/api/admin/state", {
      headers: { Accept: "application/json" },
      cache: "no-store"
    })
      .then(function (response) {
        if (response.status === 401) {
          window.location.href = "/admin/login";
          return null;
        }
        if (!response.ok) return null;
        return response.json();
      })
      .then(function (state) {
        if (state) apply(state);
      })
      .catch(function () {})
      .then(function () {
        window.setTimeout(poll, 3000);
      });
  }

  window.setTimeout(poll, 1500);
})();
