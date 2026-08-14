"""Errors raised by the OAP subsystem."""


class ProfileError(ValueError):
    """Base profile error safe to show in CLI output."""


class ProfileValidationError(ProfileError):
    """An OAP document failed schema or semantic validation."""


class ProfileConflictError(ProfileError):
    """A write targeted a stale profile revision or digest."""
