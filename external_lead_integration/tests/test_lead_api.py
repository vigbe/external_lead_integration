# pyright: reportMissingImports=false
# (odoo framework imports resolve only inside the Odoo runtime)
"""HTTP tests for the ``POST /api/v1/leads`` endpoint (HttpCase).

These exercise the real routing/auth stack: the route runs as ``auth='public'``
and is authenticated through the ``X-API-Key`` header. Since the hardening the
plaintext is exposed ONCE (in-memory ``full_key``) at creation time, so the
setup captures it before any reload and uses that value in the request headers.
"""

import hashlib
import json

from odoo.exceptions import ValidationError
from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestLeadApi(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # create() mints a new random key and exposes the plaintext ONCE via the
        # in-memory ``full_key`` field. Capture it before any reload.
        cls.api_key = cls.env["external.lead.api.key"].create({"name": "Test Key"})
        cls.api_key_plaintext = cls.api_key.full_key
        # Wire a default sales team when one exists (keeps created leads valid).
        cls.team = cls.env["crm.team"].search([], limit=1)
        if cls.team:
            cls.env["ir.config_parameter"].sudo().set_param(
                "external_lead_integration.default_team_id", cls.team.id
            )

    def _post(self, payload, api_key=None, no_header=False):
        """Send a JSON POST to ``/api/v1/leads``.

        Auth handling:
          - default (``no_header=False``, ``api_key=None``) -> use the captured
            plaintext of the test key.
          - ``no_header=True``                              -> omit the
            ``X-API-Key`` header entirely.
          - ``api_key="<value>"``                           -> send that value
            as the ``X-API-Key`` header.
        """
        headers = {"Content-Type": "application/json"}
        if no_header:
            pass  # explicitly omit the X-API-Key header
        elif api_key is None:
            headers["X-API-Key"] = self.api_key_plaintext  # default: test key
        else:
            headers["X-API-Key"] = api_key
        return self.url_open(
            "/api/v1/leads",
            data=json.dumps(payload),
            headers=headers,
            timeout=30,
        )

    # ------------------------------------------------------------------ #
    # Existing tests (updated for hashed keys).                           #
    # ------------------------------------------------------------------ #

    def test_create_lead_success(self):
        resp = self._post(
            {"name": "Jane Doe", "email": "jane@example.com", "message": "Hi"}
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        body = resp.json()
        lead_id = body.get("lead_id")
        self.assertTrue(lead_id)
        lead = self.env["crm.lead"].browse(lead_id)
        self.assertTrue(lead.exists())
        self.assertEqual(lead.email_from, "jane@example.com")

    def test_missing_api_key_returns_401(self):
        resp = self._post(
            {"name": "No Key", "email": "nokey@example.com"}, no_header=True
        )
        self.assertEqual(resp.status_code, 401)

    def test_invalid_api_key_returns_401(self):
        resp = self._post(
            {"name": "Bad", "email": "bad@example.com"}, api_key="wrong-key"
        )
        self.assertEqual(resp.status_code, 401)

    def test_inactive_key_rejected(self):
        self.api_key.active = False
        try:
            resp = self._post({"name": "Archived", "email": "archived@example.com"})
            self.assertEqual(resp.status_code, 401)
        finally:
            self.api_key.active = True

    def test_missing_required_fields_returns_422(self):
        # require_contact defaults to True (param unset) -> empty body -> 422.
        resp = self._post({})
        self.assertEqual(resp.status_code, 422)

    def test_unknown_body_fields_ignored(self):
        # Unknown body keys (e.g. property_ref) must be ignored and the lead
        # still created.
        resp = self._post(
            {"name": "Prop", "email": "prop@example.com", "property_ref": "CL-999"}
        )
        self.assertIn(resp.status_code, (200, 201))
        self.assertTrue(resp.json().get("lead_id"))

    def test_dedup_returns_existing(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "external_lead_integration.dedup", "True"
        )
        resp1 = self._post({"name": "Dup", "email": "dup@example.com"})
        self.assertEqual(resp1.status_code, 201)
        resp2 = self._post({"name": "Dup Again", "email": "dup@example.com"})
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.json().get("status"), "duplicate")

    # ------------------------------------------------------------------ #
    # New tests: hardening + expanded coverage.                           #
    # ------------------------------------------------------------------ #

    def test_key_hashed_not_plaintext(self):
        """After creation the plaintext is gone and only the hash is stored."""
        new_key = self.env["external.lead.api.key"].create({"name": "Hash Check"})
        # The plaintext is never persisted on the legacy `key` column.
        self.assertFalse(new_key.key)
        # The SHA-256 hash is stored (64-char hex digest) and indexed.
        self.assertTrue(new_key.key_hash)
        self.assertEqual(len(new_key.key_hash), 64)
        # A non-sensitive prefix is stored for masked display.
        self.assertTrue(new_key.key_prefix)
        # The full plaintext was exposed once, in memory only.
        self.assertTrue(new_key.full_key)
        self.assertTrue(new_key.full_key.startswith("elp_"))
        # The masked display is built from the prefix.
        self.assertTrue(new_key.key_masked.startswith(new_key.key_prefix))

    def test_auth_with_regenerated_key(self):
        """After regeneration the old key is revoked and the new one works.

        Uses a dedicated key so the shared test key's secret is never rotated
        (keeps the test order-independent regardless of per-method isolation).
        """
        regen_key = self.env["external.lead.api.key"].create({"name": "Regen Key"})
        old_plaintext = regen_key.full_key
        regen_key.action_regenerate_key()
        new_plaintext = regen_key.full_key
        self.assertTrue(new_plaintext)
        self.assertNotEqual(new_plaintext, old_plaintext)
        # The old key no longer authenticates.
        resp_old = self._post(
            {"name": "Old", "email": "oldregen@example.com"}, api_key=old_plaintext
        )
        self.assertEqual(resp_old.status_code, 401)
        # The new key works and creates a lead.
        resp_new = self._post(
            {"name": "New", "email": "newregen@example.com"}, api_key=new_plaintext
        )
        self.assertEqual(resp_new.status_code, 201, resp_new.text)

    def test_overrides_by_key(self):
        """A key carrying team/user overrides forces those on the lead."""
        config_team = self.env["crm.team"].create({"name": "Config Team"})
        key_team = self.env["crm.team"].create({"name": "Key Team"})
        key_user = self.env.ref("base.user_admin")
        self.env["ir.config_parameter"].sudo().set_param(
            "external_lead_integration.default_team_id", config_team.id
        )
        override_key = self.env["external.lead.api.key"].create(
            {
                "name": "Override Key",
                "team_id": key_team.id,
                "user_id": key_user.id,
            }
        )
        plaintext = override_key.full_key
        resp = self._post(
            {"name": "Override", "email": "keyoverride@example.com"},
            api_key=plaintext,
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        lead = self.env["crm.lead"].browse(resp.json()["lead_id"])
        # Key values win over the config defaults.
        self.assertEqual(lead.team_id, key_team)
        self.assertEqual(lead.user_id, key_user)

    def test_config_defaults_applied(self):
        """With config defaults and a key WITHOUT overrides, the lead inherits them."""
        default_team = self.env["crm.team"].create({"name": "Config Default Team"})
        default_stage = self.env["crm.stage"].search([], limit=1)
        default_source = self.env["utm.source"].create({"name": "Config Source"})
        default_user = self.env.ref("base.user_admin")
        icp = self.env["ir.config_parameter"].sudo()
        icp.set_param("external_lead_integration.default_team_id", default_team.id)
        icp.set_param("external_lead_integration.default_user_id", default_user.id)
        if default_stage:
            icp.set_param(
                "external_lead_integration.default_stage_id", default_stage.id
            )
        icp.set_param("external_lead_integration.default_source_id", default_source.id)
        # The test key from setUpClass carries no override.
        resp = self._post({"name": "Defaulted", "email": "defaulted@example.com"})
        self.assertEqual(resp.status_code, 201, resp.text)
        lead = self.env["crm.lead"].browse(resp.json()["lead_id"])
        self.assertEqual(lead.team_id, default_team)
        self.assertEqual(lead.user_id, default_user)
        self.assertEqual(lead.source_id, default_source)
        if default_stage:
            self.assertEqual(lead.stage_id, default_stage)

    def test_invalid_json_returns_400(self):
        """A malformed JSON body returns 400 with code ``invalid_json``."""
        resp = self.url_open(
            "/api/v1/leads",
            data="{not valid json",
            headers={
                "Content-Type": "application/json",
                "X-API-Key": self.api_key_plaintext,
            },
            timeout=30,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "invalid_json")

    def test_body_attribution_ignored(self):
        """After F3, request-body FKs are ignored (only key override + config
        apply). Replaces the old test_non_numeric_team_id_returns_422, which
        expected a body team_id to be validated — that path no longer exists."""
        bogus_team = self.env["crm.team"].create({"name": "Bogus Body Team"})
        bogus_tag = self.env["crm.tag"].create({"name": "Bogus Body Tag"})
        resp = self._post(
            {
                "name": "Body Ignored",
                "email": "bodyignored@example.com",
                "team_id": bogus_team.id,
                "tag_ids": [bogus_tag.id],
            }
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        lead = self.env["crm.lead"].browse(resp.json()["lead_id"])
        # Body values were ignored: the bogus team/tag must not be attributed.
        self.assertNotEqual(lead.team_id, bogus_team)
        self.assertFalse(lead.tag_ids)

    def test_dedup_returns_same_lead_id(self):
        """Dedup returns the SAME lead id, not just a 'duplicate' status."""
        self.env["ir.config_parameter"].sudo().set_param(
            "external_lead_integration.dedup", "True"
        )
        resp1 = self._post({"name": "First", "email": "samedup@example.com"})
        self.assertEqual(resp1.status_code, 201)
        first_id = resp1.json()["lead_id"]
        resp2 = self._post({"name": "Second", "email": "samedup@example.com"})
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.json()["lead_id"], first_id)

    # ------------------------------------------------------------------ #
    # Legacy key migration (pre-hardening plaintext -> SHA-256 hash).    #
    # ------------------------------------------------------------------ #

    def test_legacy_key_migration(self):
        """A pre-hardening plaintext key migrates to a hash on first use and
        keeps authenticating afterwards (EXTRA-2 / F4)."""
        plaintext = "elp_legacy_secret"
        expected_hash = hashlib.sha256(plaintext.encode()).hexdigest()
        # Seed a legacy record bypassing the mint: create with a dummy hash
        # (skips the mint), then clear the hash and store the raw plaintext
        # the old way.
        legacy = self.env["external.lead.api.key"].create(
            {"name": "Legacy Key", "key_hash": "d" * 64}
        )
        legacy.write({"key_hash": False, "key": plaintext})
        self.assertFalse(legacy.key_hash)
        self.assertEqual(legacy.key, plaintext)

        # First request migrates the key on the fly and authenticates.
        resp1 = self._post(
            {"name": "Legacy", "email": "legacy@example.com"}, api_key=plaintext
        )
        self.assertIn(resp1.status_code, (200, 201), resp1.text)

        # The migration cleared the plaintext and stored the SHA-256 hash.
        legacy.invalidate_recordset()
        self.assertFalse(legacy.key)
        self.assertEqual(legacy.key_hash, expected_hash)

        # Second request authenticates via the hash (legacy column empty).
        resp2 = self._post(
            {"name": "Legacy Again", "email": "legacy2@example.com"},
            api_key=plaintext,
        )
        self.assertIn(resp2.status_code, (200, 201), resp2.text)

    def test_duplicate_legacy_key_no_crash(self):
        """Two legacy keys sharing a plaintext must never crash the endpoint
        with a non-JSON 500 (F4). The endpoint stays on its JSON contract."""
        plaintext = "elp_legacy_secret_dup"
        # Two ACTIVE legacy keys with the same plaintext.
        for idx, label in enumerate(("Dup Legacy A", "Dup Legacy B")):
            rec = self.env["external.lead.api.key"].create(
                {"name": label, "key_hash": f"{idx:x}" * 64}
            )
            rec.write({"key_hash": False, "key": plaintext})
        # Several requests with the shared plaintext must all answer with
        # clean JSON (200/201/401), never a non-JSON 500.
        for n in range(3):
            resp = self._post(
                {"name": f"Dup {n}", "email": f"dup{n}@example.com"},
                api_key=plaintext,
            )
            self.assertIn(resp.status_code, (200, 201, 401), resp.text)
            self.assertEqual(
                resp.headers.get("Content-Type", ""),
                "application/json",
                resp.text,
            )

    def test_migrate_legacy_raises_on_duplicate_hash(self):
        """_migrate_legacy_key raises ValidationError when the resulting hash
        already exists on an active record — this is the condition the
        endpoint's try/except (F4) guards against, so the API never answers
        with HTML 500."""
        plaintext = "elp_legacy_collision"
        digest = hashlib.sha256(plaintext.encode()).hexdigest()
        # Active record already holding the hash.
        self.env["external.lead.api.key"].create({"name": "Holder", "key_hash": digest})
        # Active legacy key whose migration would collide.
        legacy = self.env["external.lead.api.key"].create(
            {"name": "Legacy Collision", "key_hash": "c" * 64}
        )
        legacy.write({"key_hash": False, "key": plaintext})
        with self.assertRaises(ValidationError):
            legacy._migrate_legacy_key()
