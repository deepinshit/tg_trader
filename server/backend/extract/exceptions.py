# /backend/extract/exceptions.py
"""
Exception types used by the `extract` package.

Guidelines
----------
- Keep exceptions small, explicit, and serializable.
- When logging these exceptions, attach the related DB model id using the `extra`
  dictionary with the standardized key `LOG_EXTRA_ID_KEY` (value: "model_name_id").

  Example:
      logger.error(
          "Normalization failed",
          exc_info=True,
          extra={LOG_EXTRA_ID_KEY: some_db_model_id},
      )
"""

from __future__ import annotations

from typing import Any, Dict

__all__ = [
    "SignalValidationError",
    "PriceNormalizationError",
    "LOG_EXTRA_ID_KEY",
]

#: Standardized logging key for attaching the related DB model id via `extra`.
#: Example:
#:     logger.warning("...", extra={LOG_EXTRA_ID_KEY: some_id})
LOG_EXTRA_ID_KEY: str = "model_name_id"


class SignalValidationError(Exception):
    """
    Raised when a signal fails domain validation.

    Parameters
    ----------
    field:
        The name or dotted path of the invalid field.
    reason:
        A concise, human-readable explanation of the failure.

    Notes
    -----
    - The string representation includes both `field` and `reason` for clarity
      in logs and client-facing messages.
    - Use `.to_dict()` to serialize details for API responses or structured logs.

    Example
    -------
    >>> raise SignalValidationError(field="price.amount", reason="must be positive")
    Traceback (most recent call last):
        ...
    SignalValidationError: Validation failed for 'price.amount': must be positive
    """

    __slots__ = ("field", "reason")

    def __init__(self, field: str, reason: str) -> None:
        self.field = field
        self.reason = reason
        super().__init__(f"Validation failed for '{field}': {reason}")

    def to_dict(self) -> Dict[str, Any]:
        """
        Return a serializable representation useful for APIs and structured logs.

        Returns
        -------
        dict
            Example:
            {
                "error": "SignalValidationError",
                "field": "price.amount",
                "reason": "must be positive"
            }
        """
        return {
            "error": self.__class__.__name__,
            "field": self.field,
            "reason": self.reason,
        }


class PriceNormalizationError(ValueError):
    """
    Raised when a price value cannot be normalized to a canonical form.

    Typical causes include:
    - Unsupported or ambiguous currency symbols
    - Malformed numeric input
    - Locale/format mismatches

    Example
    -------
    >>> raise PriceNormalizationError("Unsupported currency symbol '₿'")
    Traceback (most recent call last):
        ...
    PriceNormalizationError: Unsupported currency symbol '₿'
    """
    pass
