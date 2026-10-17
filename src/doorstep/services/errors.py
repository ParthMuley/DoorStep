"""Domain errors. The API maps each to an HTTP status."""


class DomainError(Exception):
    status_code = 400
    code = "domain_error"

    def __init__(self, message: str, *, reasons: list[str] | None = None):
        super().__init__(message)
        self.message = message
        self.reasons = reasons or []


class NotFound(DomainError):
    status_code = 404
    code = "not_found"


class Unauthorized(DomainError):
    status_code = 403
    code = "unauthorized"


class Conflict(DomainError):
    """State conflict, e.g. a late reply to a canceled assignment."""

    status_code = 409
    code = "conflict"


class SafetyRejection(DomainError):
    """Deterministic safety gate refused the action (e.g. active-order zone)."""

    status_code = 422
    code = "safety_rejection"


class ConsentRequired(DomainError):
    status_code = 422
    code = "consent_required"


class InvalidTransition(DomainError):
    status_code = 409
    code = "invalid_transition"


class InsufficientEvidence(DomainError):
    status_code = 422
    code = "insufficient_evidence"
