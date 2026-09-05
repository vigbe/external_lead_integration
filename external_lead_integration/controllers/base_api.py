"""Shared HTTP helpers for the External Lead Integration API.

Kept import-light on purpose: ``base_api`` depends only on the standard
library, Werkzeug and ``odoo.exceptions`` (used to catch validation errors at
the API boundary), so it can be reused by future endpoints
(e.g. ``/api/v1/contacts``) without pulling model code at import time.
"""

import hashlib
import hmac
import json
import logging

from odoo.exceptions import ValidationError  # type: ignore[import]
from werkzeug.wrappers import Response  # type: ignore[import]

_logger = logging.getLogger(__name__)


def _json_ok(payload, status=200, cors_origin=None):
    """Serialize ``payload`` as a JSON ``Response`` with a real HTTP status.

    ``cors_origin`` (optional, str) echoes the allowed
    ``Access-Control-Allow-Origin`` so a cross-origin website can read this
    JSON response. ``Vary: Origin`` is always set for correct caching.
    """
    headers = {"Vary": "Origin"}
    if cors_origin:
        headers["Access-Control-Allow-Origin"] = cors_origin
    return Response(
        json.dumps(payload),
        status=status,
        content_type="application/json",
        headers=headers,
    )


def _json_error(status, code, message, fields=None, cors_origin=None):
    """Build a uniform JSON error response.

    ``fields`` lists the offending request fields when relevant (e.g. 422).
    ``cors_origin`` (optional) adds a CORS header so the browser can surface the
    error body to the cross-origin caller's JavaScript.
    """
    body = {"error": {"code": code, "message": message}}
    if fields:
        body["error"]["fields"] = list(fields)
    headers = {"Vary": "Origin"}
    if cors_origin:
        headers["Access-Control-Allow-Origin"] = cors_origin
    return Response(
        json.dumps(body),
        status=status,
        content_type="application/json",
        headers=headers,
    )


def _cors_preflight_response(origin):
    """Build the CORS preflight (``OPTIONS``) response for an allowed origin.

    Returns ``204`` with the CORS headers when ``origin`` is allowed, or a bare
    ``403`` (no CORS headers) when it is not, so the browser blocks the real
    cross-origin request. The API key is NOT checked on preflight: the browser
    never sends custom headers with ``OPTIONS``.
    """
    if not origin:
        return Response(status=403)
    return Response(
        status=204,
        headers={
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, X-API-Key",
            "Access-Control-Max-Age": "600",
            "Vary": "Origin",
        },
    )


def _get_api_key_record(request):
    """Resolve the ``X-API-Key`` header to an active API-key record.

    The provided key is hashed with SHA-256 and matched against the stored
    ``key_hash`` first. For backward compatibility, a plaintext ``key`` lookup
    is attempted as a fallback and, when it matches a legacy key, that key is
    migrated to a hash in place (:meth:`_migrate_legacy_key`). A constant-time
    comparison guards the final decision.

    Returns the ``external.lead.api.key`` recordset (with ``last_used_on``
    stamped) or ``None`` when the header is missing or the key is invalid.
    """
    provided = (request.httprequest.headers.get("X-API-Key", "") or "").strip()
    if not provided:
        return None
    computed = hashlib.sha256(provided.encode()).hexdigest()
    ApiKey = request.env["external.lead.api.key"].sudo()
    record = ApiKey.search(
        [("key_hash", "=", computed), ("active", "=", True)], limit=1
    )
    if not record:
        record = ApiKey.search([("key", "=", provided), ("active", "=", True)], limit=1)
        if record:
            try:
                record._migrate_legacy_key()
            except ValidationError:
                # Two legacy keys sharing the same plaintext trip the
                # ``key_hash`` uniqueness constraint during migration. Log it
                # and fail closed (auth denied) so the endpoint never answers
                # with a non-JSON HTML 500. Other exception types propagate.
                _logger.warning(
                    "Legacy API-key migration failed for %r (duplicate hash).",
                    record.name,
                )
                return None
    if record and record.key_hash and hmac.compare_digest(record.key_hash, computed):
        record.log_usage()
        return record
    return None
