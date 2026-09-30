// trns.inpriv.xyz - project site (static, served from ../site).
//
// The Worker exists to (1) honour the Inpriv admin kill-switch, (2) attach
// security headers, and (3) keep HTML / the service worker fresh so a deploy
// is visible immediately while images and other assets stay cacheable.

import { maintenanceGate, maintenancePage } from "./gate.js";

// The page is fully self-contained: no inline script/style, no third parties.
const SECURITY_HEADERS = {
  "Content-Security-Policy":
    "default-src 'self'; " +
    "script-src 'self'; " +
    "style-src 'self'; " +
    "img-src 'self' data:; " +
    "font-src 'self'; " +
    "connect-src 'self'; " +
    "worker-src 'self'; " +
    "manifest-src 'self'; " +
    "base-uri 'self'; " +
    "form-action 'none'; " +
    "frame-ancestors 'none'; " +
    "object-src 'none'",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer",
  "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
  "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload",
};

const REVALIDATE = /(^\/$|\.html$|\/sw\.js$|\.webmanifest$)/;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // Always answer health checks (monitoring, admin panel).
    if (url.pathname === "/api/health") {
      return Response.json({ ok: true, service: "trns" }, {
        headers: { "Cache-Control": "no-store" },
      });
    }

    // Admin kill-switch. Fails open if admin.inpriv.xyz is unreachable.
    const gate = await maintenanceGate("trns");
    if (gate.locked) return maintenancePage("trns", gate.message);

    const response = await env.ASSETS.fetch(request);
    const headers = new Headers(response.headers);

    if (REVALIDATE.test(url.pathname)) {
      headers.set("Cache-Control", "no-cache");
    }
    if ((headers.get("Content-Type") || "").includes("text/html")) {
      for (const [k, v] of Object.entries(SECURITY_HEADERS)) headers.set(k, v);
    }

    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers,
    });
  },
};
