# Inpriv Labs

Experimental privacy & security tools. Public, open source, by [Inpriv](https://github.com/Inpriv).

Landing page: [labs.inpriv.xyz](https://labs.inpriv.xyz)

## Layout

```
labs/
├── worker/                 Cloudflare Worker for labs.inpriv.xyz (Wrangler)
└── tools/
    └── air/                Wi-Fi 802.11 frame injector & PMF/WPA3 auditor
```

## Adding a new experiment

1. Create `tools/<name>/` with your code.
2. Append an entry to `EXPERIMENTS` in [`worker/src/index.js`](worker/src/index.js).
3. Open a PR.

The Worker rebuilds and deploys via `wrangler deploy` from the `worker/`
directory. The landing page picks up the new entry automatically — no HTML
changes required.
