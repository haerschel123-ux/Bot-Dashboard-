/* Datei-Zugriff auf den DayZ-Server über die Nitrado file_server-API.
   Damit tauscht das Dashboard JSON-Dateien mit dem Bot aus:
     dashboard_state.json / dashboard_catalog.json  (Bot → Dashboard)
     dashboard_sync.json                            (Dashboard → Bot)
   Alle Transfers laufen über dieses eine Modul – falls die Download-Nodes
   irgendwann CORS blockieren, muss nur hier eine Proxy-URL ergänzt werden
   (siehe worker.js im Repo). */
"use strict";

const DashFiles = (() => {
  const STATE_FILE   = "dashboard_state.json";
  const SYNC_FILE    = "dashboard_sync.json";
  const CATALOG_FILE = "dashboard_catalog.json";

  async function list(sid, dir) {
    const d = await Nitrado.api(
      `/services/${sid}/gameservers/file_server/list?dir=${encodeURIComponent(dir)}`);
    return ((d.data || {}).entries || []);
  }

  async function download(sid, path) {
    const d = await Nitrado.api(
      `/services/${sid}/gameservers/file_server/download?file=${encodeURIComponent(path)}`);
    const url = (((d.data || {}).token) || {}).url;
    if (!url) throw new Error("Kein Download-Token erhalten");
    const r = await fetch(url);
    if (!r.ok) throw new Error("Download fehlgeschlagen (HTTP " + r.status + ")");
    return r.text();
  }

  async function upload(sid, dir, name, content) {
    const d = await Nitrado.api(`/services/${sid}/gameservers/file_server/upload`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: dir, file: name }),
    });
    const tok = ((d.data || {}).token) || {};
    if (!tok.url || !tok.token) throw new Error("Kein Upload-Token erhalten");
    const r = await fetch(tok.url, {
      method: "POST",
      headers: { "Content-Type": "application/binary", token: tok.token },
      body: content,
    });
    if (!r.ok) throw new Error("Upload fehlgeschlagen (HTTP " + r.status + ")");
    return true;
  }

  /* Verzeichnis finden, in dem der Bot die Dashboard-Dateien ablegt
     (= sein Log-Verzeichnis). Gleiche Kandidaten wie die Bot-Suche. */
  function candidates(info) {
    const c = [];
    const gsPath = String(((info || {}).game_specific || {}).path || "").replace(/\/+$/, "");
    if (gsPath) c.push(gsPath + "/config", gsPath + "/profiles", gsPath);
    const user = String((info || {}).username || "").split("_")[0];
    if (user) c.push(`/games/${user}/noftp/dayz/config`,
                     `/games/${user}/noftp/dayz/profiles`);
    c.push("/dayzps/config", "/dayzxb/config", "/dayz/config",
           "/dayzps/profiles", "/dayzxb/profiles", "/dayz/profiles");
    return [...new Set(c)];
  }

  async function findDataDir(sid, info) {
    const cacheKey = "dz_dir:" + sid;
    const cached = localStorage.getItem(cacheKey);
    const dirs = cached ? [cached, ...candidates(info)] : candidates(info);
    for (const dir of dirs) {
      try {
        const entries = await list(sid, dir);
        const names = entries.map((e) => String(e.name || e.path || "").split("/").pop());
        if (names.includes(STATE_FILE) ||
            names.some((n) => n.toUpperCase().endsWith(".ADM"))) {
          localStorage.setItem(cacheKey, dir);
          return dir;
        }
      } catch (_) { /* Kandidat existiert nicht */ }
    }
    return null;
  }

  async function readJson(sid, dir, name) {
    const txt = await download(sid, `${dir}/${name}`);
    return JSON.parse(txt);
  }

  const readState   = (sid, dir) => readJson(sid, dir, STATE_FILE);
  const readCatalog = (sid, dir) => readJson(sid, dir, CATALOG_FILE);

  /* Befehl an den Bot: sync.json lesen → bereits bestätigte/alte Einträge
     entfernen → neuen Befehl anhängen → hochladen. */
  async function sendCommand(sid, dir, action, payload, ackedIds) {
    let commands = [];
    try {
      const cur = await readJson(sid, dir, SYNC_FILE);
      if (cur && Array.isArray(cur.commands)) commands = cur.commands;
    } catch (_) { /* Datei fehlt noch */ }
    const now = Date.now() / 1000;
    const acked = ackedIds || new Set();
    commands = commands.filter((c) => c && c.id && !acked.has(String(c.id))
                                      && now - (c.ts || now) < 3600);
    const id = (crypto.randomUUID ? crypto.randomUUID()
                                  : String(now) + Math.random()).replace(/-/g, "").slice(0, 12);
    commands.push({ id, ts: now, action, ...payload });
    await upload(sid, dir, SYNC_FILE,
                 JSON.stringify({ commands }, null, 1));
    return id;
  }

  return { list, download, upload, findDataDir, readState, readCatalog,
           sendCommand, STATE_FILE, SYNC_FILE, CATALOG_FILE };
})();
