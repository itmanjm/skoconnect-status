# skoconnect-status

Public status page for SkoConnect — https://status.skoconnect.com (once DNS is
attached; interim URL https://itmanjm.github.io/skoconnect-status/).

Independence requirement (source card): the status page must NOT share hosting
or DNS-failure domains with the product. This repo lives entirely on GitHub
(Pages + Actions); it has zero runtime dependency on GCP/Firebase.

## How it works

- `scripts/probe.py` probes four surfaces every 15 minutes via GitHub Actions
  (`.github/workflows/probe.yml`):
  - Marketing site — https://skoconnect.com (any HTTP response = up)
  - Admin portal — https://admin.skoconnect.com (any HTTP response = up)
  - App & API — Cloud Functions `health` endpoint, which does a real Firestore
    round-trip (requires HTTP 200 + `"status":"ok"`)
  - Document ingestion pipeline — Cloud Run `document-ingestion` (responding =
    up; root returns 405 by design — no public GET handler)
- Each run commits `data/status.json` (current state) and aggregates into
    `data/history.json` (per-component, per-day up/total counts, 90-day retention).
- `index.html` is dependency-free static HTML/CSS/JS that renders the feed and
  additionally does a best-effort live reachability check from the visitor's
  browser. The authoritative status is the monitor feed, not the browser check.
- Uptime bars show the last 14 days per component; 30-day uptime % shown per row.

## Component list changes

Components are defined in `scripts/probe.py` (`COMPONENTS`). Edit, commit to
`main`, the next probe run picks them up.

## Adding the custom domain (Dre / manual DNS step)

When ready to attach status.skoconnect.com:

1. GitHub → repo Settings → Pages → Custom domain: `status.skoconnect.com`
   (this writes the `CNAME` file into the branch automatically).
2. At Namecheap (DNS for skoconnect.com, NS registrar-servers.com) add:
   `status CNAME itmanjm.github.io.` (or A records 185.199.108–111.153).
3. Wait for DNS propagation, then re-enforce HTTPS in Pages settings.

This repo intentionally does NOT carry the CNAME file until that DNS change
lands, to avoid serving 404s on the custom domain during the gap.

## Probe semantics

"Up" follows curl-style reachability semantics: any HTTP response (even 4xx/5xx
from the surface itself) proves the front door is reachable. Network-level
failure (DNS, timeout, refused, TLS) marks the surface down. The API component
is stricter: HTTP 200 + `status:"ok"` from the health endpoint.

## Card / issue lineage

Trello SkoConnect #253, Paperclip JOZ-14. Companion monitoring card: #254
(external uptime monitoring, feeds this page long-term).
