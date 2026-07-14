/* DayZ Dashboard – Frontend-Logik */
(function () {
  "use strict";

  // ── Helpers ───────────────────────────────────────────────
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  function h(tag, attrs, kids) {
    var e = document.createElement(tag);
    attrs = attrs || {};
    for (var k in attrs) {
      if (k === "class") e.className = attrs[k];
      else if (k === "html") e.innerHTML = attrs[k];
      else if (k.slice(0, 2) === "on") e.addEventListener(k.slice(2), attrs[k]);
      else if (attrs[k] != null) e.setAttribute(k, attrs[k]);
    }
    (kids || []).forEach(function (c) {
      if (c == null) return;
      e.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    });
    return e;
  }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }

  var toastT;
  function toast(msg, kind) {
    var t = $("#toast"); t.textContent = msg;
    t.className = "toast " + (kind || "");
    clearTimeout(toastT); toastT = setTimeout(function () { t.classList.add("hidden"); }, 3200);
  }

  async function api(method, path, bodyObj) {
    var opt = { method: method, headers: {} };
    if (bodyObj !== undefined) { opt.headers["Content-Type"] = "application/json";
      opt.body = JSON.stringify(bodyObj); }
    var r = await fetch(path, opt);
    if (r.status === 401) { showOnboarding(); throw new Error("unauthorized"); }
    var j = await r.json().catch(function () { return {}; });
    if (!r.ok || j.ok === false) throw new Error(j.error || j.message || ("HTTP " + r.status));
    return j.data !== undefined ? j.data : j;
  }

  function modal(title, contentNode, onSave, saveLabel) {
    var bg = h("div", { class: "modal-bg" });
    var save = h("button", { class: "btn primary", onclick: async function () {
      try { await onSave(); document.body.removeChild(bg); }
      catch (e) { toast(e.message, "bad"); } } }, [saveLabel || "Speichern"]);
    var box = h("div", { class: "modal" }, [
      h("h3", {}, [title]), contentNode,
      h("div", { class: "modal-actions" }, [
        h("button", { class: "btn ghost", onclick: function () { document.body.removeChild(bg); } }, ["Abbrechen"]),
        onSave ? save : null])]);
    bg.appendChild(box);
    bg.addEventListener("click", function (e) { if (e.target === bg) document.body.removeChild(bg); });
    document.body.appendChild(bg);
    return bg;
  }

  // ── State ─────────────────────────────────────────────────
  var state = { guilds: [], gid: null, eventTypes: [], filters: {}, showPlayers: true,
                mapLoaded: false, pollTimer: null, view: "overview" };

  // ── Onboarding ────────────────────────────────────────────
  function showOnboarding() {
    $("#app").classList.add("hidden");
    $("#onboarding").classList.remove("hidden");
    $("#ob-step-server").classList.add("hidden");
    $("#ob-step-token").classList.remove("hidden");
  }
  function showApp() {
    $("#onboarding").classList.add("hidden");
    $("#app").classList.remove("hidden");
  }

  $("#ob-token-btn").addEventListener("click", async function () {
    var tok = $("#ob-token").value.trim();
    $("#ob-token-err").textContent = "";
    if (!tok) { $("#ob-token-err").textContent = "Bitte Token eingeben."; return; }
    this.disabled = true; this.textContent = "Prüfe …";
    try {
      var d = await api("POST", "/api/auth/token", { token: tok });
      var sel = $("#ob-server"); sel.innerHTML = "";
      d.servers.forEach(function (s) {
        sel.appendChild(h("option", { value: s.id }, [s.name + " (" + s.status + ")"]));
      });
      $("#ob-step-token").classList.add("hidden");
      $("#ob-step-server").classList.remove("hidden");
    } catch (e) { $("#ob-token-err").textContent = e.message; }
    this.disabled = false; this.textContent = "Token prüfen & bestätigen";
  });

  $("#ob-server-btn").addEventListener("click", async function () {
    var sid = $("#ob-server").value;
    $("#ob-server-err").textContent = "";
    $("#ob-server-busy").classList.remove("hidden");
    this.disabled = true;
    try {
      var d = await api("POST", "/api/auth/select-server", { service_id: sid });
      if (d.warnings && d.warnings.length) toast(d.warnings.join(" · "), "bad");
      showApp(); await boot(); setView("overview");
    } catch (e) { $("#ob-server-err").textContent = e.message; }
    $("#ob-server-busy").classList.add("hidden"); this.disabled = false;
  });

  $("#btn-logout").addEventListener("click", async function () {
    try { await api("POST", "/api/auth/logout"); } catch (e) {}
    showOnboarding();
  });

  // ── Status ────────────────────────────────────────────────
  async function refreshStatus() {
    try {
      var s = await api("GET", "/api/server/status");
      var pill = $("#status-pill");
      pill.textContent = s.online ? "● Online" : "○ Offline";
      pill.className = "pill " + (s.online ? "online" : "offline");
      $("#status-map").textContent = s.map_name || "—";
      var pc = s.a2s ? (s.a2s.players + "/" + s.a2s.max_players) :
               (s.nitrado && s.nitrado.players != null ? s.nitrado.players : "—");
      $("#status-players").textContent = "👥 " + pc;
    } catch (e) {}
  }
  $("#btn-refresh-status").addEventListener("click", refreshStatus);

  // ── Navigation ────────────────────────────────────────────
  var renderers = {};
  function setView(name) {
    state.view = name;
    $$(".nav").forEach(function (b) { b.classList.toggle("active", b.dataset.view === name); });
    $$(".view").forEach(function (v) { v.classList.toggle("hidden", v.dataset.section !== name); });
    if (name !== "map" && state.pollTimer) { clearInterval(state.pollTimer); state.pollTimer = null; }
    if (renderers[name]) renderers[name]();
  }
  $$(".nav").forEach(function (b) {
    b.addEventListener("click", function () { setView(b.dataset.view); });
  });

  // ══════════ OVERVIEW ══════════
  renderers.overview = async function () {
    var c = $('[data-section="overview"]');
    c.innerHTML = "";
    c.appendChild(h("h2", {}, ["Übersicht"]));
    c.appendChild(h("p", { class: "sub" }, ["Willkommen im DayZ-Server-Dashboard."]));
    var stats = h("div", { class: "grid stats" });
    c.appendChild(stats);
    function stat(n, l) { stats.appendChild(h("div", { class: "stat" },
      [h("div", { class: "n" }, [String(n)]), h("div", { class: "l" }, [l])])); }
    try {
      var z = await api("GET", "/api/zones");
      var sh = await api("GET", "/api/shop/items?page_size=1");
      var ar = await api("GET", "/api/auto-restart");
      stat(z.zones.length, "Zonen");
      stat(z.map_name, "Aktive Karte");
      stat(sh.total, "Shop-Einträge");
      stat(ar.schedule.enabled ? "AN" : "AUS", "Auto-Restart");
    } catch (e) {}
    var quick = h("div", { class: "card" }, [h("h3", {}, ["Schnellzugriff"])]);
    ["feeds", "zones", "shop", "map"].forEach(function (v) {
      quick.appendChild(h("button", { class: "btn", style: "margin:4px",
        onclick: function () { setView(v); } }, [v]));
    });
    c.appendChild(quick);
  };

  // ══════════ FEEDS ══════════
  renderers.feeds = async function () {
    var c = $('[data-section="feeds"]'); c.innerHTML = "";
    c.appendChild(h("h2", {}, ["Feeds"]));
    c.appendChild(h("p", { class: "sub" }, ["Lege pro Log-Typ den Discord-Channel fest, in den gepostet wird."]));
    var d = await api("GET", "/api/feeds");
    if (!d.guilds.length) { c.appendChild(h("div", { class: "card" }, ["Keine Guilds konfiguriert."])); return; }
    d.guilds.forEach(function (g) {
      var card = h("div", { class: "card" }, [h("h3", {}, [g.name + (g.available ? "" : " (Bot offline?)")])]);
      d.log_types.forEach(function (lt) {
        var sel = h("select", {});
        sel.appendChild(h("option", { value: "" }, ["— kein Channel —"]));
        g.channels.forEach(function (ch) {
          var o = h("option", { value: ch.id }, ["#" + ch.name]);
          if (g.feeds[lt.key] === ch.id) o.selected = true;
          sel.appendChild(o);
        });
        if (!g.channels.length && g.feeds[lt.key])
          sel.appendChild(h("option", { value: g.feeds[lt.key], selected: "selected" }, ["Channel " + g.feeds[lt.key]]));
        sel.addEventListener("change", async function () {
          try { await api("POST", "/api/feeds/" + g.id + "/" + lt.key, { channel_id: sel.value || null });
            toast("Gespeichert: " + lt.label, "ok"); } catch (e) { toast(e.message, "bad"); }
        });
        card.appendChild(h("div", { class: "feed-row" }, [
          h("div", { class: "label" }, [lt.label, h("small", {}, [lt.key])]), sel]));
      });
      c.appendChild(card);
    });
  };

  // ══════════ ZONES ══════════
  async function loadGuildPickers(gid) {
    var ch = { channels: [] }, ro = { roles: [] };
    try { ch = await api("GET", "/api/guild/" + gid + "/channels"); } catch (e) {}
    try { ro = await api("GET", "/api/guild/" + gid + "/roles"); } catch (e) {}
    return { channels: ch.channels, roles: ro.roles };
  }

  function zoneModal(prefill) {
    prefill = prefill || {};
    var name = h("input", { value: prefill.name || "", placeholder: "Zonen-Name" });
    var x = h("input", { type: "number", step: "0.1", value: prefill.x != null ? prefill.x : "" });
    var z = h("input", { type: "number", step: "0.1", value: prefill.z != null ? prefill.z : "" });
    var rad = h("input", { type: "number", step: "1", value: prefill.radius != null ? prefill.radius : 250 });
    var chSel = h("select", {}, [h("option", { value: "" }, ["— kein Channel —"])]);
    var roSel = h("select", {}, [h("option", { value: "" }, ["— keine Rolle —"])]);
    loadGuildPickers(state.gid).then(function (p) {
      p.channels.forEach(function (ch) { chSel.appendChild(h("option", { value: ch.id }, ["#" + ch.name])); });
      p.roles.forEach(function (r) { roSel.appendChild(h("option", { value: r.id }, ["@" + r.name])); });
    });
    var body = h("div", {}, [
      lbl("Name", name),
      h("div", { class: "grid two" }, [lbl("X (Ost)", x), lbl("Z (Nord)", z)]),
      lbl("Radius (m)", rad),
      lbl("Warn-Channel (optional)", chSel),
      lbl("Ping-Rolle (optional)", roSel),
      h("p", { class: "muted", style: "font-size:12px" },
        ["Tipp: Über „Auf Karte zeichnen“ setzt du X/Z/Radius bequem per Kreis."])]);
    modal(prefill.name ? "Zone bearbeiten" : "Zone anlegen", body, async function () {
      var payload = { name: name.value.trim(), x: parseFloat(x.value), z: parseFloat(z.value),
        radius: parseFloat(rad.value), channel_id: chSel.value || null, role_id: roSel.value || null,
        guild_id: state.gid };
      if (prefill.editName) await api("PUT", "/api/zones/" + encodeURIComponent(prefill.editName), payload);
      else await api("POST", "/api/zones", payload);
      toast("Zone gespeichert", "ok"); renderers.zones();
    });
  }
  function lbl(text, node) { return h("label", { class: "field" }, [h("span", {}, [text]), node]); }
  function hrow(cols) { return h("tr", {}, cols.map(function (t) { return h("th", {}, [t]); })); }

  renderers.zones = async function () {
    var c = $('[data-section="zones"]'); c.innerHTML = "";
    c.appendChild(h("h2", {}, ["Zones"]));
    c.appendChild(h("p", { class: "sub" }, ["Überwachte Zonen – der Bot pingt, solange ein Spieler darin steht."]));
    var d = await api("GET", "/api/zones");
    var actions = h("div", { class: "row", style: "margin-bottom:14px" }, [
      h("button", { class: "btn primary", onclick: function () { zoneModal(); } }, ["+ Zone"]),
      h("button", { class: "btn", onclick: function () { drawZoneOnMap(); } }, ["🗺️ Auf Karte zeichnen"])]);
    c.appendChild(actions);
    var tb = h("tbody", {});
    d.zones.forEach(function (zn) {
      tb.appendChild(h("tr", {}, [
        h("td", {}, [zn.name]), h("td", {}, [String(zn.x)]), h("td", {}, [String(zn.z)]),
        h("td", {}, [zn.radius + " m"]),
        h("td", {}, [
          h("button", { class: "btn small", onclick: function () {
            zoneModal({ name: zn.name, editName: zn.name, x: zn.x, z: zn.z, radius: zn.radius }); } }, ["✎"]),
          h("button", { class: "btn small danger", style: "margin-left:6px", onclick: async function () {
            if (!confirm("Zone „" + zn.name + "“ löschen?")) return;
            await api("DELETE", "/api/zones/" + encodeURIComponent(zn.name)); toast("Gelöscht", "ok"); renderers.zones();
          } }, ["🗑"])])]));
    });
    var tbl = h("table", {}, [h("thead", {}, [hrow(["Name", "X", "Z", "Radius", ""])]), tb]);
    c.appendChild(h("div", { class: "card" }, [d.zones.length ? tbl : h("div", { class: "muted" }, ["Noch keine Zonen."])]));
  };

  function drawZoneOnMap() {
    setView("map");
    toast("Klicke das Zentrum, dann einen zweiten Punkt für den Radius.", "ok");
    var iv = setInterval(function () {
      if (state.mapLoaded) { clearInterval(iv);
        window.DZMap.startDraw(function (res) { setView("zones");
          zoneModal({ x: res.x, z: res.z, radius: res.radius }); });
      }
    }, 120);
  }

  // ══════════ AUTO-AUFGABEN ══════════
  renderers.autotasks = async function () {
    var c = $('[data-section="autotasks"]'); c.innerHTML = "";
    c.appendChild(h("h2", {}, ["Auto-Aufgaben"]));
    c.appendChild(h("p", { class: "sub" }, ["Automatische Server-Neustarts planen (Ankündigungen 15/5/1 Min vorher)."]));
    var d = await api("GET", "/api/auto-restart");
    var en = h("input", { type: "checkbox" }); en.checked = d.schedule.enabled;
    var ft = h("input", { type: "time", value: d.schedule.first_time || "04:00" });
    var iv = h("input", { type: "number", min: "1", max: "24", value: d.schedule.interval_hours || 4 });
    var ap = h("input", { type: "checkbox" }); ap.checked = d.after_purchase;
    var nxt = h("div", { class: "muted" }, [d.next_run_ts ?
      "Nächster Neustart: " + new Date(d.next_run_ts * 1000).toLocaleString() : "Kein Neustart geplant."]);
    var card = h("div", { class: "card" }, [
      h("label", { class: "chk" }, [en, " Automatische Neustarts aktiv"]),
      h("div", { class: "grid two", style: "margin-top:10px" }, [
        lbl("Erste Startzeit (HH:MM)", ft), lbl("Intervall (Stunden, 1–24)", iv)]),
      h("label", { class: "chk", style: "margin-top:8px" }, [ap, " Nach jedem Shop-Kauf automatisch neustarten"]),
      h("div", { class: "row", style: "margin-top:14px" }, [
        h("button", { class: "btn primary", onclick: async function () {
          try { var r = await api("POST", "/api/auto-restart", { enabled: en.checked,
              first_time: ft.value, interval_hours: parseInt(iv.value, 10), after_purchase: ap.checked });
            toast("Zeitplan gespeichert", "ok");
            nxt.textContent = r.next_run_ts ? "Nächster Neustart: " + new Date(r.next_run_ts * 1000).toLocaleString() : "Kein Neustart geplant.";
          } catch (e) { toast(e.message, "bad"); } } }, ["Speichern"])]),
      h("div", { style: "margin-top:10px" }, [nxt])]);
    c.appendChild(card);
  };

  // ══════════ SHOP ══════════
  function classnameField(initial) {
    var wrap = h("div", { class: "item-line" });
    var inp = h("input", { value: initial || "", placeholder: "Classname (z. B. M4A1)", autocomplete: "off" });
    var rm = h("button", { class: "btn small danger", onclick: function () { wrap.remove(); } }, ["×"]);
    var box = null, timer = null;
    function close() { if (box) { box.remove(); box = null; } }
    inp.addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(async function () {
        close();
        try {
          var d = await api("GET", "/api/shop/classnames?q=" + encodeURIComponent(inp.value.trim()));
          if (!d.classnames.length) return;
          box = h("div", { class: "ac-box" });
          d.classnames.forEach(function (cn) {
            box.appendChild(h("div", { class: "ac-item", onclick: function () {
              inp.value = cn.classname; close(); } },
              [cn.classname, h("small", {}, [cn.name + " · " + cn.category])]));
          });
          wrap.appendChild(box);
        } catch (e) {}
      }, 180);
    });
    inp.addEventListener("blur", function () { setTimeout(close, 180); });
    wrap.appendChild(inp); wrap.appendChild(rm);
    wrap._value = function () { return inp.value.trim(); };
    return wrap;
  }

  async function bundleModal() {
    var cats = await api("GET", "/api/shop/categories");
    var name = h("input", { placeholder: "Name der Shopliste / des Bundles" });
    var catSel = h("select", {});
    cats.categories.forEach(function (ct) { catSel.appendChild(h("option", { value: ct.name }, [ct.name + " (" + ct.count + ")"])); });
    var addCat = h("button", { class: "btn small", onclick: async function () {
      var nn = prompt("Name der neuen Kategorie:"); if (!nn) return;
      try { await api("POST", "/api/shop/categories", { name: nn.trim() });
        catSel.appendChild(h("option", { value: nn.trim(), selected: "selected" }, [nn.trim()]));
        toast("Kategorie angelegt", "ok"); } catch (e) { toast(e.message, "bad"); } } }, ["+ Neue Kategorie"]);
    var price = h("input", { type: "number", min: "0", value: cats.default_price || 100 });
    var limit = h("input", { type: "number", min: "1", value: 1 });
    var itemsWrap = h("div", {});
    itemsWrap.appendChild(classnameField());
    var addItem = h("button", { class: "btn small", onclick: function () {
      itemsWrap.appendChild(classnameField()); } }, ["+ Item"]);
    var body = h("div", {}, [
      lbl("Name für Shopliste", name),
      h("label", { class: "field" }, [h("span", {}, ["Kategorie"]),
        h("div", { class: "row" }, [h("div", { style: "flex:1" }, [catSel]), addCat])]),
      h("label", { class: "field" }, [h("span", {}, ["Items (mit Autofill, mehrere möglich)"]), itemsWrap, addItem]),
      h("div", { class: "grid two" }, [lbl("Preis (gesamt)", price), lbl("Limit (max/Kauf)", limit)])]);
    modal("🛒 Shop-Bundle erstellen", body, async function () {
      var classnames = $$(".item-line", itemsWrap).map(function (w) { return w._value(); }).filter(Boolean);
      if (!classnames.length) throw new Error("Mindestens einen Classname angeben.");
      if (!name.value.trim()) throw new Error("Name fehlt.");
      var r = await api("POST", "/api/shop/items", { name: name.value.trim(), category: catSel.value,
        classnames: classnames, price: parseInt(price.value, 10), max_amount_per_buy: parseInt(limit.value, 10) });
      if (r.unknown_classnames && r.unknown_classnames.length)
        toast("Hinweis: unbekannte Classnames – " + r.unknown_classnames.join(", "), "bad");
      else toast("Bundle gespeichert", "ok");
      renderers.shop();
    }, "Bundle anlegen");
  }

  var shopState = { q: "", cat: "", page: 1 };
  renderers.shop = async function () {
    var c = $('[data-section="shop"]'); c.innerHTML = "";
    c.appendChild(h("h2", {}, ["Shop"]));
    c.appendChild(h("p", { class: "sub" }, ["Katalog aus Items & Bundles – kaufbar im Spiel per /buy."]));
    var cats = await api("GET", "/api/shop/categories");
    var q = h("input", { placeholder: "Suche…", value: shopState.q, style: "max-width:260px" });
    var catSel = h("select", { style: "max-width:220px" }, [h("option", { value: "" }, ["Alle Kategorien"])]);
    cats.categories.forEach(function (ct) { var o = h("option", { value: ct.name }, [ct.name + " (" + ct.count + ")"]);
      if (ct.name === shopState.cat) o.selected = true; catSel.appendChild(o); });
    q.addEventListener("input", function () { shopState.q = q.value; shopState.page = 1; loadItems(); });
    catSel.addEventListener("change", function () { shopState.cat = catSel.value; shopState.page = 1; loadItems(); });
    c.appendChild(h("div", { class: "row between", style: "margin-bottom:14px" }, [
      h("div", { class: "row" }, [q, catSel]),
      h("button", { class: "btn primary", onclick: bundleModal }, ["🛒 Shop-Bundle erstellen"])]));
    var listCard = h("div", { class: "card" }); c.appendChild(listCard);
    async function loadItems() {
      listCard.innerHTML = "";
      var d = await api("GET", "/api/shop/items?page_size=100&page=" + shopState.page +
        "&q=" + encodeURIComponent(shopState.q) + "&category=" + encodeURIComponent(shopState.cat));
      listCard.appendChild(h("div", { class: "muted", style: "margin-bottom:8px" },
        [d.total + " Einträge · Quelle: " + d.source]));
      var tb = h("tbody", {});
      d.items.forEach(function (it) {
        tb.appendChild(h("tr", {}, [
          h("td", {}, [it.name, it.is_bundle ? h("span", { class: "tag" }, ["Bundle ×" + it.classnames.length]) : null,
            it.custom ? h("span", { class: "tag" }, ["custom"]) : null]),
          h("td", {}, [it.category]),
          h("td", {}, [String(it.price)]),
          h("td", {}, [String(it.max_amount_per_buy)]),
          h("td", {}, [h("span", { class: it.enabled ? "badge-on" : "badge-off" }, [it.enabled ? "aktiv" : "aus"])]),
          h("td", {}, [
            h("button", { class: "btn small", onclick: async function () {
              await api("PUT", "/api/shop/items/" + encodeURIComponent(it.name), { enabled: !it.enabled });
              loadItems(); } }, [it.enabled ? "deaktiv." : "aktiv."]),
            it.custom ? h("button", { class: "btn small danger", style: "margin-left:6px", onclick: async function () {
              if (!confirm("„" + it.name + "“ löschen?")) return;
              await api("DELETE", "/api/shop/items/" + encodeURIComponent(it.name)); loadItems(); } }, ["🗑"]) : null])]));
      });
      var head = h("tr", {});
      ["Name", "Kategorie", "Preis", "Limit", "Status", ""].forEach(function (t) { head.appendChild(h("th", {}, [t])); });
      listCard.appendChild(h("table", {}, [h("thead", {}, [head]), tb]));
      var pages = Math.max(1, Math.ceil(d.total / d.page_size));
      listCard.appendChild(h("div", { class: "row", style: "margin-top:10px" }, [
        h("button", { class: "btn small", onclick: function () { if (shopState.page > 1) { shopState.page--; loadItems(); } } }, ["‹"]),
        h("span", { class: "muted" }, ["Seite " + d.page + " / " + pages]),
        h("button", { class: "btn small", onclick: function () { if (shopState.page < pages) { shopState.page++; loadItems(); } } }, ["›"])]));
    }
    loadItems();
  };

  // ══════════ KARTE ══════════
  $("#map-panel-toggle").addEventListener("click", function () {
    var p = $("#map-panel"); p.classList.toggle("collapsed");
    this.textContent = p.classList.contains("collapsed") ? "⟩" : "⟨";
    window.DZMap.invalidate();
  });
  $("#flt-players").addEventListener("change", function () { state.showPlayers = this.checked; pollMap(); });
  $("#map-refresh").addEventListener("click", function () { pollMap(); });

  function buildFilters() {
    var box = $("#map-filters"); box.innerHTML = "";
    window.EVENT_COLORS = {};
    state.eventTypes.forEach(function (t) {
      window.EVENT_COLORS[t.type] = { color: t.color };
      if (state.filters[t.type] === undefined) state.filters[t.type] = t.default;
      var row = h("div", { class: "flt" + (state.filters[t.type] ? "" : " off") }, [
        h("span", { class: "dot", style: "background:" + t.color }),
        h("span", {}, [t.emoji + " " + t.label]),
        h("span", { class: "cnt", "data-cnt": t.type }, ["0"])]);
      row.addEventListener("click", function () {
        state.filters[t.type] = !state.filters[t.type];
        row.classList.toggle("off", !state.filters[t.type]);
        renderMapEvents();
      });
      box.appendChild(row);
    });
  }

  var mapEventsCache = [];
  function renderMapEvents() {
    window.DZMap.renderEvents(mapEventsCache, state.filters);
    var counts = {};
    mapEventsCache.forEach(function (e) { counts[e.type] = (counts[e.type] || 0) + 1; });
    $$("[data-cnt]").forEach(function (el) { el.textContent = counts[el.getAttribute("data-cnt")] || 0; });
    renderEventList();
  }

  function renderEventList() {
    var box = $("#event-list"); box.innerHTML = "";
    var list = mapEventsCache.filter(function (e) { return state.filters[e.type]; }).slice(-60).reverse();
    if (!list.length) { box.appendChild(h("div", { class: "muted", style: "padding:8px" }, ["Noch keine Events."])); return; }
    list.forEach(function (e) {
      var meta = state.eventTypes.filter(function (t) { return t.type === e.type; })[0] || {};
      box.appendChild(h("div", { class: "ev", onclick: function () { if (typeof e.x === "number") window.DZMap.focus(e.x, e.z); } }, [
        h("span", { class: "ico" }, [meta.emoji || "•"]),
        h("span", { class: "tx", html: "<b>" + esc(meta.label || e.type) + "</b> · " + esc(e.summary || "") }),
        h("span", { class: "tm" }, [e.time || ""])]));
    });
  }

  async function pollMap() {
    try {
      var ev = await api("GET", "/api/events?since=0");
      mapEventsCache = ev.events || [];
      renderMapEvents();
      if (state.showPlayers) { var pl = await api("GET", "/api/map/players");
        window.DZMap.setPlayers(pl.players, true); } else window.DZMap.setPlayers([], false);
    } catch (e) {}
  }

  renderers.map = async function () {
    if (!state.mapLoaded) {
      var meta = await api("GET", "/api/map/meta");
      var types = await api("GET", "/api/events/types");
      state.eventTypes = types.types;
      window.DZMap.load(meta);
      buildFilters();
      state.mapLoaded = true;
      try { var z = await api("GET", "/api/zones"); window.DZMap.setZones(z.zones); } catch (e) {}
    } else { window.DZMap.invalidate(); }
    await pollMap();
    if (state.pollTimer) clearInterval(state.pollTimer);
    state.pollTimer = setInterval(pollMap, 7000);
  };

  // ══════════ BANS / WHITELIST ══════════
  function listManager(section, path, title, sub) {
    renderers[section] = async function () {
      var c = $('[data-section="' + section + '"]'); c.innerHTML = "";
      c.appendChild(h("h2", {}, [title]));
      c.appendChild(h("p", { class: "sub" }, [sub]));
      var inp = h("input", { placeholder: "Spielername", style: "max-width:260px" });
      c.appendChild(h("div", { class: "row", style: "margin-bottom:14px" }, [inp,
        h("button", { class: "btn primary", onclick: async function () {
          if (!inp.value.trim()) return;
          try { await api("POST", path, { player: inp.value.trim() }); toast("Hinzugefügt", "ok"); render(); }
          catch (e) { toast(e.message, "bad"); } } }, ["Hinzufügen"])]));
      var card = h("div", { class: "card" }, ["Lade …"]); c.appendChild(card);
      async function render() {
        card.innerHTML = "";
        try {
          var d = await api("GET", path);
          if (!d.names.length) { card.appendChild(h("div", { class: "muted" }, ["Liste ist leer."])); return; }
          d.names.forEach(function (n) {
            card.appendChild(h("div", { class: "row between", style: "padding:6px 0;border-bottom:1px solid var(--line)" }, [
              h("span", {}, [n]),
              h("button", { class: "btn small danger", onclick: async function () {
                await api("DELETE", path + "/" + encodeURIComponent(n)); toast("Entfernt", "ok"); render(); } }, ["Entfernen"])]));
          });
        } catch (e) { card.appendChild(h("div", { class: "err" }, [e.message])); }
      }
      render();
    };
  }
  listManager("bans", "/api/bans", "Bans", "Ban-Liste des Nitrado-Servers (wie im Web-Interface).");
  listManager("whitelist", "/api/whitelist", "Whitelist", "Whitelist des Nitrado-Servers.");

  // ══════════ ECONOMY ══════════
  renderers.economy = async function () {
    var c = $('[data-section="economy"]'); c.innerHTML = "";
    c.appendChild(h("h2", {}, ["Economy"]));
    c.appendChild(h("p", { class: "sub" }, ["Guthaben der Spieler ansehen und anpassen."]));
    var card = h("div", { class: "card" }, ["Lade …"]); c.appendChild(card);
    try {
      var d = await api("GET", "/api/economy/balances");
      card.innerHTML = "";
      var head = h("tr", {}); ["Ingame", "User-ID", "Wallet", "Bank", ""].forEach(function (t) { head.appendChild(h("th", {}, [t])); });
      var tb = h("tbody", {});
      d.balances.forEach(function (b) {
        tb.appendChild(h("tr", {}, [
          h("td", {}, [b.ingame || "—"]), h("td", {}, [b.user_id]),
          h("td", {}, [b.wallet + " " + d.symbol]), h("td", {}, [b.bank + " " + d.symbol]),
          h("td", {}, [h("button", { class: "btn small", onclick: function () { moneyModal(d.guild_id, b, d.symbol); } }, ["±"])])]));
      });
      card.appendChild(d.balances.length ? h("table", {}, [h("thead", {}, [head]), tb]) : h("div", { class: "muted" }, ["Keine Guthaben-Daten."]));
    } catch (e) { card.innerHTML = ""; card.appendChild(h("div", { class: "err" }, [e.message])); }
  };
  function moneyModal(gid, b, sym) {
    var amt = h("input", { type: "number", value: 100 });
    var op = h("select", {}, [h("option", { value: "add" }, ["Hinzufügen"]),
      h("option", { value: "remove" }, ["Abziehen"]), h("option", { value: "set" }, ["Setzen"])]);
    modal("Guthaben ändern – " + (b.ingame || b.user_id), h("div", {}, [lbl("Aktion", op), lbl("Betrag (" + sym + ")", amt)]),
      async function () { await api("POST", "/api/economy/money", { guild_id: parseInt(gid, 10),
        user_id: parseInt(b.user_id, 10), op: op.value, amount: parseInt(amt.value, 10) });
        toast("Geändert", "ok"); renderers.economy(); });
  }

  // ══════════ ANKÜNDIGUNGEN ══════════
  renderers.announce = async function () {
    var c = $('[data-section="announce"]'); c.innerHTML = "";
    c.appendChild(h("h2", {}, ["Ankündigungen"]));
    c.appendChild(h("p", { class: "sub" }, ["Wiederkehrende Nachrichten planen."]));
    c.appendChild(h("div", { class: "row", style: "margin-bottom:14px" }, [
      h("button", { class: "btn primary", onclick: announceModal }, ["+ Ankündigung"])]));
    var card = h("div", { class: "card" }, ["Lade …"]); c.appendChild(card);
    try {
      var d = await api("GET", "/api/announcements");
      card.innerHTML = "";
      if (!d.announcements.length) { card.appendChild(h("div", { class: "muted" }, ["Keine Ankündigungen."])); return; }
      d.announcements.forEach(function (a) {
        card.appendChild(h("div", { class: "row between", style: "padding:8px 0;border-bottom:1px solid var(--line)" }, [
          h("div", {}, [h("b", {}, [a.day + " " + a.time + " · " + a.repeat]),
            h("div", { class: "muted", html: esc(a.message) })]),
          h("button", { class: "btn small danger", onclick: async function () {
            await api("DELETE", "/api/announcements/" + a.index); toast("Gelöscht", "ok"); renderers.announce(); } }, ["🗑"])]));
      });
    } catch (e) { card.innerHTML = ""; card.appendChild(h("div", { class: "err" }, [e.message])); }
  };
  async function announceModal() {
    var days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];
    var daySel = h("select", {}, days.map(function (d) { return h("option", { value: d }, [d]); }));
    var time = h("input", { type: "time", value: "18:00" });
    var rep = h("select", {}, ["weekly", "biweekly", "triweekly", "monthly"].map(function (r) { return h("option", { value: r }, [r]); }));
    var msg = h("textarea", { rows: "3", placeholder: "Nachricht" });
    var chSel = h("select", {}, [h("option", { value: "" }, ["— Channel wählen —"])]);
    loadGuildPickers(state.gid).then(function (p) { p.channels.forEach(function (ch) {
      chSel.appendChild(h("option", { value: ch.id }, ["#" + ch.name])); }); });
    modal("Ankündigung anlegen", h("div", {}, [
      h("div", { class: "grid two" }, [lbl("Wochentag", daySel), lbl("Uhrzeit", time)]),
      lbl("Wiederholung", rep), lbl("Channel", chSel), lbl("Nachricht", msg)]),
      async function () { await api("POST", "/api/announcements", { day: daySel.value, time: time.value,
        repeat: rep.value, channel_id: chSel.value, message: msg.value.trim() });
        toast("Angelegt", "ok"); renderers.announce(); });
  }

  // ══════════ SERVER ══════════
  renderers.server = async function () {
    var c = $('[data-section="server"]'); c.innerHTML = "";
    c.appendChild(h("h2", {}, ["Server"]));
    c.appendChild(h("p", { class: "sub" }, ["Status & Steuerung des Nitrado-Servers."]));
    var status = h("div", { class: "card" }, ["Lade Status …"]); c.appendChild(status);
    c.appendChild(h("div", { class: "card" }, [
      h("h3", {}, ["Steuerung"]),
      h("div", { class: "row" }, [
        h("button", { class: "btn primary", onclick: async function () {
          if (!confirm("Server jetzt neustarten?")) return;
          try { var r = await api("POST", "/api/server/restart"); toast(r.message || "Neustart ausgelöst", "ok"); }
          catch (e) { toast(e.message, "bad"); } } }, ["🔄 Neustarten"]),
        h("button", { class: "btn danger", onclick: async function () {
          if (!confirm("Server stoppen?")) return;
          try { var r = await api("POST", "/api/server/stop"); toast(r.message || "Gestoppt", "ok"); }
          catch (e) { toast(e.message, "bad"); } } }, ["⏹️ Stoppen"])])]));
    try {
      var s = await api("GET", "/api/server/status"); status.innerHTML = "";
      status.appendChild(h("div", { class: "grid stats" }, [
        stat2(s.online ? "Online" : "Offline", "Status"),
        stat2(s.map_name || "—", "Karte"),
        stat2(s.a2s ? (s.a2s.players + "/" + s.a2s.max_players) : (s.nitrado && s.nitrado.players != null ? s.nitrado.players : "—"), "Spieler"),
        stat2(s.server_ip || "—", "Server-IP")]));
    } catch (e) { status.innerHTML = ""; status.appendChild(h("div", { class: "err" }, [e.message])); }
  };
  function stat2(n, l) { return h("div", { class: "stat" }, [h("div", { class: "n" }, [String(n)]), h("div", { class: "l" }, [l])]); }

  // ── Boot ──────────────────────────────────────────────────
  async function boot() {
    try { var f = await api("GET", "/api/feeds"); state.guilds = f.guilds;
      state.gid = f.guilds.length ? parseInt(f.guilds[0].id, 10) : null; } catch (e) {}
    refreshStatus();
    setInterval(refreshStatus, 30000);
  }

  (async function init() {
    try {
      var s = await api("GET", "/api/session");
      if (s.authed) { showApp(); await boot(); setView("overview"); }
      else showOnboarding();
    } catch (e) { showOnboarding(); }
  })();
})();
