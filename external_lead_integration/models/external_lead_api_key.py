"""``external.lead.api.key`` — secret tokens used to authenticate the public
``POST /api/v1/leads`` endpoint.

Each integration (landing, marketing site, partner portal) gets its own key.
Keys are validated in the controller (see ``controllers/base_api.py``) and the
matching ``crm.lead`` is created with ``sudo()``, so anonymous callers never
touch the model ACL directly.

Security: keys are stored as a **SHA-256 hash** (``key_hash``); the plaintext is
never persisted. The full secret is shown **once** — through the in-memory
``full_key`` field — right after creation or regeneration, then only a masked
value (``key_masked``) is displayed. Legacy plaintext keys (pre-hardening) are
migrated lazily to a hash on their first successful request
(:meth:`_migrate_legacy_key`).
"""

import hashlib
import logging
import secrets

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

# Prefix shared by every generated key, so an operator can recognise where a
# leaked token comes from (e.g. a stray commit in a client repository).
_KEY_PREFIX = "elp_"
# Number of leading plaintext chars kept as a non-sensitive display prefix.
_KEY_PREFIX_LEN = 8


class ExternalLeadApiKey(models.Model):
    _name = "external.lead.api.key"
    _description = "External Lead API Key"
    _order = "name"

    name = fields.Char(
        string="Label",
        required=True,
        help='Human label, e.g. "Landing ia-prop.cl"',
    )
    # LEGACY plaintext key from before the hardening. Kept ONLY so existing keys
    # can be migrated to ``key_hash`` on first use; it is cleared afterwards.
    # New keys never store their plaintext here.
    key = fields.Char(
        string="API Key (legacy)",
        copy=False,
        help="LEGACY plaintext key, kept only to migrate pre-hardening keys. It "
        "is cleared once the SHA-256 ``key_hash`` is computed and is never set "
        "for keys created after the hardening.",
    )
    # SHA-256 hex digest of the plaintext key — the real authentication column.
    key_hash = fields.Char(
        string="Key hash",
        copy=False,
        index=True,
        help="SHA-256 hex digest of the API key. This is the column used for "
        "authentication lookups; the plaintext is never stored.",
    )
    # Non-sensitive prefix (first chars of the plaintext) used only to build the
    # masked display, so an operator can tell keys apart at a glance.
    key_prefix = fields.Char(
        string="Key prefix",
        copy=False,
        help="First characters of the plaintext key (non-sensitive), shown "
        "masked so operators can distinguish keys without exposing the secret.",
    )
    # Transient, non-stored: holds the plaintext IN MEMORY only right after
    # create/regenerate so the form can display it exactly once (GitHub-style).
    # It is never persisted and cannot be recovered later.
    full_key = fields.Char(
        string="API key",
        store=False,
        readonly=True,
        help="Full API key. Shown ONCE after creation or regeneration; it is "
        "never persisted and cannot be recovered later.",
    )
    # Masked representation for everyday display.
    key_masked = fields.Char(
        string="Key",
        compute="_compute_key_masked",
        store=False,
        help="Masked representation of the key, built from the non-sensitive prefix.",
    )
    active = fields.Boolean(default=True)
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Site / Client",
        ondelete="set null",
    )
    team_id = fields.Many2one(
        comodel_name="crm.team",
        string="Sales Team",
        ondelete="set null",
        help="When set, leads created with this key default to this team.",
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        string="Salesperson",
        ondelete="set null",
        help="When set, leads created with this key default to this salesperson.",
    )
    source_id = fields.Many2one(
        comodel_name="utm.source",
        string="Source",
        ondelete="set null",
        help="When set, leads created with this key default to this UTM source.",
    )
    campaign_id = fields.Many2one(
        comodel_name="utm.campaign",
        string="Campaign",
        ondelete="set null",
        help="When set, leads created with this key default to this UTM campaign.",
    )
    last_used_on = fields.Datetime(readonly=True)
    company_id = fields.Many2one(
        comodel_name="res.company",
        default=lambda self: self.env.company,
        ondelete="restrict",
    )

    @api.depends("key_prefix")
    def _compute_key_masked(self):
        for record in self:
            if record.key_prefix:
                record.key_masked = f"{record.key_prefix}••••••••"
            else:
                record.key_masked = "••••••••"

    @api.constrains("key_hash")
    def _check_key_hash_unique(self):
        """Enforce ``key_hash`` uniqueness, ignoring empty values.

        A plain SQL ``UNIQUE(key_hash)`` is deliberately NOT used: during the
        lazy migration several records legitimately have an empty hash, and we
        want those to coexist portably. The ``search_count`` check lets us skip
        empties explicitly and works across every supported database.
        """
        for record in self:
            if not record.key_hash:
                continue
            duplicates = self.search_count(
                [
                    ("key_hash", "=", record.key_hash),
                    ("id", "!=", record.id),
                ]
            )
            if duplicates:
                raise ValidationError(_("This API key is already in use."))

    @api.model_create_multi
    def create(self, vals_list):
        """Generate a strong random key for each new record.

        The plaintext is returned to the caller through the in-memory
        ``full_key`` field (shown once via the copyable wizard); it is never
        persisted — only its SHA-256 hash (``key_hash``) and a non-sensitive
        prefix (``key_prefix``) are stored.
        """
        generated_keys = []
        for vals in vals_list:
            # F1: drop any legacy/caller-supplied ``key`` UNCONDITIONALLY and
            # BEFORE the ``key_hash`` short-circuit, so a caller passing both a
            # precomputed ``key_hash`` and a legacy ``key`` can never persist
            # the plaintext. The plaintext is never stored at rest.
            vals.pop("key", None)
            if vals.get("key_hash"):
                # Caller supplied a precomputed hash directly; nothing to mint.
                generated_keys.append(None)
                continue
            plaintext = _KEY_PREFIX + secrets.token_urlsafe(32)
            vals["key_hash"] = hashlib.sha256(plaintext.encode()).hexdigest()
            vals["key_prefix"] = plaintext[:_KEY_PREFIX_LEN]
            generated_keys.append(plaintext)
        records = super().create(vals_list)
        for record, plaintext in zip(records, generated_keys, strict=True):
            if plaintext:
                record.full_key = plaintext
        return records

    def action_regenerate_key(self):
        """Issue a new random key for the current record (form button).

        The new plaintext is exposed once through the in-memory ``full_key``
        field; only its hash and prefix are persisted, and any legacy plaintext
        is cleared.
        """
        self.ensure_one()
        plaintext = _KEY_PREFIX + secrets.token_urlsafe(32)
        self.write(
            {
                "key_hash": hashlib.sha256(plaintext.encode()).hexdigest(),
                "key_prefix": plaintext[:_KEY_PREFIX_LEN],
                "key": False,
            }
        )
        self.full_key = plaintext
        return True

    def action_open_regenerate_wizard(self):
        """Open the copyable wizard to rotate this key and reveal it once.

        The header "Regenerate Key" button points here: instead of mutating
        the key inline (which left no UI to copy the new secret), it opens the
        ``external.lead.api.key.wizard`` prefilled with this record. The
        actual rotation happens in the wizard, which then displays the new
        plaintext exactly once.
        """
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Regenerate API Key"),
            "res_model": "external.lead.api.key.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_key_id": self.id},
        }

    def _migrate_legacy_key(self):
        """Lazily hash a legacy plaintext ``key`` into ``key_hash`` + ``key_prefix``.

        Called from the controller the first time a pre-hardening key is used.
        After migration the plaintext ``key`` is cleared, so only the hash
        remains at rest.
        """
        for record in self:
            if record.key_hash or not record.key:
                continue
            record.write(
                {
                    "key_hash": hashlib.sha256(record.key.encode()).hexdigest(),
                    "key_prefix": record.key[:_KEY_PREFIX_LEN],
                    "key": False,
                }
            )

    def log_usage(self):
        """Stamp ``last_used_on`` each time the key authenticates a request."""
        for record in self:
            record.last_used_on = fields.Datetime.now()

    @api.ondelete(at_uninstall=False)
    def _unlink_if_active(self):
        """Active keys cannot be deleted — archive them instead.

        This is both the Odoo 19 delete-validation pattern and a safer default
        for credentials: an archived key stops working but stays auditable.
        """
        for record in self:
            if record.active:
                raise UserError(_("Archive the key instead of deleting it."))
