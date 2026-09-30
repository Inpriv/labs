# trns site - Cloudflare Worker

Serves `../site` at **https://trns.inpriv.xyz** (Worker `trns-pwa`) with the
Inpriv maintenance gate and strict security headers.

```bash
cd worker
npx wrangler@4 deploy --dry-run    # validate
npx wrangler@4 deploy              # ship
npx wrangler@4 rollback            # undo the last deploy
```

The Worker name must stay `trns-pwa`: it owns the `trns.inpriv.xyz` custom domain.
