# Museumwijzer Sync API (Cloudflare Worker)

Provides a lightweight, zero-maintenance anonymous 6-digit sync code service for Museumwijzer lists, backed by **Cloudflare Workers KV**.

- **Zero Accounts / Zero Passwords**: Uses temporary 6-digit numeric codes (e.g. `582-913`).
- **Privacy First**: Only stores anonymous arrays of museum slugs and visited status.
- **Auto-Expiry**: Automatically expires entries after 30 days of inactivity.
- **Free Tier**: Uses Cloudflare's free tier (100,000 requests/day, 1,000 KV writes/day, 100,000 KV reads/day).

---

## 2-Minute Deployment Guide

### Option 1: Via Cloudflare Web Dashboard (Easiest — No CLI needed)

1. Log in to [dash.cloudflare.com](https://dash.cloudflare.com/).
2. In the left navigation, go to **Storage & Databases** → **KV** → Click **Create Namespace**.
   - Name: `MUSEUM_SYNC_KV` → Click **Add**.
3. In the left navigation, go to **Workers & Pages** → Click **Create Application** → **Create Worker**.
   - Name: `museumwijzer-sync` → Click **Deploy**.
4. Click **Edit code**:
   - Paste the contents of [`worker.js`](./worker.js) into the editor.
   - Click **Deploy**.
5. Go back to your Worker's dashboard → **Settings** → **Variables and Secrets**:
   - Scroll down to **KV Namespace Bindings** → Click **Add binding**.
   - Variable name: `MUSEUM_SYNC_KV`
   - KV namespace: select the `MUSEUM_SYNC_KV` namespace you created in Step 2.
   - Click **Save and deploy**.
6. (Optional) In **Settings** → **Domains & Routes**:
   - Add Custom Domain: e.g. `sync.museumwijzer.vlesyk.com` (Cloudflare sets up the DNS and SSL automatically in seconds!).

---

### Option 2: Via Wrangler CLI

If you have Node.js and Wrangler installed:

```bash
cd worker
# 1. Create the KV namespace
npx wrangler kv:namespace create "MUSEUM_SYNC_KV"

# 2. Copy the generated namespace ID into wrangler.toml:
# id = "<id_from_above>"

# 3. Deploy the worker
npx wrangler deploy
```

---

## API Endpoints

### 1. Save or Update List
* **URL**: `POST /api/sync`
* **Body**:
  ```json
  {
    "code": "582913",  // optional: if omitted, generates a new 6-digit code
    "items": [
      { "slug": "rijksmuseum", "visited": false, "note": "Early morning" },
      { "slug": "van-gogh-museum", "visited": true, "note": "" }
    ]
  }
  ```
* **Response**:
  ```json
  {
    "success": true,
    "code": "582913",
    "updated_at": "2026-09-25T21:00:00.000Z"
  }
  ```

### 2. Fetch List by Code
* **URL**: `GET /api/sync/582913`
* **Response**:
  ```json
  {
    "code": "582913",
    "updated_at": "2026-09-25T21:00:00.000Z",
    "items": [
      { "slug": "rijksmuseum", "visited": false, "note": "Early morning" },
      { "slug": "van-gogh-museum", "visited": true, "note": "" }
    ]
  }
  ```
