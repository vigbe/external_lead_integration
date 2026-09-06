# odoo framework: resolves inside the Odoo runtime only
# pyright: reportMissingImports=false
"""External Lead Integration — public REST endpoint.

``POST /api/v1/leads`` creates a ``crm.lead`` from a JSON body authenticated
with an ``X-API-Key`` header. The route runs as ``auth='public'`` (the Odoo
idiomatic mode for public endpoints that write: no login, a proper
read/write cursor) and answers with explicit HTTP status codes + a JSON
body, so it can be consumed directly from any external website.
"""

import json
import logging

from odoo import fields, http
from odoo.exceptions import ValidationError
from odoo.tools import email_normalize

# NOTE: ``base_api`` is a sibling helper module. The host type-checker cannot
# resolve it because ``base_api`` imports ``werkzeug`` (only available inside
# the odoo:19.0 container); the import is correct and resolves at runtime.
from .base_api import _get_api_key_record, _json_error, _json_ok  # type: ignore[import]

_logger = logging.getLogger(__name__)


class _FieldError(Exception):
    """Raised when a request value cannot be cast to its expected type."""

    def __init__(self, field):
        super().__init__(field)
        self.field = field


def _truthy(value):
    """Interpret an ``ir.config_parameter`` value as a boolean."""
    return str(value or "").lower() in ("1", "true", "yes", "t")


def _as_int(value, field_name):
    """Cast a request/config value to int, or ``None`` when empty.

    Raises :class:`_FieldError` (carrying ``field_name``) when a non-empty
    value cannot be interpreted as an integer.
    """
    if value in (None, "", False):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise _FieldError(field_name) from exc


