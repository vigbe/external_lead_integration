"""Copyable wizard that reveals a freshly minted API key exactly once.

GitHub-style: the plaintext is never stored at rest on ``external.lead.api.key``
and cannot be recovered later. This wizard holds the secret on a transient record
just long enough for the operator to copy it; closing the wizard deletes the
record (and the plaintext) immediately, and Odoo's transient auto-vacuum is the
backstop.

Why a wizard (and not the form): the model's ``full_key`` is a non-stored,
non-computed field, so it returns empty on an RPC ``read`` — the web client
reloads the form in a separate request/transaction and the value is gone. Within
the wizard flow, however, the model's ``create`` / ``action_regenerate_key`` set
``full_key`` in the SAME transaction; the wizard reads it there and stores it on
its own transient row, so the client's re-read of the wizard returns it. ``new_key``
is therefore ``store=True`` on the transient: a literal ``store=False`` would
re-introduce the very invisibility bug (F2) this wizard exists to fix.
"""

from odoo import _, fields, models


class ExternalLeadApiKeyWizard(models.TransientModel):
    _name = "external.lead.api.key.wizard"
    _description = "External Lead API Key Wizard"

    name = fields.Char(
        string="Label",
        help='Human label for a new key, e.g. "Landing ia-prop.cl".',
    )
    key_id = fields.Many2one(
        comodel_name="external.lead.api.key",
        string="API key",
        readonly=True,
        help="Set when regenerating an existing key.",
    )
    # Stored on the transient record so it survives the client's re-read RPC.
    # The record (and thus the plaintext) is deleted when the wizard is closed.
    new_key = fields.Char(
        string="API key",
        readonly=True,
        help="Full API key. Shown ONCE after creation or regeneration; copy it "
        "now — it is never stored at rest and cannot be recovered later.",
    )

    def action_create_key(self):
        """Create a new ``external.lead.api.key`` and reveal its plaintext once."""
        self.ensure_one()
        new_record = self.env["external.lead.api.key"].create(
            {"name": self.name or _("API key")}
        )
        # ``full_key`` is readable here (same transaction/cache); copy it onto the
        # transient row so the client's re-read can display it.
        self.new_key = new_record.full_key
        self.key_id = new_record.id
        return self._reopen()

    def action_regenerate_key(self):
        """Rotate an existing key and reveal the new plaintext once."""
        self.ensure_one()
        self.key_id.action_regenerate_key()
        self.new_key = self.key_id.full_key
        return self._reopen()

    def _reopen(self):
        """Re-open this wizard record so the freshly set ``new_key`` is shown."""
        return {
            "type": "ir.actions.act_window",
            "name": _("API Key"),
            "res_model": "external.lead.api.key.wizard",
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }
