# Fix: web leads assigned to public user — `external_lead_integration`

## Context

Root cause (verified in local `local_main_rs` and prod `main_rs_db`): `POST /api/v1/leads`
runs as `auth='public'`; Odoo 19 `sudo()` does not change `uid`; `crm.lead.user_id` has
`default=lambda self: self.env.user`. With no `user_id` on any API key and no
`external_lead_integration.default_user_id` param, every lead lands on the public user
(salesperson AND `create_uid`). Field `domain="[('share','=',False)]"` is UI-only and is
not enforced by the ORM on create.

Portal leads (Mercado Libre / Yapo / etc.) are unaffected: their connectors set
`user_id_venta` / `user_id_arriendo` explicitly.

## User decisions (2026-09-28)

1. Scope: production config fix + code hardening + deploy.
2. Execution: Pi applies changes via SSH (IAP tunnel) + SQL on `main_rs_db`.
3. Existing public-user leads: reassign by team (4 → venta@, 5 → arriendo@).
4. Keys "Captación pagina" and "Otras solicitudes" → `venta@andrassy.cl`.

## Production identity map (verified read-only)

- `venta@andrassy.cl` = res_users id 11 (active, share=false)
- `arriendo@andrassy.cl` = res_users id 14 (active, share=false)
- `public` = res_users id 4
- Team 4 = Equipo de Ventas; Team 5 = Equipo de Arriendos
- Leads with user_id=4: 4664 (archived, t5), 20153 (t5), 20154 (t5), 20194 (t4),
  20204 (t4), 20530 (t4)

## Tasks

- [x] Verify users/teams/leads in production (read-only)
- [x] SQL: set user_id on the 4 API keys (1→11, 2→14, 3→11; key 4 kept its
      preexisting roberto@ (uid 6) — user confirmed)
- [x] SQL: reassign 6 public-user leads by team (t4→11, t5→14) — 0 remaining
- [x] Code: explicit `vals["user_id"] = False` when no override resolves + test
      (+ guarded `customer_rank` for vanilla Odoo 19 partner model)
- [x] Run module test suite: 18/18 green on fresh `test_eli_tmp` DB
      (requires `--db-filter`; dbfilter mismatch caused phantom 401s)
- [x] Work-unit commit: `c54e037` on `fix/public-user-salesperson-default`
- [x] Deploy: tar-over-IAP to `/mnt/extra-addons/common/external_lead_integration/`
      + `docker restart main_rs` (clients untouched)
- [x] Post-deploy verification: endpoint JSON-401 alive + E2E POST created
      lead 20816 with `user_id=11, create_uid=4`; test lead + temp key deleted

## Deploy notes

- `sync_to_vps.sh` restarts ALL containers; we deviate with a targeted rsync of this
  addon + `docker restart main_rs` to avoid downtime on clt_rs_00X.
- Python-only change: no `-u` module upgrade needed; restart loads new controller.
- Client containers keep old code until their own next restart (change is
  backwards-compatible: unassigned instead of public user).

## Evidence log

- Local diagnosis: tracking showed 'Public user' → 'Luis Quintana' manual fixes by
  administrador@ia-prop.com (leads 20200, 20280).
- Prod containers: main_rs (odoo:19.0-custom-20260915), clt_rs_003/004/005.
- Prod DB: main_rs_db @ 10.33.0.3.
- Deploy commit: c54e037 (version 19.0.1.4.4). Prod ir_module_module still
  stamps 19.0.1.4.0 until the next `-u` upgrade (cosmetic).
- `customer_rank` exists in prod only via custom addons (contacts_management /
  real_estate_products); core Odoo 19 removed it. Fix guards on field presence.
- Pre-existing unrelated errors observed in main_rs logs: yapo_connector renewal
  crash (pub 125) and product.real_estate.ml_item_id not-stored SQL error —
  flagged as follow-ups, not touched by this fix.
