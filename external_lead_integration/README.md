# External Lead Integration

Public REST endpoint that lets external websites, landing pages and marketing
forms create **CRM leads** (`crm.lead`) in Odoo without an
Odoo user session.

> Available on the Odoo Apps Store for Odoo 16.0, 17.0, 18.0 and 19.0 — by
> [Victor Bastías Escobar](https://vicbas.com).

- **Endpoint:** `POST /api/v1/leads`
- **Auth:** secret API key sent in the `X-API-Key` header
- **Format:** JSON request body, JSON response with **real HTTP status codes**

> Odoo 19 Community · Python 3.10+ · depends on `base` + `crm`

---

## Install

```bash
# in the Odoo 19 container, with the addons path configured
odoo -i external_lead_integration -d <your_db>
# or update later
odoo -u external_lead_integration -d <your_db>
```

Then activate **Developer mode**, open **Settings**, open the **External Leads**
settings tab and click **Manage API Keys** (or go to **CRM ‣ Configuration ‣
External Lead API Keys**).

---

## Create an API key

1. Go to **CRM ‣ Configuration ‣ External Lead API Keys ‣ New API Key**.
2. Give it a **Label** (e.g. "Landing page A") and click **Generate Key**.
3. The **API key** is generated and shown **once** in a copyable wizard — copy it
   now; it cannot be recovered later (only its SHA-256 hash is stored).
4. Optionally set a **Sales Team** / **Salesperson** to force defaults for this
   key.
5. Use **Regenerate Key** to rotate the secret at any time (a new wizard shows the
   new key once).
6. **Archive** a key to revoke it (active keys cannot be deleted, by design).

---

## Request contract — `POST /api/v1/leads`

Send `Content-Type: application/json` and `X-API-Key: <your key>`.

| Field                 | Type    | Required\* | Description                                                        |
| --------------------- | ------- | ---------- | ------------------------------------------------------------------ |
| `name`                | string  | yes\*      | Contact name.                                                      |
| `email`               | string  | yes\*\*    | Contact email (one of `email`/`phone` required when contact on).   |
| `phone`               | string  | yes\*\*    | Contact phone.                                                     |
| `message` / `description` | string | no     | Free text → stored in the lead `description`.                      |
| `title`               | string  | no         | Lead title. Defaults to `Lead web - {name} - {date}`.              |
| `type`                | string  | no         | `lead` (default) or `opportunity`.                                 |

> **Attribution is NOT taken from the request body.** Sales team, salesperson,
> UTM source and stage come **only** from the API-key override and the module's
> config defaults (see Settings). Request-body `team_id` / `user_id` /
> `source_id` / `medium_id` / `campaign_id` / `tag_ids` are ignored, so a caller
> can never inject arbitrary attribution or tags.

\* "Required" depends on the **Require contact info** setting (on by default):
when on, `name` **and** (`email` **or** `phone`) are mandatory.
\*\* Either `email` or `phone` satisfies the contact requirement.

---

### curl example

```bash
curl -X POST https://crm.example.com/api/v1/leads \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR-API-KEY" \
  -d '{
    "name": "Juan Pérez",
    "email": "juan@example.com",
    "phone": "+56912345678",
    "message": "I would like more information about your services",
    "title": "Website contact"
  }'
```

### JavaScript `fetch` example

```javascript
const res = await fetch("https://crm.example.com/api/v1/leads", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "X-API-Key": "YOUR-API-KEY",
  },
  body: JSON.stringify({
    name: "Juan Pérez",
    email: "juan@example.com",
    message: "I want more info",
  }),
});
    const data = await res.json();
    console.log(data); // { lead_id: 42, name: "...", status: "created" }
    ```
    
    ---
    
    ## CORS (cross-origin websites)
    
    Browsers block a `fetch` to a different domain than the page unless the server
    returns CORS headers. Since the **website** (e.g. `https://www.example.com`) and the
    **Odoo database** (its `web.base.url`, e.g. `https://odoo.example.com`) are almost
    always on different domains, you must allow the website's origin.
    
    The module ships a built-in **CORS allowlist**:
    
    1. Go to **Settings ‣ External Leads ‣ Security ‣ Allowed CORS origins**.
    2. Enter the comma-separated origins of the sites that may call the endpoint,
       e.g. `https://www.example.com, https://example.com`.
    3. The endpoint answers the browser `OPTIONS` preflight with
       `Access-Control-Allow-Origin` (the exact origin), `Access-Control-Allow-Methods`
       (`POST, OPTIONS`) and `Access-Control-Allow-Headers` (`Content-Type, X-API-Key`).
    4. Leave the field **empty** to block every cross-origin request (same-origin only).
    
    > Only origins in the allowlist are echoed back; unknown origins get no CORS
    > header, so the browser blocks them. This is read from
    > `ir.config_parameter` `external_lead_integration.cors_allowed_origins`, so it can
    > also be set directly in **Settings ‣ Technical ‣ Parameters**.
    
    A ready-to-use reference contact form (HTML + CSS + JS) lives in
    `static/src/lead-form.html`.
    
    ---
    
    ## Responses

### Success — `201 Created`

```json
{ "lead_id": 42, "name": "Lead web - Juan Pérez - 2025-01-01", "status": "created" }
```

### Success (duplicate) — `200 OK`

When **Deduplicate by email** is on and the email matches an existing open lead:

```json
{ "lead_id": 7, "name": "Lead web - ...", "status": "duplicate" }
```

### Errors

| Status | `error.code`       | Meaning                                              |
| ------ | ------------------ | ---------------------------------------------------- |
| `400`  | `invalid_json`     | Body is not valid JSON / not a JSON object.          |
| `401`  | `invalid_api_key`  | Missing, unknown or archived `X-API-Key`.            |
| `422`  | `validation`       | Missing required fields or a non-numeric id.         |
| `422`  | `create_failed`    | `crm.lead` rejected the values (e.g. constraint).    |
| `500`  | `internal_error`   | Unexpected server error (logged).                    |

Error body shape:

```json
{ "error": { "code": "validation", "message": "...", "fields": ["name", "email"] } }
```

---

## Settings (Settings ‣ External Leads tab)

| Setting               | Effect                                                              |
| --------------------- | ------------------------------------------------------------------- |
| Require contact info  | Require `name` + (`email` or `phone`). Default **on**.              |
| Deduplicate by email  | Return the existing lead when the email matches an open lead.       |
| Default Sales Team    | Used when neither the caller nor the API key sets one.              |
| Default Salesperson   | Used when neither the caller nor the API key sets one.              |
| Default Stage         | Forced stage on created leads when set.                             |
| Default Source        | UTM source when the caller provides none.                           |
| Allowed CORS origins  | Comma-separated website origins allowed to call the endpoint cross-origin. Leave empty for same-origin only. |

---

## Security notes

- **Rotate keys** regularly; use **Regenerate Key** and update the website.
- **Revoke** by archiving the key (active keys cannot be deleted).
- Keys are stored as a **SHA-256 hash** (`key_hash`); the plaintext is **never
  persisted**. The full key is shown **once** via a copyable wizard right after
  creation or regeneration, then only a masked value (`elp_••••••••`) is
  displayed. Legacy plaintext keys (pre-hardening) are migrated lazily to a hash
  on their first successful request. Authentication compares the SHA-256 digests
  in constant time.
- **Always put the endpoint behind a reverse proxy** (nginx) with **TLS**,
  **rate limiting** and abuse protection (e.g. **reCAPTCHA** / WAF) at the edge.
- The route uses `auth='public'` (Odoo's idiomatic mode for public endpoints
  that write); all `crm.lead` writes go through `sudo()` after manual
  `X-API-Key` validation, so anonymous callers never touch model ACLs and
  cannot bypass the key check.
- Consider IP allow-listing per key and request logging/monitoring.

---

## Extensibility

The endpoint path is versioned (`/api/v1/...`) so you can evolve the contract
without breaking existing integrations. Additional endpoints (e.g.
`POST /api/v1/contacts` to create `res.partner`, or `/api/v1/leads/<id>` to
read status) can be added in `controllers/main.py` and share the helpers in
`controllers/base_api.py` (`_json_ok`, `_json_error`, `_get_api_key_record`).

---

## License

LGPL-3 — © Victor Bastías Escobar (vicbas.com)
