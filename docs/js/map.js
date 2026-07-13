/* Karten-Modul: Leaflet (CRS.Simple) mit echten iZurvive-Kartentiles der
   jeweils aktiven DayZ-Karte (ChernarusPlus/Livonia/Sakhal). Fällt auf ein
   schematisches Koordinatenraster mit Ortsnamen zurück, wenn die Tiles
   nicht erreichbar sind. Koordinaten: x = Ost, z = Nord (wie iZurvive).

   Mapping DayZ→Leaflet (Zoom 0 = ganze Karte in einem 256px-Tile):
     latLng = [ (z - S) * 256/S , x * 256/S ]        (S = Kartengröße in m)  */
"use strict";

const DashMap = (() => {
  const TILE_BASE = "https://maps.izurvive.com/maps";

  const EVENT_STYLE = {
    kill_pvp:     { color: "#e74c3c", label: "☠️ PvP-Kills" },
    damage:       { color: "#e67e22", label: "🩸 Treffer/Damage" },
    kill_env:     { color: "#8e44ad", label: "💀 Umwelt-Tode" },
    suicide:      { color: "#95a5a6", label: "🪦 Suizide" },
    connect:      { color: "#2ecc71", label: "🟢 Verbunden" },
    disconnect:   { color: "#7f8c8d", label: "⚪ Getrennt" },
    connecting:   { color: "#1abc9c", label: "🔌 Verbindet…" },
    basebuild:    { color: "#3498db", label: "🏗️ Bau-Events" },
    vehicle:      { color: "#d35400", label: "🚗 Fahrzeug-Events" },
    chat:         { color: "#f1c40f", label: "💬 Chat" },
    loot:         { color: "#c0a060", label: "🎒 Loot" },
    admin_action: { color: "#ff66aa", label: "🛡️ Admin-Aktionen" },
    players:      { color: "#00d0ff", label: "🧍 Spieler-Positionen" },
  };

  let MAPS = null;   // Inhalt von maps.json

  async function loadMapsConfig() {
    if (!MAPS) {
      const r = await fetch("maps.json");
      MAPS = await r.json();
    }
    return MAPS;
  }

  /* Erste erreichbare Tile-Version der Karte ermitteln (Probe-Bild mit Timeout) */
  function probeVersion(izName, versions) {
    const tryOne = (v) => new Promise((res) => {
      const img = new Image();
      const timer = setTimeout(() => { img.src = ""; res(null); }, 6000);
      img.onload  = () => { clearTimeout(timer); res(v); };
      img.onerror = () => { clearTimeout(timer); res(null); };
      img.src = `${TILE_BASE}/${izName}/${v}/tiles/0/0/0.webp`;
    });
    return (async () => {
      for (const v of versions) {
        const hit = await tryOne(v);
        if (hit) return hit;
      }
      return null;
    })();
  }

  /* Schematisches Fallback-Raster (1km-Linien) als Leaflet-GridLayer */
  const GridFallback = L.GridLayer.extend({
    createTile: function (coords) {
      const tile = document.createElement("canvas");
      tile.width = tile.height = 256;
      const g = tile.getContext("2d");
      g.fillStyle = "#1b2a1e";
      g.fillRect(0, 0, 256, 256);
      const S = this.options.worldSize;
      const metersPerTile = S / Math.pow(2, coords.z);
      const kmStep = 256 / (metersPerTile / 1000);   // Pixel pro km
      if (kmStep >= 12) {
        g.strokeStyle = "rgba(255,255,255,0.15)";
        g.beginPath();
        const x0 = coords.x * metersPerTile, z0 = coords.y * metersPerTile;
        for (let km = Math.ceil(x0 / 1000); km * 1000 < x0 + metersPerTile; km++) {
          const px = (km * 1000 - x0) / metersPerTile * 256;
          g.moveTo(px, 0); g.lineTo(px, 256);
        }
        for (let km = Math.ceil(z0 / 1000); km * 1000 < z0 + metersPerTile; km++) {
          const py = (km * 1000 - z0) / metersPerTile * 256;
          g.moveTo(0, py); g.lineTo(256, py);
        }
        g.stroke();
      }
      return tile;
    },
  });

  function create(containerId, mapName, opts = {}) {
    const cfg = (MAPS || {})[mapName] || MAPS.ChernarusPlus;
    const S = cfg.size;
    const dz2ll = (x, z) => [ (z - S) * 256 / S, x * 256 / S ];
    const ll2dz = (ll) => [ ll.lng * S / 256, S + ll.lat * S / 256 ];

    const map = L.map(containerId, {
      crs: L.CRS.Simple, minZoom: 1, maxZoom: 9, zoomControl: true,
      attributionControl: false,
    });
    const bounds = L.latLngBounds(dz2ll(0, 0), dz2ll(S, S));
    map.setMaxBounds(bounds.pad(0.25));
    map.fitBounds(bounds);

    const layers = {
      events: L.layerGroup().addTo(map),
      zones:  L.layerGroup().addTo(map),
      towns:  L.layerGroup(),
      draw:   L.layerGroup().addTo(map),
    };

    /* Raster sofort anzeigen (nie eine schwarze Karte) – echte iZurvive-Tiles
       legen sich darüber, sobald ihre Verfügbarkeit bestätigt ist */
    let usingFallback = true;
    new GridFallback({ worldSize: S, minZoom: 0, maxZoom: 9,
                       bounds: bounds, noWrap: true }).addTo(map);
    probeVersion(cfg.izName, cfg.versions).then((v) => {
      if (v) {
        usingFallback = false;
        map.removeLayer(layers.towns);
        L.tileLayer(`${TILE_BASE}/${cfg.izName}/${v}/tiles/{z}/{x}/{y}.webp`, {
          minZoom: 0, maxNativeZoom: 7, maxZoom: 9, noWrap: true,
          bounds: bounds,
        }).addTo(map);
      } else {
        // Ortsnamen einblenden, damit man sich auch ohne Kartenbild orientiert
        for (const [name, x, z] of (cfg.locations || [])) {
          L.marker(dz2ll(x, z), {
            icon: L.divIcon({ className: "town-label", html: name }),
            interactive: false,
          }).addTo(layers.towns);
        }
        layers.towns.addTo(map);
        if (opts.onFallback) opts.onFallback();
      }
    });

    function fmt(n) { return Math.round(n * 10) / 10; }

    /* Events + Spielerpositionen zeichnen (filters = Set aktiver Typen) */
    function setEvents(events, positions, filters) {
      layers.events.clearLayers();
      for (const ev of events || []) {
        if (!ev || !ev.pos || !filters.has(ev.t)) continue;
        const st = EVENT_STYLE[ev.t] || { color: "#ffffff" };
        L.circleMarker(dz2ll(ev.pos[0], ev.pos[1]), {
          radius: 6, color: st.color, weight: 2,
          fillColor: st.color, fillOpacity: 0.5,
        }).bindPopup(
          `<b>${(st.label || ev.t)}</b><br>${escapeHtml(ev.label || "")}` +
          `<br><small>${ev.time || ""} · ${fmt(ev.pos[0])}, ${fmt(ev.pos[1])}</small>`
        ).addTo(layers.events);
      }
      if (filters.has("players")) {
        for (const [name, p] of Object.entries(positions || {})) {
          if (!p || !p.pos) continue;
          L.circleMarker(dz2ll(p.pos[0], p.pos[1]), {
            radius: 5, color: "#00d0ff", weight: 2,
            fillColor: "#00d0ff", fillOpacity: 0.8,
          }).bindPopup(`<b>🧍 ${escapeHtml(name)}</b>` +
                       `<br><small>${fmt(p.pos[0])}, ${fmt(p.pos[1])}</small>`)
            .addTo(layers.events);
        }
      }
    }

    function setZones(zones) {
      layers.zones.clearLayers();
      for (const z of zones || []) {
        if (z.x == null || z.z == null) continue;
        L.circle(dz2ll(z.x, z.z), {
          radius: (z.radius || 0) * 256 / S,   // CRS.Simple: Radius in Karteneinheiten
          color: "#ffd166", weight: 2, fillColor: "#ffd166", fillOpacity: 0.12,
        }).bindPopup(`<b>🛡️ ${escapeHtml(z.name || "")}</b>` +
                     `<br><small>${z.x}, ${z.z} · r=${z.radius} m</small>`)
          .addTo(layers.zones);
      }
    }

    /* Zone zeichnen: 1. Klick = Zentrum, Maus ziehen = Radius, 2. Klick = fertig */
    let drawState = null;
    function enableDraw(onDone) {
      disableDraw();
      map.getContainer().style.cursor = "crosshair";
      drawState = { center: null, circle: null, onDone };
      map.on("click", onDrawClick);
      map.on("mousemove", onDrawMove);
    }
    function disableDraw() {
      map.getContainer().style.cursor = "";
      map.off("click", onDrawClick);
      map.off("mousemove", onDrawMove);
      layers.draw.clearLayers();
      drawState = null;
    }
    function onDrawClick(e) {
      if (!drawState) return;
      if (!drawState.center) {
        drawState.center = e.latlng;
        drawState.circle = L.circle(e.latlng, {
          radius: 1, color: "#4dd0e1", weight: 2, fillOpacity: 0.15,
        }).addTo(layers.draw);
      } else {
        const [cx, cz] = ll2dz(drawState.center);
        const [px, pz] = ll2dz(e.latlng);
        const radius = Math.max(10, Math.round(Math.hypot(px - cx, pz - cz)));
        const done = drawState.onDone;
        const res = { x: fmt(cx), z: fmt(cz), radius };
        disableDraw();
        if (done) done(res);
      }
    }
    function onDrawMove(e) {
      if (drawState && drawState.center && drawState.circle) {
        const [cx, cz] = ll2dz(drawState.center);
        const [px, pz] = ll2dz(e.latlng);
        const r = Math.max(10, Math.hypot(px - cx, pz - cz));
        drawState.circle.setRadius(r * 256 / S);
      }
    }

    return { map, dz2ll, ll2dz, setEvents, setZones, enableDraw, disableDraw,
             invalidate: () => map.invalidateSize(),
             isFallback: () => usingFallback };
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g,
      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  return { create, loadMapsConfig, EVENT_STYLE };
})();