class ExternalLeadApiController(http.Controller):
    @http.route(
        "/api/v1/leads",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def create_lead(self, **kwargs):
        request = http.request

        # 1. Parse the JSON body manually (we need real status codes).
        raw = request.httprequest.get_data()
        try:
            data = json.loads(raw or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return _json_error(400, "invalid_json", "Request body must be valid JSON")
        if not isinstance(data, dict):
            return _json_error(
                400, "invalid_json", "Request body must be a JSON object"
            )

        # 2. Authenticate via the X-API-Key header.
        api_key = _get_api_key_record(request)
        if not api_key:
            return _json_error(
                401, "invalid_api_key", "Missing or invalid X-API-Key header"
            )

        # 3. Read configurable defaults (persisted by res.config.settings).
        icp = request.env["ir.config_parameter"].sudo()
        cfg_team_id = icp.get_param("external_lead_integration.default_team_id")
        cfg_user_id = icp.get_param("external_lead_integration.default_user_id")
        cfg_stage_id = icp.get_param("external_lead_integration.default_stage_id")
        cfg_source_id = icp.get_param("external_lead_integration.default_source_id")
        cfg_campaign_id = icp.get_param("external_lead_integration.default_campaign_id")
        # Lead type: 'opportunity' (pipeline) or 'lead' (pre-pipeline).
        cfg_type = (
            icp.get_param("external_lead_integration.default_lead_type")
            or "opportunity"
        )
        # require_contact defaults to True (required) when the param is unset.
        rc_val = icp.get_param("external_lead_integration.require_contact")
        require_contact = rc_val in (None, "", False) or _truthy(rc_val)
        dedup = _truthy(icp.get_param("external_lead_integration.dedup"))

        contact_name = (data.get("contact_name") or data.get("name") or "").strip()
        email_from = (data.get("email") or "").strip()
        phone = (data.get("phone") or "").strip()
        message = data.get("message") or data.get("description") or ""

        # 5. Validate required contact info BEFORE any DB write.
        if require_contact and not (contact_name and (email_from or phone)):
            return _json_error(
                422,
                "validation",
                "Name and either email or phone are required",
                fields=["name", "email", "phone"],
            )

        today = fields.Date.to_string(fields.Date.today())
        title = (data.get("title") or "").strip() or (
            f"Lead web - {contact_name} - {today}"
            if contact_name
            else f"Lead web - {today}"
        )

        # 4. Build the crm.lead vals (numeric ids are cast defensively).
        lead_fields = request.env["crm.lead"]._fields
        try:
            vals = {
                "name": title,
                "type": data.get("type") or cfg_type,
            }
            if contact_name:
                vals["contact_name"] = contact_name
            if email_from:
                vals["email_from"] = email_from
            if phone:
                vals["phone"] = phone
            if message:
                vals["description"] = message

            # F3: attribution comes ONLY from the API-key override or the
            # config defaults — NEVER from the request body. A caller must
            # not be able to inject arbitrary sales teams, salespeople,
            # sources, campaigns or tags. medium_id/campaign_id/tag_ids had no
            # key/config source, so they are dropped entirely.
            team_id = _as_int(
                api_key.team_id.id if api_key.team_id else cfg_team_id,
                "team_id",
            )
            if team_id:
                vals["team_id"] = team_id

            user_id = _as_int(
                api_key.user_id.id if api_key.user_id else cfg_user_id,
                "user_id",
            )
            if user_id:
                vals["user_id"] = user_id

            source_id = _as_int(
                api_key.source_id.id if api_key.source_id else cfg_source_id,
                "source_id",
            )
            if source_id:
                vals["source_id"] = source_id

            stage_id = _as_int(cfg_stage_id, "stage_id")
            if stage_id:
                vals["stage_id"] = stage_id

            campaign_id = _as_int(
                api_key.campaign_id.id if api_key.campaign_id else cfg_campaign_id,
                "campaign_id",
            )
            if campaign_id:
                vals["campaign_id"] = campaign_id

        except _FieldError as field_error:
            return _json_error(
                422,
                "validation",
                f"Invalid value for field '{field_error.field}'",
                fields=[field_error.field],
            )

        # EXTRA-4: scope lead creation + dedup to the key's company (a key is
        # global — no company filter on the lookup itself). Fall back to the
        # current company when the key carries none.
        key_company = api_key.company_id or request.env.company
        lead_model = request.env["crm.lead"].sudo().with_company(key_company)
        if "company_id" in lead_fields:
            vals["company_id"] = key_company.id

        # 6. Deduplicate by email when enabled (return the existing lead).
        if dedup and email_from:
            normalized = email_normalize(email_from)
            if normalized:
                # EXTRA-3: serialize concurrent same-email requests so the
                # check-then-create is atomic (TOCTOU guard). Parameterized
                # query — no string concatenation of user data.
                request.env.cr.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s))", (normalized,)
                )
                domain = [
                    ("email_normalized", "=", normalized),
                    ("active", "=", True),
                ]
                if "company_id" in lead_fields:
                    domain.append(("company_id", "=", key_company.id))
                existing = lead_model.search(domain, limit=1)
                if existing:
                    return _json_ok(
                        {
                            "lead_id": existing.id,
                            "name": existing.name,
                            "status": "duplicate",
                        },
                        status=200,
                    )

        # 7b. Find or create the res.partner so the lead is linked to a real
        #     contact record (search by email, then phone; create if none).
        partner_model = request.env["res.partner"].sudo()
        partner = False
        if email_from:
            norm = email_normalize(email_from)
            if norm:
                partner = partner_model.search(
                    [("email_normalized", "=", norm)], limit=1
                )
            if not partner:
                partner = partner_model.search(
                    [("email", "=ilike", email_from)], limit=1
                )
        if not partner and phone:
            digits = "".join(ch for ch in (phone or "") if ch.isdigit())
            if len(digits) >= 9:
                partner = partner_model.search(
                    [("phone", "ilike", digits[-9:])], limit=1
                )
        if not partner and (contact_name or email_from or phone):
            partner = partner_model.create(
                {
                    "name": contact_name or email_from or phone or "Contacto Web",
                    "email": email_from,
                    "phone": phone,
                    "customer_rank": 1,
                }
            )
        if partner:
            vals["partner_id"] = partner.id

        # 8. Create the lead.
        try:
            lead = lead_model.create(vals)
        except (ValidationError, ValueError) as exc:
            # Don't leak internal constraint/field details to the caller; log
            # the real exception server-side and return a generic message.
            _logger.warning("create_failed for external lead request: %s", exc)
            return _json_error(422, "create_failed", "Could not create lead")
        except Exception:
            _logger.exception("Unexpected error creating lead via external API")
            return _json_error(500, "internal_error", "Could not create lead")

        # 9. Success.
        _logger.info("Lead created via external api id=%s", lead.id)
        return _json_ok(
            {"lead_id": lead.id, "name": lead.name, "status": "created"},
            status=201,
        )
