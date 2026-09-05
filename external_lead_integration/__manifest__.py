# Odoo __manifest__.py is a bare dict literal (read via ast.literal_eval);
# the "unused expression" warning is an unavoidable false positive.
# pyright: reportUnusedExpression=false
{  # noqa: B018  # Odoo manifest: module-level dict literal read via exec()
  "name": "External Lead Integration",
  "version": "19.0.1.4.0",
  "category": "Sales/CRM",
  "summary": "Public REST endpoint to create CRM leads from external websites",
  "description": """
External Lead Integration
=========================

Published for Odoo 16.0, 17.0, 18.0 and 19.0 (Community and Enterprise).

Exposes a versioned REST endpoint (``POST /api/v1/leads``) so that external
websites, landing pages and marketing forms can create ``crm.lead`` records
without an Odoo user session.

Highlights
----------

* **API-key authentication**: each integration is issued a secret token
  (``external.lead.api.key``) validated through the ``X-API-Key`` header.
  Keys are stored as a SHA-256 hash (plaintext never persisted),
  group-restricted, unique, archivable and can be rotated.
* **Real HTTP semantics**: the endpoint runs as ``type='http'`` /
  ``auth='public'`` and answers with explicit status codes
  (``201`` created, ``200`` duplicate, ``400/401/422/500`` errors) and a JSON
  body.
* **Configurable defaults**: default sales team, salesperson, stage, source,
  contact-info requirement and optional email-based deduplication are stored in
  ``res.config.settings`` (persisted through ``ir.config_parameter``).
* **Per-key overrides**: an API key can force a sales team / salesperson.
* **Extensible**: optional real-estate (inmobiliario) fields are mapped to
  ``crm.lead`` custom fields **only when those fields exist**, so the module
  stays compatible with a plain CRM.

Security note
-------------

Keys are stored as a **SHA-256 hash** (``key_hash``); the plaintext is never
persisted. The full secret is shown **once** — through a copyable wizard —
right after creation or regeneration, then only a masked value is displayed.
Legacy plaintext keys (pre-hardening) are migrated lazily to a hash on their
first successful request. The endpoint should always sit behind a reverse
proxy with rate limiting and abuse protection (e.g. reCAPTCHA) at the edge.
""",
  "author": "Victor Bastías Escobar",
  "website": "https://vicbas.com",
  "support": "contacto@vicbas.com",
  "maintainer": "Victor Bastías Escobar",
  "license": "LGPL-3",
  "depends": [
    "base",
    "crm",
  ],
  "data": [
    "security/security_groups.xml",
    "security/ir.model.access.csv",
    "views/external_lead_api_key_views.xml",
    "views/external_lead_api_key_wizard_views.xml",
    "views/res_config_settings_views.xml",
  ],
  "application": True,
  "installable": True,
  "auto_install": False,
  "images": [
    "static/description/thumbnail.png",
  ],
}
