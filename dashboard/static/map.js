/* Leaflet-Kartenlogik für das DayZ-Dashboard.
   Spiel-Koordinaten: x = Ost, z = Nord (Meter, 0..world_size).
   Leaflet nutzt CRS.Simple, normalisiert auf 256 Einheiten (= 1 Kachel bei Zoom 0),
   damit die echten XYZ-Kacheln (static.xam.nu) exakt auf die Spielkoordinaten,
   Ortsnamen, Spieler und Zonen passen. Norden ist oben. */
(function (global) {
  "use strict";

  var UNIT = 256;                       // CRS-Kantenlänge (1 Kachel bei Zoom 0)
  var UNIT_BOUNDS = [[0, 0], [UNIT, UNIT]];
  var map = null, worldSize = 15360, factor = UNIT / 15360;
  var baseLayer = null, gridLayer = null, labelLayer = null;
  var playerLayer = null, eventLayer = null, zoneLayer = null, drawLayer = null;
  var currentMeta = null, drawState = null, baseTimer = null;

  // Spiel (Meter) → Leaflet-LatLng (0..256, Norden oben) und zurück
  function g2ll(x, z) { return L.latLng(z * factor, x * factor); }
  function ll2g(ll)   { return { x: ll.lng / factor, z: ll.lat / factor }; }
  function m2u(m)     { return m * factor; }   // Meter → CRS-Einheiten
  function u2m(u)     { return u / factor; }   // CRS-Einheiten → Meter

  // Kachel-Layer: bildet Leaflet-CRS.Simple-Kachelkoordinaten auf das
  // xam.nu-XYZ-Schema ab. Bei CRS.Simple mit „Norden oben" ist die Kachel-Y
  // negativ; +2^z verschiebt sie in den gültigen Bereich 0..2^z-1 (Norden = 0).
  var DZTileLayer = L.TileLayer.extend({
    getTileUrl: function (coords) {
      var n = Math.pow(2, coords.z);
      var x = coords.x;
      var y = coords.y + n;
      if (x < 0 || x >= n || y < 0 || y >= n) return L.Util.emptyImageUrl;
      return L.Util.template(this._url, L.extend({ z: coords.z, x: x, y: y }, this.options));
    }
  });

  function ensureMap() {
    if (map) return map;
    map = L.map("leaflet", {
      crs: L.CRS.Simple, minZoom: 0, maxZoom: 8,
      zoomControl: false, attributionControl: false
    });
    L.control.zoom({ position: "topright" }).addTo(map);
    // Backdrop-Pane für das schematische Gitter, UNTER den Kacheln (tilePane=200)
    map.createPane("schematic");
    map.getPane("schematic").style.zIndex = 150;
    playerLayer = L.layerGroup().addTo(map);
    eventLayer  = L.layerGroup().addTo(map);
    zoneLayer   = L.layerGroup().addTo(map);
    drawLayer   = L.layerGroup().addTo(map);
    return map;
  }

  function clearLayer(l) { if (l) l.clearLayers(); }
  function removeBase() {
    if (baseLayer) { map.removeLayer(baseLayer); baseLayer = null; }
    if (baseTimer) { clearTimeout(baseTimer); baseTimer = null; }
  }

  function drawGrid() {
    if (gridLayer) { map.removeLayer(gridLayer); }
    gridLayer = L.layerGroup();
    for (var c = 0; c <= worldSize; c += 1000) {
      L.polyline([g2ll(c, 0), g2ll(c, worldSize)],
        { color: "#3a4130", weight: 1, pane: "schematic" }).addTo(gridLayer);
      L.polyline([g2ll(0, c), g2ll(worldSize, c)],
        { color: "#3a4130", weight: 1, pane: "schematic" }).addTo(gridLayer);
    }
    gridLayer.addTo(map);
  }

  // Basis-Layer: echte Kacheln → (Fallback) eigenes Bild → (Fallback) Gitter.
  function setBaseLayer(meta) {
    removeBase();
    drawGrid();  // Backdrop unter den Kacheln – sichtbar nur, falls Kacheln/Bild fehlen
    if (meta.tile_url) {
      var maxNative = meta.tile_max_native_zoom || 7;
      var loaded = false;
      baseLayer = new DZTileLayer(meta.tile_url, {
        tileSize: 256, noWrap: true, minZoom: 0,
        maxNativeZoom: maxNative, maxZoom: 8, bounds: UNIT_BOUNDS
      });
      baseLayer.on("tileload", function () { loaded = true; });
      baseLayer.addTo(map);
      // Kommt der Browser nicht an die Kachelquelle (offline/blockiert), nach 6s
      // auf ein eigenes Bild bzw. das schematische Gitter zurückfallen.
      baseTimer = setTimeout(function () { if (!loaded) { removeBase(); useImage(meta); } }, 6000);
    } else {
      useImage(meta);
    }
  }

  function useImage(meta) {
    if (!meta.image) return;  // Gitter-Backdrop bleibt sichtbar
    var img = new Image();
    img.onload = function () {
      removeBase();
      baseLayer = L.imageOverlay(meta.image, UNIT_BOUNDS).addTo(map);
    };
    img.onerror = function () { /* Gitter bleibt */ };
    img.src = meta.image;
  }

  // Ortslabels: klein und zoomabhängig – weit herausgezoomt nur die Städte,
  // beim Hineinzoomen nach und nach alle Orte (Dörfer, Camps, Hügel …).
  var allLocations = [];
  var _labelZoomHooked = false;
  var LABEL_MIN_ZOOM = { capital: 0, city: 1, village: 2, camp: 3, ruin: 3,
                         marine: 3, local: 4, hill: 4 };

  function renderLabels() {
    if (!map) return;
    if (labelLayer) { map.removeLayer(labelLayer); }
    labelLayer = L.layerGroup();
    var zoom = map.getZoom();
    allLocations.forEach(function (loc) {
      var t = loc.t || "local";
      if (zoom < (LABEL_MIN_ZOOM[t] !== undefined ? LABEL_MIN_ZOOM[t] : 5)) return;
      L.circleMarker(g2ll(loc.x, loc.z), { radius: 1.5, color: "#cfe6a3",
        fillColor: "#cfe6a3", fillOpacity: .9, weight: 1, interactive: false }).addTo(labelLayer);
      L.marker(g2ll(loc.x, loc.z), { icon: L.divIcon({
        className: "map-marker-label lbl-" + t, html: loc.name,
        iconSize: [0, 0], iconAnchor: [-5, 7] }), interactive: false }).addTo(labelLayer);
    });
    labelLayer.addTo(map);
  }

  function drawLabels(locations) {
    allLocations = locations || [];
    if (!_labelZoomHooked) { map.on("zoomend", renderLabels); _labelZoomHooked = true; }
    renderLabels();
  }

  var DZMap = {
    gameToLatLng: g2ll,

    load: function (meta) {
      currentMeta = meta;
      worldSize = meta.world_size || 15360;
      factor = UNIT / worldSize;
      ensureMap();
      map.setMaxBounds([[-20, -20], [UNIT + 20, UNIT + 20]]);
      setBaseLayer(meta);
      drawLabels(meta.locations);
      map.fitBounds(UNIT_BOUNDS);
      setTimeout(function () { map.invalidateSize(); map.fitBounds(UNIT_BOUNDS); }, 60);
    },

    invalidate: function () { if (map) setTimeout(function () { map.invalidateSize(); }, 30); },

    setPlayers: function (players, show) {
      clearLayer(playerLayer);
      if (!show) return;
      (players || []).forEach(function (p) {
        L.circleMarker(g2ll(p.x, p.z), { radius: 5, color: "#fff", weight: 1.5,
          fillColor: "#5ac8fa", fillOpacity: .95 })
          .bindTooltip(p.name + (p.near ? " · " + p.near : ""), { direction: "top" })
          .addTo(playerLayer);
      });
    },

    renderEvents: function (events, active) {
      clearLayer(eventLayer);
      (events || []).forEach(function (e) {
        if (typeof e.x !== "number") return;
        if (active && !active[e.type]) return;
        var m = (global.EVENT_COLORS || {})[e.type] || { color: "#e67e22" };
        L.circleMarker(g2ll(e.x, e.z), { radius: 4, color: "#0008", weight: 1,
          fillColor: m.color, fillOpacity: .9 })
          .bindPopup("<b>" + (e.type) + "</b><br>" + (e.summary || "") +
                     (e.time ? "<br><small>" + e.time + "</small>" : ""))
          .addTo(eventLayer);
      });
    },

    focus: function (x, z) {
      if (map && typeof x === "number") map.setView(g2ll(x, z), Math.max(map.getZoom(), 3));
    },

    setZones: function (zones) {
      clearLayer(zoneLayer);
      (zones || []).forEach(function (zn) {
        L.circle(g2ll(zn.x, zn.z), { radius: m2u(zn.radius), color: "#f1c40f",
          weight: 2, fillColor: "#f1c40f", fillOpacity: .12 })
          .bindTooltip(zn.name + " · r=" + zn.radius + "m", { sticky: true })
          .addTo(zoneLayer);
      });
    },

    // Zeichnen: 1. Klick = Zentrum, Maus = Radius, 2. Klick = fertig.
    startDraw: function (onComplete) {
      this.cancelDraw();
      map.getContainer().style.cursor = "crosshair";
      var circle = null, center = null;
      function onClick(e) {
        if (!center) {
          center = e.latlng;
          circle = L.circle(center, { radius: m2u(10), color: "#7cae3f", weight: 2,
            fillColor: "#7cae3f", fillOpacity: .15 }).addTo(drawLayer);
        } else {
          var r = Math.round(u2m(map.distance(center, e.latlng)));  // CRS-Einheiten → Meter
          DZMap.cancelDraw();
          var gp = ll2g(center);
          onComplete({ x: Math.round(gp.x * 10) / 10, z: Math.round(gp.z * 10) / 10,
            radius: Math.max(10, r) });
        }
      }
      function onMove(e) {
        if (center && circle) circle.setRadius(Math.max(m2u(10), map.distance(center, e.latlng)));
      }
      drawState = { onClick: onClick, onMove: onMove };
      map.on("click", onClick);
      map.on("mousemove", onMove);
    },

    cancelDraw: function () {
      if (drawState) {
        map.off("click", drawState.onClick);
        map.off("mousemove", drawState.onMove);
        drawState = null;
      }
      clearLayer(drawLayer);
      if (map) map.getContainer().style.cursor = "";
    }
  };

  global.DZMap = DZMap;
})(window);
