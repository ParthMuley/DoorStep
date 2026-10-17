"""Domain errors. The API maps each to an HTTP status and a contract error code
(docs/interface-contract.md section 3). Business-rule refusals are 409, never 500."""


class DomainError(Exception):
    status_code = 400
    code = "BAD_REQUEST"

    def __init__(self, message: str, *, reasons: list[str] | None = None, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.reasons = reasons or []
        if code:
            self.code = code


class NotFound(DomainError):
    status_code = 404
    code = "NOT_FOUND"


class Unauthorized(DomainError):
    status_code = 403
    code = "UNAUTHORIZED"


class Conflict(DomainError):
    status_code = 409
    code = "CONFLICT"


class SafetyRejection(DomainError):
    """Deterministic safety/eligibility gate refused the action.
    Codes: UNSAFE_ZONE, PROVIDER_NOT_APPROVED, OFFER_NOT_ELIGIBLE, NOT_AUTHORIZED."""

    status_code = 409
    code = "OFFER_NOT_ELIGIBLE"


class ConsentRequired(DomainError):
    status_code = 409
    code = "CONSENT_MISSING"


class InvalidTransition(DomainError):
    status_code = 409
    code = "INVALID_TRANSITION"


class InsufficientEvidence(DomainError):
    status_code = 409
    code = "INSUFFICIENT_EVIDENCE"


def safety_code(reasons: list[str]) -> str:
    if any(r in ("ACTIVE_ORDER_ZONE", "ZONE_UNVERIFIED", "INSIDE_ACTIVE_ORDER_ZONE",
                 "DESTINATION_IN_ACTIVE_ORDER_ZONE") for r in reasons):
        return "UNSAFE_ZONE"
    if "PROVIDER_NOT_APPROVED" in reasons:
        return "PROVIDER_NOT_APPROVED"
    return "OFFER_NOT_ELIGIBLE"
