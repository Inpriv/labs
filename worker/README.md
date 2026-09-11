# worker — Inpriv Labs landing page

Cloudflare Worker serving [labs.inpriv.xyz](https://labs.inpriv.xyz).

The page lists experimental tools in this repo (`../tools/...`). Adding a
new experiment is a single object push to the `EXPERIMENTS` array in
`src/index.js` — no deployment changes needed.

## Local dev

```bash
cd worker
npm install
npx wrangler dev
```

Wrangler will prompt for Cloudflare auth on first run.

## Deploy

```bash
npx wrangler deploy
```

The `wrangler.jsonc` declares a route for `labs.inpriv.xyz` as a custom
domain. First-time deploy requires the domain to already be on Cloudflare
(add it via the dashboard or `wrangler domains add`).

## Endpoints

- `GET /` — HTML landing page
- `GET /api/experiments` — JSON list of experiments
