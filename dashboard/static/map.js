/* Leaflet-Kartenlogik für das DayZ-Dashboard.
   Koordinaten: x = Ost (horizontal), z = Nord (vertikal, oben = Norden).
   In Leaflet (CRS.Simple) wird ein Punkt als LatLng(z, x) dargestellt. */
(function (global) {
  "use strict";

  var map = null, worldSize = 15360, baseLayer = null, gridLayer = null;
  var labelLayer = null, playerLayer = null, eventLayer = null, zoneLayer = null;
  var drawLayer = null, drawState = null, currentMeta = null;

  function g2ll(x, z) { return L.latLng(z, x); }          // Spiel → Leaflet
  function ll2g(ll)   { return { x: ll.lng, z: ll.lat }; } // Leaflet → Spiel

  function ensureMap() {
    if (map) return map;
    map = L.map("leaflet", {
      crs: L.CRS.Simple, minZoom: -6, maxZoom: 4,
      zoomControl: false, attributionControl: false
    });
    L.control.zoom({ position: "topright" }).addTo(map);
    playerLayer = L.layerGroup().addTo(map);
    eventLayer  = L.layerGroup().addTo(map);
    zoneLayer   = L.layerGroup().addTo(map);
    drawLayer   = L.layerGroup().addTo(map);
    return map;
  }

  function clearLayer(l) { if (l) l.clearLayers(); }

  function drawGrid() {
    if (gridLayer) map.removeLayer(gridLayer);
    gridLayer = L.layerGroup();
    var step = 1000, s = worldSize;
    for (var c = 0; c <= s; c += step) {
      L.polyline([g2ll(c, 0), g2ll(c, s)], { color: "#3a4130", weight: 1 }).addTo(gridLayer);
      L.polyline([g2ll(0, c), g2ll(s, c)], { color: "#3a4130", weight: 1 }).addTo(gridLayer);
    }
    gridLayer.addTo(map);
  }

  function setBaseLayer(meta) {
    if (baseLayer) { map.removeLayer(baseLayer); baseLayer = null; }
    var bounds = [[0, 0], [worldSize, worldSize]];
    // 1) Kachel-URL (falls konfiguriert)
    if (meta.tile_url) {
      baseLayer = L.tileLayer(meta.tile_url, { bounds: bounds, noWrap: true,
        tms: !!meta.tile_tms, minZoom: -6, maxZoom: 4 }).addTo(map);
      return;
    }
    // 2) Bild-Overlay aus /maps/<Map>.jpg – bei 404 auf Schema zurückfallen
    if (meta.image) {
      var img = new Image();
      img.onload = function () {
        baseLayer = L.imageOverlay(meta.image, bounds).addTo(map);
        if (gridLayer) gridLayer.bringToFront && gridLayer.bringToFront();
      };
      img.onerror = function () { /* Schema-Gitter bleibt sichtbar */ };
      img.src = meta.image;
    }
  }

  function drawLabels(locations) {
    if (labelLayer) map.removeLayer(labelLayer);
    labelLayer = L.layerGroup();
    (locations || []).forEach(function (loc) {
      L.circleMarker(g2ll(loc.x, loc.z), { radius: 2, color: "#7cae3f",
        fillOpacity: 1, weight: 1 }).addTo(labelLayer);
      L.marker(g2ll(loc.x, loc.z), { icon: L.divIcon({
        className: "map-marker-label", html: loc.name,
        iconSize: [0, 0], iconAnchor: [-6, 8] }), interactive: false }).addTo(labelLayer);
    });
    labelLayer.addTo(map);
  }

  var DZMap = {
    gameToLatLng: g2ll,

    load: function (meta) {
      currentMeta = meta;
      worldSize = meta.world_size || 15360;
      ensureMap();
      var b = [[0, 0], [worldSize, worldSize]];
      map.setMaxBounds([[-worldSize * 0.1, -worldSize * 0.1],
                        [worldSize * 1.1, worldSize * 1.1]]);
      drawGrid();
      setBaseLayer(meta);
      drawLabels(meta.locations);
      map.fitBounds(b);
      setTimeout(function () { map.invalidateSize(); }, 60);
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
        var meta = (global.EVENT_COLORS || {})[e.type] || { color: "#e67e22" };
        L.circleMarker(g2ll(e.x, e.z), { radius: 4, color: "#0008", weight: 1,
          fillColor: meta.color, fillOpacity: .9 })
          .bindPopup("<b>" + (e.type) + "</b><br>" + (e.summary || "") +
                     (e.time ? "<br><small>" + e.time + "</small>" : ""))
          .addTo(eventLayer);
      });
    },

    focus: function (x, z) {
      if (map && typeof x === "number") map.setView(g2ll(x, z), Math.max(map.getZoom(), 0));
    },

    setZones: function (zones) {
      clearLayer(zoneLayer);
      (zones || []).forEach(function (zn) {
        L.circle(g2ll(zn.x, zn.z), { radius: zn.radius, color: "#f1c40f",
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
          circle = L.circle(center, { radius: 10, color: "#7cae3f", weight: 2,
            fillColor: "#7cae3f", fillOpacity: .15 }).addTo(drawLayer);
        } else {
          var r = Math.round(map.distance(center, e.latlng));
          DZMap.cancelDraw();
          var gp = ll2g(center);
          onComplete({ x: Math.round(gp.x * 10) / 10, z: Math.round(gp.z * 10) / 10,
            radius: Math.max(10, r) });
        }
      }
      function onMove(e) {
        if (center && circle) circle.setRadius(Math.max(10, map.distance(center, e.latlng)));
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
