/* DayZ Bot Dashboard – Hauptlogik (Login, Views, State-Polling, Befehle) */
"use strict";

(() => {
  const $  = (sel) => document.querySelector(sel);
  const $$ = (sel) => [...document.querySelectorAll(sel)];

  const S = {
    sid:        localStorage.getItem("dz_service") || "",
    mapName:    localStorage.getItem("dz_map") || "ChernarusPlus",
    serverName: localStorage.getItem("dz_server_name") || "",
    dir:     null,   // FTP-Verzeichnis mit den Dashboard-Dateien
    info:    null,   // Nitrado-Gameserver-Info
    state:   null,   // dashboard_state.json
    catalog: null,   // dashboard_catalog.json
    pending: new Map(),          // Befehls-ID → Beschreibung (wartet auf Bot)
    filters: null,               // Set aktiver Event-Typen (Karte)
    editingZone: null,           // Name der Zone im Bearbeiten-Modus
    zonesMap: null, eventsMap: null,
    pollTimer: null,
  };

  /* ── Toasts ─────────────────────────────────────────── */
  function toast(msg, cls = "") {
    const el = document.createElement("div");
    el.className = "toast " + cls;
    el.textContent = msg;
    $("#toast-area").appendChild(el);
    setTimeout(() => el.remove(), 7000);
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g,
      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  /* ══════════ Login: Token → Server-Auswahl ══════════ */
  async function confirmToken() {
    const tok = $("#token-input").value.trim();
    const err = $("#login-error");
    err.classList.add("hidden");
    if (!tok) return;
    localStorage.setItem("dz_token", tok);
    $("#token-confirm").disabled = true;
    try {
      const services = await Nitrado.listServices();
      if (!services.length) throw new Error("Keine Gameserver unter diesem Token gefunden");
      const sel = $("#server-select");
      sel.innerHTML = "";
      for (const s of services) {
        const d = s.details || {};
        const opt = document.createElement("option");
        opt.value = String(s.id);
        opt.textContent = `${d.name || d.game || "Server"} (ID ${s.id})`;
        sel.appendChild(opt);
      }
      $("#login-step-token").classList.add("hidden");
      $("#login-step-server").classList.remove("hidden");
    } catch (e) {
      err.textContent = "❌ " + e.message + " – Token prüfen.";
      err.classList.remove("hidden");
    } finally {
      $("#token-confirm").disabled = false;
    }
  }

  async function confirmServer() {
    const sid = $("#server-select").value;
    if (!sid) return;
    $("#server-confirm").disabled = true;
    $("#server-info").textContent = "🔎 Server wird geprüft, Karte wird erkannt…";
    try {
      const info = await Nitrado.gameserver(sid);
      S.sid  = sid;
      S.info = info;
      S.mapName = Nitrado.detectMap(info) || "ChernarusPlus";
      S.serverName = $("#server-select").selectedOptions[0].textContent;
      localStorage.setItem("dz_service", sid);
      localStorage.setItem("dz_map", S.mapName);
      localStorage.setItem("dz_server_name", S.serverName);
      await enterApp();
    } catch (e) {
      $("#server-info").textContent = "❌ " + e.message;
    } finally {
      $("#server-confirm").disabled = false;
    }
  }

  function logout(clearToken) {
    clearInterval(S.pollTimer);
    if (clearToken) localStorage.removeItem("dz_token");
    localStorage.removeItem("dz_service");
    location.reload();
  }

  /* ══════════ App-Start ══════════ */
  async function enterApp() {
    await DashMap.loadMapsConfig();
    $("#login").classList.add("hidden");
    $("#app").classList.remove("hidden");
    $("#badge-server").textContent = S.serverName || ("Service " + S.sid);
    $("#badge-map").textContent = "🗺️ " + S.mapName + " (automatisch erkannt)";
    $("#map-name-label").textContent = "– " + S.mapName;
    initFilters();
    await refreshState(true);
    renderAll();
    S.pollTimer = setInterval(() => refreshState(false), 10000);
    showView("feeds");
  }

  /* ══════════ State-Polling (Bot → Dashboard) ══════════ */
  async function refreshState(initial) {
    try {
      if (!S.dir) {
        S.dir = await DashFiles.findDataDir(S.sid, S.info);
      }
      if (!S.dir) throw new Error("Datenverzeichnis nicht gefunden");
      S.state = await DashFiles.readState(S.sid, S.dir);
      $("#offline-banner").classList.add("hidden");
      const age = Date.now() / 1000 - (S.state.ts || 0);
      $("#bot-status").textContent = age < 90 ? "🟢 online" : "🟠 zuletzt vor " + Math.round(age / 60) + " Min";
      if (S.state.map_name && S.state.map_name !== S.mapName) {
        S.mapName = S.state.map_name;    // Kartenwechsel vom Bot übernehmen
        localStorage.setItem("dz_map", S.mapName);
        $("#badge-map").textContent = "🗺️ " + S.mapName + " (automatisch erkannt)";
        $("#map-name-label").textContent = "– " + S.mapName;
        S.zonesMap = S.eventsMap = null;  // Karten neu aufbauen
        $("#zones-map").innerHTML = "";
        $("#events-map").innerHTML = "";
      }
      resolvePending();
      if (!S.catalog) loadCatalog();
      renderLive();
      if (initial) renderAll();
    } catch (e) {
      $("#bot-status").textContent = "🔴 keine Daten";
      $("#offline-banner").classList.remove("hidden");
    }
  }

  async function loadCatalog() {
    try {
      S.catalog = await DashFiles.readCatalog(S.sid, S.dir);
      renderShopMeta();
    } catch (_) { /* Katalog noch nicht hochgeladen */ }
  }

  function resolvePending() {
    const results = (S.state || {}).results || {};
    for (const [id, desc] of [...S.pending]) {
      if (id in results) {
        const r = results[id];
        toast((r.ok ? "✅ " : "❌ ") + desc + ": " + (r.msg || ""), r.ok ? "ok" : "err");
        S.pending.delete(id);
        if (r.ok) { renderAll(); if (desc.startsWith("Shop")) S.catalog = null; }
      }
    }
  }

  /* Befehl an den Bot schicken (über dashboard_sync.json) */
  async function sendCmd(action, payload, desc) {
    if (!S.dir) { toast("❌ Bot-Datenverzeichnis nicht gefunden", "err"); return; }
    try {
      const acked = new Set(Object.keys((S.state || {}).results || {}));
      const id = await DashFiles.sendCommand(S.sid, S.dir, action, payload, acked);
      S.pending.set(id, desc);
      toast("⏳ " + desc + " – an den Bot gesendet…");
    } catch (e) {
      toast("❌ " + desc + ": " + e.message, "err");
    }
  }

  /* ══════════ Navigation ══════════ */
  function showView(name) {
    $$(".nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
    $$(".view").forEach((v) => v.classList.toggle("hidden", v.id !== "view-" + name));
    if (name === "zones") initZonesMap();
    if (name === "karte") initEventsMap();
    setTimeout(() => {
      if (name === "zones" && S.zonesMap) S.zonesMap.invalidate();
      if (name === "karte" && S.eventsMap) S.eventsMap.invalidate();
    }, 60);
  }

  function renderAll() {
    renderFeeds();
    renderZonesList();
    renderAutoForm();
    renderShopMeta();
    renderLive();
  }

  /* Live-Teile (bei jedem Poll): Karten-Marker + Zonenliste + Countdown */
  function renderLive() {
    const st = S.state || {};
    if (S.eventsMap) S.eventsMap.setEvents(st.events, st.positions, S.filters);
    if (S.eventsMap) S.eventsMap.setZones(st.zones);
    if (S.zonesMap)  S.zonesMap.setZones(st.zones);
    renderAutoNext();
    // Feeds nur neu zeichnen, wenn der Nutzer gerade nicht darin arbeitet
    if (!$("#feeds-list").contains(document.activeElement)) renderFeeds();
    renderZonesList();
  }

  /* ══════════ Feeds ══════════ */
  function renderFeeds() {
    const st = S.state;
    const box = $("#feeds-list");
    if (!st) { box.innerHTML = "<p class='muted'>Warte auf Daten vom Bot…</p>"; return; }
    box.innerHTML = "";
    for (const g of st.guilds || []) {
      const wrap = document.createElement("div");
      wrap.className = "feed-guild";
      wrap.innerHTML = `<h3>💬 ${esc(g.name)}</h3>`;
      for (const [ft, label] of Object.entries(st.feed_types || {})) {
        const row = document.createElement("div");
        row.className = "feed-row";
        const current = (g.feeds || {})[ft] || "";
        const opts = ['<option value="">– kein Channel (aus) –</option>']
          .concat((g.channels || []).map((c) =>
            `<option value="${c.id}" ${c.id === current ? "selected" : ""}>#${esc(c.name)}</option>`));
        row.innerHTML =
          `<span class="feed-state">${current ? "🟢" : "⚪"}</span>` +
          `<span class="feed-name">${esc(label)}</span>` +
          `<select data-guild="${g.id}" data-feed="${ft}">${opts.join("")}</select>`;
        row.querySelector("select").addEventListener("change", (e) => {
          const sel = e.target;
          sendCmd("set_feed",
            { guild_id: sel.dataset.guild, feed: sel.dataset.feed,
              channel_id: sel.value || null },
            `Feed ${sel.dataset.feed}`);
        });
        wrap.appendChild(row);
      }
      box.appendChild(wrap);
    }
    if (!(st.guilds || []).length) {
      box.innerHTML = "<p class='muted'>Der Bot ist noch auf keinem Discord-Server.</p>";
    }
  }

  /* ══════════ Zonen ══════════ */
  function initZonesMap() {
    if (S.zonesMap) return;
    S.zonesMap = DashMap.create("zones-map", S.mapName);
    if (S.state) S.zonesMap.setZones(S.state.zones);
  }

  function fillZoneChannelSelect() {
    const sel = $("#zone-form select[name=channel_id]");
    const keep = sel.value;
    sel.innerHTML = '<option value="">– Zonen-Feed/Adminlog –</option>';
    for (const g of (S.state || {}).guilds || []) {
      const grp = document.createElement("optgroup");
      grp.label = g.name;
      for (const c of g.channels || []) {
        const o = document.createElement("option");
        o.value = c.id; o.textContent = "#" + c.name;
        grp.appendChild(o);
      }
      sel.appendChild(grp);
    }
    sel.value = keep;
  }

  function renderZonesList() {
    const box = $("#zones-list");
    if (!box) return;
    const zones = (S.state || {}).zones || [];
    box.innerHTML = zones.length ? "" : "<p class='muted'>Noch keine Zonen.</p>";
    for (const z of zones) {
      const item = document.createElement("div");
      item.className = "zone-item";
      item.innerHTML =
        `<span class="zi-info"><b>${esc(z.name)}</b><br>
         <span class="muted">${z.x}, ${z.z} · r=${z.radius} m</span></span>
         <button class="btn small" data-act="edit">✏️</button>
         <button class="btn small danger" data-act="del">🗑️</button>`;
      item.querySelector('[data-act=edit]').addEventListener("click", () => {
        S.editingZone = z.name;
        $("#zone-form-title").textContent = "Zone bearbeiten: " + z.name;
        const f = $("#zone-form");
        f.name.value = z.name; f.x.value = z.x; f.z.value = z.z;
        f.radius.value = z.radius;
        f.role_id.value = z.role_id || "";
        fillZoneChannelSelect();
        f.channel_id.value = z.channel_id || "";
      });
      item.querySelector('[data-act=del]').addEventListener("click", () => {
        if (confirm(`Zone "${z.name}" wirklich löschen?`)) {
          sendCmd("zone_delete", { name: z.name }, `Zone ${z.name} löschen`);
        }
      });
      box.appendChild(item);
    }
    fillZoneChannelSelect();
  }

  function resetZoneForm() {
    S.editingZone = null;
    $("#zone-form-title").textContent = "Neue Zone";
    $("#zone-form").reset();
  }

  function submitZoneForm(e) {
    e.preventDefault();
    const f = e.target;
    const payload = {
      name:   S.editingZone || f.name.value.trim(),
      x:      parseFloat(f.x.value),
      z:      parseFloat(f.z.value),
      radius: parseFloat(f.radius.value),
      role_id:    f.role_id.value.trim() || null,
      channel_id: f.channel_id.value || null,
    };
    if (S.editingZone) {
      sendCmd("zone_edit", payload, `Zone ${payload.name} ändern`);
    } else {
      sendCmd("zone_create", payload, `Zone ${payload.name} anlegen`);
    }
    resetZoneForm();
  }

  /* ══════════ Auto-Aufgaben ══════════ */
  function renderAutoForm() {
    const f = $("#auto-form");
    const a = ((S.state || {}).auto_restart) || {};
    if (!f.contains(document.activeElement)) {
      f.enabled.checked = !!a.enabled;
      if (a.first_time) f.first_time.value =
        a.first_time.length === 4 ? "0" + a.first_time : a.first_time;
      if (a.interval_hours) f.interval_hours.value = a.interval_hours;
    }
    renderAutoNext();
  }

  function renderAutoNext() {
    const a = ((S.state || {}).auto_restart) || {};
    $("#auto-next").textContent = a.enabled && a.next_ts
      ? "Nächster Neustart: " + new Date(a.next_ts * 1000).toLocaleString("de-DE")
      : "Automatische Neustarts sind aus.";
  }

  function submitAutoForm(e) {
    e.preventDefault();
    const f = e.target;
    sendCmd("auto_restart", {
      enabled: f.enabled.checked,
      first_time: f.first_time.value,
      interval_hours: parseInt(f.interval_hours.value, 10) || 4,
    }, "Auto-Restart");
  }

  /* ══════════ Shop ══════════ */
  function renderShopMeta() {
    const catSel = $("#bundle-form select[name=category]");
    const cats = new Set([...((S.state || {}).shop_categories || []),
                          ...(((S.catalog || {}).categories) || []), "Bundles"]);
    const keep = catSel.value;
    catSel.innerHTML = "";
    for (const c of [...cats].sort()) {
      const o = document.createElement("option");
      o.value = o.textContent = c;
      catSel.appendChild(o);
    }
    if (keep && [...cats].includes(keep)) catSel.value = keep;

    const dl = $("#item-datalist");
    dl.innerHTML = "";
    const items = ((S.catalog || {}).items || []).slice(0, 2000);
    for (const it of items) {
      const o = document.createElement("option");
      o.value = it.n;
      dl.appendChild(o);
    }
    $("#catalog-info").textContent = items.length
      ? `Autofill aktiv: ${items.length} Items aus deinem Katalog.`
      : "Item-Autofill lädt, sobald der Bot den Katalog hochgeladen hat.";
  }

  function addBundleRow(count = 1, name = "") {
    const row = document.createElement("div");
    row.className = "bundle-row";
    row.innerHTML =
      `<input class="cnt" type="number" min="1" value="${count}" title="Anzahl">
       <input class="itm" list="item-datalist" placeholder="Item / Classname…" value="${esc(name)}">
       <button type="button" class="btn small danger">✕</button>`;
    row.querySelector("button").addEventListener("click", () => row.remove());
    $("#bundle-items").appendChild(row);
  }

  function submitBundleForm(e) {
    e.preventDefault();
    const f = e.target;
    const items = $$("#bundle-items .bundle-row").map((r) => ({
      count: parseInt(r.querySelector(".cnt").value, 10) || 1,
      classname: r.querySelector(".itm").value.trim(),
    })).filter((i) => i.classname);
    if (!items.length) { toast("❌ Mindestens ein Item angeben", "err"); return; }
    sendCmd("shop_add", {
      name: f.name.value.trim(),
      category: f.category.value,
      price: parseInt(f.price.value, 10) || 0,
      max_per_buy: parseInt(f.max_per_buy.value, 10) || 1,
      items,
    }, "Shop: " + f.name.value.trim());
    f.reset();
    $("#bundle-items").innerHTML = "";
    addBundleRow();
    f.classList.add("hidden");
  }

  /* ══════════ Karte (Events) ══════════ */
  function initFilters() {
    const saved = localStorage.getItem("dz_filters");
    S.filters = new Set(saved ? JSON.parse(saved)
                              : Object.keys(DashMap.EVENT_STYLE));
    const box = $("#filter-boxes");
    box.innerHTML = "";
    for (const [key, st] of Object.entries(DashMap.EVENT_STYLE)) {
      const el = document.createElement("div");
      el.className = "filter-box" + (S.filters.has(key) ? "" : " off");
      el.innerHTML = `<span class="dot" style="background:${st.color}"></span>
                      <span>${esc(st.label)}</span>`;
      el.addEventListener("click", () => {
        if (S.filters.has(key)) S.filters.delete(key); else S.filters.add(key);
        el.classList.toggle("off", !S.filters.has(key));
        localStorage.setItem("dz_filters", JSON.stringify([...S.filters]));
        renderLive();
      });
      box.appendChild(el);
    }
  }

  function initEventsMap() {
    if (S.eventsMap) return;
    S.eventsMap = DashMap.create("events-map", S.mapName, {
      onFallback: () => toast("Kartenbilder nicht erreichbar – zeige Koordinatenraster", ""),
    });
    renderLive();
  }

  /* ══════════ Verkabelung ══════════ */
  function init() {
    $("#token-confirm").addEventListener("click", confirmToken);
    $("#token-input").addEventListener("keydown", (e) => {
      if (e.key === "Enter") confirmToken();
    });
    $("#server-confirm").addEventListener("click", confirmServer);
    $("#btn-logout").addEventListener("click", () => logout(true));
    $("#btn-switch").addEventListener("click", () => logout(false));
    $("#btn-retry-state").addEventListener("click", () => {
      localStorage.removeItem("dz_dir:" + S.sid);
      S.dir = null;
      refreshState(true);
    });
    $$(".nav-btn").forEach((b) =>
      b.addEventListener("click", () => showView(b.dataset.view)));

    $("#zone-form").addEventListener("submit", submitZoneForm);
    $("#zone-form-reset").addEventListener("click", resetZoneForm);
    $("#btn-draw-zone").addEventListener("click", () => {
      if (!S.zonesMap) return;
      toast("✏️ Klick = Zentrum setzen, ziehen und 2. Klick = Radius festlegen");
      S.zonesMap.enableDraw((res) => {
        const f = $("#zone-form");
        f.x.value = res.x; f.z.value = res.z; f.radius.value = res.radius;
        f.name.focus();
      });
    });

    $("#auto-form").addEventListener("submit", submitAutoForm);

    $("#btn-new-bundle").addEventListener("click", () => {
      $("#bundle-form").classList.remove("hidden");
      if (!$$("#bundle-items .bundle-row").length) addBundleRow();
      renderShopMeta();
    });
    $("#bundle-cancel").addEventListener("click", () =>
      $("#bundle-form").classList.add("hidden"));
    $("#btn-add-item-row").addEventListener("click", () => addBundleRow());
    $("#btn-new-category").addEventListener("click", () => {
      const name = prompt("Name der neuen Kategorie:");
      if (!name || !name.trim()) return;
      const sel = $("#bundle-form select[name=category]");
      const o = document.createElement("option");
      o.value = o.textContent = name.trim().slice(0, 60);
      sel.appendChild(o);
      sel.value = o.value;
    });
    $("#bundle-form").addEventListener("submit", submitBundleForm);

    $("#filter-toggle").addEventListener("click", () => {
      const p = $("#filter-panel");
      p.classList.toggle("collapsed");
      $("#filter-toggle").textContent = p.classList.contains("collapsed") ? "▶" : "◀";
      setTimeout(() => S.eventsMap && S.eventsMap.invalidate(), 180);
    });

    /* Auto-Login, wenn Token + Server gespeichert sind */
    const tok = localStorage.getItem("dz_token");
    if (tok && S.sid) {
      Nitrado.gameserver(S.sid)
        .then((info) => { S.info = info; return enterApp(); })
        .catch(() => { /* Token abgelaufen o. Ä. → Login zeigen */ });
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
