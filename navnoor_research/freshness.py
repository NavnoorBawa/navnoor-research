"""Independent freshness policy for the checked publication datasets."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

MAX_FUTURE_SKEW = timedelta(minutes=10)
MAX_ARCHIVE_AGE = timedelta(hours=36)
MAX_COMPANY_AGE = timedelta(hours=72)
MAX_NEWS_ATTEMPT_AGE = timedelta(hours=12)
PERSISTENT_DEGRADATION_AGE = timedelta(hours=48)


class FreshnessError(ValueError):
    """A checked-data timestamp does not satisfy the operational contract."""


def _instant(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise FreshnessError(f"{label} is missing")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise FreshnessError(f"{label} is not a canonical UTC second") from exc
    return parsed.replace(tzinfo=timezone.utc)


def _checked_timestamp(
    errors: list[str],
    value: Any,
    label: str,
    stale_message: str,
    max_age: timedelta,
    now: datetime,
) -> datetime | None:
    try:
        checked = _instant(value, label)
    except FreshnessError as exc:
        errors.append(str(exc))
        return None
    if checked > now + MAX_FUTURE_SKEW:
        errors.append(f"{label} is implausibly in the future")
    elif now - checked > max_age:
        errors.append(stale_message)
    return checked


def evaluate(
    seed: Any,
    companies: Any,
    news: Any,
    *,
    now: datetime | None = None,
) -> tuple[list[str], list[str]]:
    """Return every hard freshness error and visible degraded-source warning."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise FreshnessError("freshness clock must be timezone-aware")
    current = current.astimezone(timezone.utc)
    errors: list[str] = []
    warnings: list[str] = []

    try:
        archive_value = seed["source_snapshot"]["checked_at"]
    except (KeyError, TypeError):
        archive_value = None
    _checked_timestamp(
        errors,
        archive_value,
        "archive check time",
        "the public research archive has not completed a source check in 36 hours",
        MAX_ARCHIVE_AGE,
        current,
    )

    try:
        company_value = companies["checked_at"]
    except (KeyError, TypeError):
        company_value = None
    _checked_timestamp(
        errors,
        company_value,
        "SEC company check time",
        "the SEC company registry has not completed a refresh in 72 hours",
        MAX_COMPANY_AGE,
        current,
    )

    states = news.get("sources") if isinstance(news, dict) else None
    if not isinstance(states, dict) or not states:
        errors.append("checked headline source state is missing")
        return errors, warnings

    for source_id, state in sorted(states.items()):
        if not isinstance(source_id, str) or not isinstance(state, dict):
            errors.append("checked headline source state is invalid")
            continue
        attempted = _checked_timestamp(
            errors,
            state.get("last_attempt_at"),
            f"{source_id} last attempt",
            f"{source_id} has not been attempted in 12 hours",
            MAX_NEWS_ATTEMPT_AGE,
            current,
        )
        status = state.get("status")
        success_value = state.get("last_success_at")
        success: datetime | None = None
        if success_value is not None:
            try:
                success = _instant(success_value, f"{source_id} last success")
            except FreshnessError as exc:
                errors.append(str(exc))
            else:
                if success > current + MAX_FUTURE_SKEW:
                    errors.append(f"{source_id} last success is implausibly in the future")
                if attempted is not None and success > attempted:
                    errors.append(f"{source_id} last success is later than its last attempt")

        if success is None or status != "ok":
            if success is not None and current - success > PERSISTENT_DEGRADATION_AGE:
                warnings.append(
                    f"{source_id} is {status!r} and has not succeeded in 48 hours; "
                    "the validated last-known-good release remains exact"
                )
            else:
                warnings.append(
                    f"{source_id} is {status!r}; the validated last-known-good "
                    "release remains exact"
                )

    return errors, warnings
