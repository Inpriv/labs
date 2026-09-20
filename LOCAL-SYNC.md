# Local sync note

Klon z `Inpriv/labs` branch `trns/pwa` wykonany **2026-09-20**.

```
C:\Users\mckkw\Desktop\Private\.projects\inpriv-labs-trns-pwa\
```

Branch na GitHubie (zdalny) ma już wszystkie commity; ten klon to
po prostu mirror, żeby pracować lokalnie bez `gh api` przy każdym
zapytaniu.

## Co tu jest

- `tools/trns/` — CLI + cały TWA/PWA poddrzewo (patrz `tools/trns/README.md`)
- `tools/trns/trns-0.1.0-beta.apk` — APK ściągnięty z GitHub Release
  (`v0.1.0-beta`); SHA256 = `323be853…8d30ff`, dokładnie ten sam co
  został zbudowany lokalnie przez gradle 8.11.1
- `worker/` — landing worker (Inpriv Labs homepage), w tym klonie
  niemodyfikowany

## Reprodukowanie buildu APK

Zobacz `tools/trns/apk/build.sh` albo przeczytaj
`tools/trns/README.md`, sekcja **Building**.

## Aktualizacja (gdy pushujesz nowy commit na `trns/pwa`)

```bash
cd C:\Users\mckkw\Desktop\Private\.projects\inpriv-labs-trns-pwa
git pull --rebase origin trns/pwa
```

Albo (po merge'u PR do `main`):

```bash
git remote set-head origin main
git fetch --all --prune
git checkout main && git pull
```

## Custom domain DNS

`trns.inpriv.xyz` wskazuje na Cloudflare (resolver 1.1.1.1 widzi
`104.21.30.221`/`172.67.173.224`). Lokalny Windows resolver może
cache'ować NXDOMAIN przez kilka minut — jeśli z localhost wygląda
jak niedostępne, sprawdź `trns.inpriv.xyz` przez `curl --resolve` albo
po prostu poczekaj.
