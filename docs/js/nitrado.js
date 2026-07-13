/* Nitrado-API-Client (läuft komplett im Browser, api.nitrado.net erlaubt CORS).
   Basis-URL per localStorage 'dz_api_base' übersteuerbar (Tests/Proxy). */
"use strict";

const Nitrado = (() => {
  const base  = () => localStorage.getItem("dz_api_base") || "https://api.nitrado.net";
  const token = () => localStorage.getItem("dz_token") || "";

  async function api(path, opts = {}) {
    const r = await fetch(base() + path, {
      ...opts,
      headers: { Authorization: "Bearer " + token(), ...(opts.headers || {}) },
    });
    let data = null;
    try { data = await r.json(); } catch (_) { /* kein JSON */ }
    if (!r.ok) {
      throw new Error((data && data.message) || "HTTP " + r.status);
    }
    return data || {};
  }

  /* Alle Gameserver-Services des Tokens */
  async function listServices() {
    const d = await api("/services");
    return ((d.data || {}).services || [])
      .filter((s) => String(s.type || "").toLowerCase() === "gameserver");
  }

  async function gameserver(sid) {
    const d = await api(`/services/${sid}/gameservers`);
    return (d.data || {}).gameserver || {};
  }

  async function restart(sid) {
    return api(`/services/${sid}/gameservers/restart`, { method: "POST" });
  }

  /* Aktive Karte aus den Gameserver-Infos – gleiche Normalisierung wie im Bot */
  const CANON = { chernarusplus: "ChernarusPlus", chernarus: "ChernarusPlus",
                  enoch: "Livonia", livonia: "Livonia", sakhal: "Sakhal" };
  function canonMap(raw) {
    const s = String(raw || "").toLowerCase();
    for (const k in CANON) if (s.includes(k)) return CANON[k];
    return null;
  }
  function detectMap(info) {
    let m = canonMap(((info || {}).query || {}).map);
    if (m) return m;
    const settings = (info || {}).settings || {};
    for (const cat of Object.values(settings)) {
      if (cat && typeof cat === "object") {
        for (const key of ["mission", "map", "current_map", "mapname"]) {
          m = canonMap(cat[key]);
          if (m) return m;
        }
      }
    }
    return null;
  }

  return { api, base, listServices, gameserver, restart, detectMap, canonMap };
})();
