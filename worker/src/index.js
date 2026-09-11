/**
 * Inpriv Labs — landing page worker (labs.inpriv.xyz).
 *
 * Renders an HTML page listing experimental tools. New experiments are added
 * to the `EXPERIMENTS` array below; no other changes required.
 */

const EXPERIMENTS = [
  {
    slug: "air",
    name: "air",
    tagline: "Wi-Fi 802.11 frame injector & PMF/WPA3 resilience auditor",
    repo: "https://github.com/Inpriv/labs/tree/main/tools/air",
    docs: "https://github.com/Inpriv/labs/blob/main/tools/air/README.md",
    status: "experimental",
    description:
      "Interactive Python CLI for authorized 802.11 deauthentication testing. " +
      "Switches the wireless adapter into monitor mode (airmon-ng / iw), " +
      "discovers APs and connected clients, and loops deauth frames with " +
      "configurable reason codes. Use it to verify whether your WPA3 / PMF " +
      "deployment actually protects management frames.",
    install: [
      "git clone https://github.com/Inpriv/labs.git",
      "cd labs/tools/air",
      "sudo ./install.sh",
      "sudo python air.py -i wlan0",
    ],
    requirements: ["Linux", "monitor-mode-capable adapter", "Scapy", "airmon-ng"],
    legal:
      "Authorized use only. Deauthentication against networks you do not own " +
      "or have explicit written permission to test is illegal in most jurisdictions.",
  },
];

function escape(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderExperiment(exp) {
  return `
    <article class="card" id="${escape(exp.slug)}">
      <header>
        <h2>${escape(exp.name)}</h2>
        <span class="status status-${escape(exp.status)}">${escape(exp.status)}</span>
      </header>
      <p class="tagline">${escape(exp.tagline)}</p>
      <p class="description">${escape(exp.description)}</p>

      <h3>Quick install</h3>
      <pre><code>${escape(exp.install.join("\n"))}</code></pre>

      <h3>Requirements</h3>
      <ul class="reqs">
        ${exp.requirements.map((r) => `<li>${escape(r)}</li>`).join("")}
      </ul>

      <p class="links">
        <a href="${escape(exp.repo)}">Source</a>
        &middot;
        <a href="${escape(exp.docs)}">Docs</a>
      </p>

      <p class="legal">${escape(exp.legal)}</p>
    </article>
  `;
}

function renderPage() {
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Inpriv Labs</title>
  <meta name="description" content="Experimental privacy &amp; security tools by Inpriv." />
  <link rel="icon" href="https://inpriv.xyz/favicon.ico" />
  <style>
    :root {
      --bg: #0b0b0c;
      --fg: #e6e6e6;
      --muted: #8a8a8a;
      --accent: #6ee7b7;
      --card: #141416;
      --border: #1f1f23;
      --warn: #f87171;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--fg);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      line-height: 1.55;
    }
    .wrap { max-width: 880px; margin: 0 auto; padding: 3rem 1.5rem; }
    header.hero h1 {
      font-size: 2.5rem;
      margin: 0 0 0.5rem;
      letter-spacing: -0.02em;
    }
    header.hero p { color: var(--muted); margin: 0; }
    section.labs { margin-top: 3rem; }
    .card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1.5rem;
      margin-bottom: 1.5rem;
    }
    .card header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 0.5rem; }
    .card h2 { margin: 0; font-size: 1.5rem; font-family: ui-monospace, "SF Mono", Menlo, monospace; }
    .card h3 { margin-top: 1.5rem; font-size: 0.9rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); }
    .tagline { color: var(--accent); margin: 0.25rem 0 1rem; font-weight: 500; }
    .description { color: var(--fg); }
    .status {
      font-size: 0.7rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      padding: 0.25rem 0.5rem;
      border-radius: 4px;
      background: var(--border);
      color: var(--muted);
    }
    .status-experimental { color: var(--warn); }
    pre {
      background: #000;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0.75rem 1rem;
      overflow-x: auto;
    }
    pre code { font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 0.85rem; }
    ul.reqs { margin: 0.5rem 0; padding-left: 1.25rem; color: var(--muted); }
    .links a { color: var(--accent); text-decoration: none; }
    .links a:hover { text-decoration: underline; }
    .legal { color: var(--warn); font-size: 0.85rem; margin-top: 1.5rem; padding-top: 1rem; border-top: 1px solid var(--border); }
    footer { margin-top: 4rem; padding-top: 2rem; border-top: 1px solid var(--border); color: var(--muted); font-size: 0.85rem; text-align: center; }
    footer a { color: var(--muted); }
  </style>
</head>
<body>
  <div class="wrap">
    <header class="hero">
      <h1>Inpriv Labs</h1>
      <p>Experimental privacy &amp; security tools. Public research, open source.</p>
    </header>

    <section class="labs">
      ${EXPERIMENTS.map(renderExperiment).join("\n")}
    </section>

    <footer>
      <p>
        <a href="https://inpriv.xyz">inpriv.xyz</a>
        &middot;
        <a href="https://github.com/Inpriv">github.com/Inpriv</a>
      </p>
      <p>MIT licensed unless otherwise noted.</p>
    </footer>
  </div>
</body>
</html>`;
}

export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (url.pathname === "/" || url.pathname === "/index.html") {
      return new Response(renderPage(), {
        headers: { "content-type": "text/html; charset=utf-8" },
      });
    }
    if (url.pathname === "/api/experiments") {
      return new Response(JSON.stringify(EXPERIMENTS, null, 2), {
        headers: { "content-type": "application/json" },
      });
    }
    return new Response("Not Found", { status: 404 });
  },
};
