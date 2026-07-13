/* OPTIONALER CORS-Fallback (nur nötig, falls die Nitrado-Datei-Download-Server
   im Browser CORS blockieren – erkennbar an Fehlern in der Browser-Konsole
   beim Laden von dashboard_state.json).

   Einrichtung (kostenlos):
   1. https://workers.cloudflare.com → Konto anlegen → "Create Worker"
   2. Diesen Code einfügen und deployen (z.B. https://dz-proxy.<name>.workers.dev)
   3. Im Dashboard die Browser-Konsole öffnen und einmalig eintragen:
        localStorage.setItem("dz_api_base",
          "https://dz-proxy.<name>.workers.dev/https://api.nitrado.net")
   Der Worker reicht Anfragen 1:1 weiter und ergänzt nur die CORS-Header. */

export default {
  async fetch(request) {
    const url = new URL(request.url);
    const target = url.pathname.slice(1) + url.search;
    if (!/^https:\/\/([a-z0-9-]+\.)*(nitrado\.net|gamedata\.io)\//.test(target)) {
      return new Response("Nur nitrado.net/gamedata.io erlaubt", { status: 403 });
    }
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: cors() });
    }
    const resp = await fetch(target, {
      method: request.method,
      headers: request.headers,
      body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
    });
    const out = new Response(resp.body, resp);
    for (const [k, v] of Object.entries(cors())) out.headers.set(k, v);
    return out;
  },
};

function cors() {
  return {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type, token",
  };
}
