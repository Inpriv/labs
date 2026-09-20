// trns Cloudflare Worker
// Serves the PWA at https://trns.inpriv.xyz.
// ASSETS binding handles the static UI; dynamic routes here cover
// anything that needs custom logic (Digital Asset Links, security
// headers, offline fallback for the service-worker shell).

const SECURITY_HEADERS = {
  // CSP keeps the PWA self-contained (translate.googleapis.com endpoint
  // is hit from JS via fetch, which requires connect-src).
  "Content-Security-Policy":
    "default-src 'self' translate.googleapis.com; " +
    "script-src 'self'; " +
    "style-src 'self' 'unsafe-inline'; " +
    "img-src 'self' data: blob:; " +
    "connect-src 'self' https://translate.googleapis.com; " +
    "worker-src 'self'; " +
    "manifest-src 'self'; " +
    "base-uri 'self'; " +
    "form-action 'self'; " +
    "frame-ancestors 'none'; " +
    "object-src 'none'",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer",
  "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
  "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload",
};

const ASSETLINKS = [{
  relation: ["delegate_permission/common.handle_all_urls"],
  target: { namespace: "web", site: "https://trns.inpriv.xyz" },
}];

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // Digital Asset Links — must be served at /.well-known/assetlinks.json
    // with the right Content-Type for Chrome to verify the TWA binding.
    if (url.pathname === "/.well-known/assetlinks.json") {
      return new Response(JSON.stringify(ASSETLINKS, null, 2), {
        headers: {
          "Content-Type": "application/json",
          "Cache-Control": "public, max-age=3600",
        },
      });
    }

    // Fallback: any HTML navigation gets index.html (SPA-style shell
    // pattern for offline). The PWA is a single page so this is safe.
    let response = await env.ASSETS.fetch(request);

    // If ASSETS returns 404 for an HTML route, fall back to the app shell.
    if (response.status === 404 && request.headers.get("Accept")?.includes("text/html")) {
      const indexReq = new Request(new URL("/index.html", url), request);
      response = await env.ASSETS.fetch(indexReq);
      if (response.ok) {
        response = new Response(response.body, {
          status: 200,
          statusText: "OK",
          headers: response.headers,
        });
      }
    }

    // Inject the security headers on HTML responses only — keeps
    // manifest + assetlinks JSON untouched.
    const ct = response.headers.get("Content-Type") || "";
    const isHtml = ct.includes("text/html");
    if (response.ok && isHtml) {
      const newHeaders = new Headers(response.headers);
      for (const [k, v] of Object.entries(SECURITY_HEADERS)) {
        newHeaders.set(k, v);
      }
      return new Response(response.body, {
        status: response.status,
        statusText: response.statusText,
        headers: newHeaders,
      });
    }
    return response;
  },
};
