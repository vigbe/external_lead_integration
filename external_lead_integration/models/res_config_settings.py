# pyright: reportMissingImports=false
# (odoo framework imports resolve only inside the Odoo runtime)
"""Configuration for the External Lead Integration endpoint.

All fields use ``config_parameter=`` so they auto-persist in
``ir.config_parameter`` and can be read by the controller (``auth='public'``,
no user session) without touching ``res.config.settings`` directly.
"""

from odoo import fields, models  # type: ignore[import]


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    external_lead_default_team_id = fields.Many2one(
        comodel_name="crm.team",
        config_parameter="external_lead_integration.default_team_id",
        string="Default Sales Team",
        help="Sales team used when the caller and the API key provide none.",
    )
    external_lead_default_user_id = fields.Many2one(
        comodel_name="res.users",
        config_parameter="external_lead_integration.default_user_id",
        string="Default Salesperson",
        help="Salesperson used when the caller and the API key provide none.",
    )
    external_lead_default_stage_id = fields.Many2one(
        comodel_name="crm.stage",
        config_parameter="external_lead_integration.default_stage_id",
        string="Default Stage",
        help="Stage forced on created leads when set.",
    )
    external_lead_default_source_id = fields.Many2one(
        comodel_name="utm.source",
        config_parameter="external_lead_integration.default_source_id",
        string="Default Source",
        help="UTM source set on created leads when the caller provides none.",
    )
    external_lead_default_campaign_id = fields.Many2one(
        comodel_name="utm.campaign",
        config_parameter="external_lead_integration.default_campaign_id",
        string="Default Campaign",
        help="UTM campaign set on created leads when the caller provides none.",
    )
    external_lead_dedup = fields.Boolean(
        config_parameter="external_lead_integration.dedup",
        string="Deduplicate by email",
        help="If on, when an email matches an existing open lead, return that "
        "lead instead of creating a duplicate.",
    )
    external_lead_require_contact = fields.Boolean(
        default=True,
        config_parameter="external_lead_integration.require_contact",
        string="Require contact info",
        help="Require name and either email or phone when creating a lead.",
    )
    external_lead_cors_allowed_origins = fields.Char(
        config_parameter="external_lead_integration.cors_allowed_origins",
        string="Allowed CORS origins",
        help="Comma-separated list of website origins allowed to call the "
        "endpoint from a browser (e.g. https://www.example.com, "
        "https://example.com). Leave empty to block all cross-origin "
        "requests (same-origin only).",
    )
