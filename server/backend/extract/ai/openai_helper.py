# /backend/extract/ai/openai_helper.py
"""
Helpers for extracting structured data from natural language using OpenAI
Structured Outputs.

Design goals:
- Production-ready and robust: typed, validated inputs, timeouts, retries, and
  precise logging (with optional `model_name_id` via logging `extra`).
- Clean and minimal: no architectural changes; retains the existing async API.
- Flexible yet stable: supports either a Pydantic model *class* or *instance*
  for the schema, without forcing callers to change.

Notes:
- Pass a related DB model id to logs using the `model_name_id` parameter;
  it will be attached to log records via `extra={"model_name_id": ...}`.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Type, TypeVar, Union

import openai  # for exception classes
from openai import OpenAI
from pydantic import BaseModel

from cfg import OPENAI_KEY

logger = logging.getLogger(__name__)

# ---- Configuration (tune as needed, but kept simple) -------------------------

_DEFAULT_MODEL_NAME = "gpt-4o"  # Keep existing model choice; easy to swap centrally.
_MAX_RETRIES = 2                # Total attempts = 1 + _MAX_RETRIES
_BASE_BACKOFF_SECONDS = 0.75    # Exponential backoff base for retryable errors
_CALL_TIMEOUT_SECONDS = 30.0    # Hard cap per attempt (SDK call wrapped via asyncio.wait_for)

# Initialize the OpenAI client once (reuse connections). Fail fast if key missing.
if not OPENAI_KEY:
    # Raising at import makes issues visible early during startup.
    raise RuntimeError("OPENAI_KEY is not configured")

client = OpenAI(api_key=OPENAI_KEY)

# Generic return type bound to Pydantic models
TModel = TypeVar("TModel", bound=BaseModel)


def _resolve_schema_class(scheme_model: Union[Type[TModel], TModel]) -> Type[TModel]:
    """
    Accept either a Pydantic model class or instance and return the class.
    """
    if isinstance(scheme_model, type) and issubclass(scheme_model, BaseModel):
        return scheme_model  # type: ignore[return-value]
    if isinstance(scheme_model, BaseModel):
        return scheme_model.__class__  # type: ignore[return-value]
    raise TypeError(
        "scheme_model must be a Pydantic BaseModel subclass or instance "
        f"(got: {type(scheme_model)!r})"
    )


def _log_extra(model_name_id: Optional[Union[int, str]]) -> Dict[str, Any]:
    """
    Prepare the logging `extra` dict, attaching model_name_id when provided.
    """
    return {"model_name_id": model_name_id} if model_name_id is not None else {}


async def _call_openai_parse(
    *,
    input_prompts: List[Dict[str, str]],
    schema_cls: Type[TModel],
) -> Any:
    """
    Run the (synchronous) OpenAI SDK parse call in a thread and enforce a timeout.
    Returns the raw SDK response object.
    """
    # The `responses.parse` call is synchronous in the SDK; run it in a worker thread.
    return await asyncio.wait_for(
        asyncio.to_thread(
            client.responses.parse,
            model=_DEFAULT_MODEL_NAME,
            input=input_prompts,
            text_format=schema_cls,
        ),
        timeout=_CALL_TIMEOUT_SECONDS,
    )


async def _get_structured_output_from_ai(
    input_prompts: List[Dict[str, str]],
    scheme_model: BaseModel,
    *,
    model_name_id: Optional[Union[int, str]] = None,
) -> Optional[BaseModel]:
    """
    Extract structured data from natural language using OpenAI Structured Outputs.

    Parameters
    ----------
    input_prompts : List[Dict[str, str]]
        A list of message dicts (e.g., [{"role": "user", "content": "..."}, ...]).
        The function does not alter the architecture; it passes these directly to the SDK.
    scheme_model : BaseModel
        Either a Pydantic BaseModel instance or its class that defines the desired schema.
        Both forms are supported; an instance is accepted for backwards-compatibility.
    model_name_id : Optional[Union[int, str]]
        Optional identifier for the related DB model. When provided, it is logged using
        logging `extra={"model_name_id": <id>}` as requested.

    Returns
    -------
    Optional[BaseModel]
        An instance of the provided schema type on success; otherwise `None`.

    Notes
    -----
    - On transient API errors (timeouts/rate limits), the call is retried with exponential backoff.
    - On non-retryable errors or persistent failure, the function logs and returns `None`.
    - This function keeps the original async signature, even though the SDK call is sync.
    """
    extra = _log_extra(model_name_id)

    # Basic, defensive validation (kept light to avoid changing caller behavior)
    if not isinstance(input_prompts, list) or not input_prompts:
        logger.warning(
            "input_prompts should be a non-empty list of message dicts; returning None.",
            extra=extra,
        )
        return None

    try:
        schema_cls: Type[TModel] = _resolve_schema_class(scheme_model)  # type: ignore[type-arg]
    except Exception as e:
        logger.error("Invalid schema model provided: %s", e, extra=extra, exc_info=True)
        return None

    # Retry loop for transient failures
    attempt = 0
    while True:
        attempt += 1
        try:
            response = await _call_openai_parse(
                input_prompts=input_prompts,
                schema_cls=scheme_model,
            )

            # The SDK is expected to return `output_parsed` containing the schema instance.
            output_parsed = getattr(response, "output_parsed", None)

            if output_parsed is None:
                logger.warning(
                    "OpenAI returned no structured output (output_parsed is None).",
                    extra=extra,
                )
                return None

            # If the SDK already returns the correctly-typed object, pass it through.
            if isinstance(output_parsed, schema_cls):
                return output_parsed

            # Best-effort coercion into the schema class without assuming Pydantic v1/v2 specifics.
            try:
                # Pydantic v2
                if hasattr(schema_cls, "model_validate"):
                    return schema_cls.model_validate(output_parsed)  # type: ignore[attr-defined]
                # Pydantic v1
                if hasattr(schema_cls, "parse_obj"):
                    return schema_cls.parse_obj(output_parsed)  # type: ignore[attr-defined]
            except Exception:
                # If coercion fails, fall through to return as-is (maintain behavior simplicity)
                logger.debug(
                    "Could not coerce output to schema; returning parsed output as-is.",
                    extra=extra,
                    exc_info=True,
                )
                return output_parsed  # type: ignore[return-value]

            # If we reach here, just return what we got.
            return output_parsed  # type: ignore[return-value]

        except (
            openai.RateLimitError,
            openai.APITimeoutError,
            openai.APIConnectionError,
            openai.APIError,
            asyncio.TimeoutError,
        ) as e:
            # Retry transient errors with exponential backoff
            if attempt <= _MAX_RETRIES:
                delay = _BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
                logger.warning(
                    "Transient OpenAI error on attempt %s/%s: %s — retrying in %.2fs",
                    attempt,
                    _MAX_RETRIES + 1,
                    e,
                    delay,
                    extra=extra,
                )
                await asyncio.sleep(delay)
                continue
            logger.error(
                "Failed to get structured output after %s attempts due to transient errors.",
                attempt,
                extra=extra,
                exc_info=True,
            )
            return None
        except (
            openai.AuthenticationError,
            openai.BadRequestError,
            openai.NotFoundError,
            ValueError,
            TypeError,
        ) as e:
            # Non-retryable or caller-side errors: log and return None
            logger.error(
                "Non-retryable error while calling OpenAI Structured Outputs: %s",
                e,
                extra=extra,
                exc_info=True,
            )
            return None
        except Exception as e:  # Failsafe catch-all
            logger.error(
                "Unexpected error while parsing structured output: %s",
                e,
                extra=extra,
                exc_info=True,
            )
            return None
