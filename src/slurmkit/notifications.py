"""
Notification utilities for job lifecycle events.

This module provides:
- Notification route parsing from configuration
- Job context lookup from collection metadata
- Collection-final report generation and deduplication
- Canonical payload generation for webhook notifications
- Slack/Discord adapters with human-readable summaries
- HTTP delivery with bounded retries
"""

from __future__ import annotations

import copy
import fcntl
import hashlib
import importlib
import json
import os
import re
import smtplib
import socket
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from slurmkit.collections import (
    Collection,
    CollectionManager,
    JOB_STATE_COMPLETED,
    JOB_STATE_FAILED,
    JOB_STATE_PENDING,
    JOB_STATE_RUNNING,
    JOB_STATE_UNKNOWN,
)
from slurmkit.config import Config, get_config
from slurmkit.slurm import find_job_output

try:
    import requests
except ImportError:  # pragma: no cover - guarded by packaging dependency
    requests = None


ROUTE_TYPES = {"webhook", "slack", "discord", "email"}
DEFAULT_EVENT_FAILED = "job_failed"
EVENT_JOB_COMPLETED = "job_completed"
EVENT_JOB_FAILED = "job_failed"
EVENT_COLLECTION_COMPLETED = "collection_completed"
EVENT_COLLECTION_FAILED = "collection_failed"
EVENT_TEST = "test_notification"
SCHEMA_VERSION = "v1"

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class NotificationConfigError(ValueError):
    """Raised when notification configuration is invalid."""


@dataclass
class NotificationDefaults:
    """Default values used by notification routes."""

    events: List[str]
    timeout_seconds: float
    max_attempts: int
    backoff_seconds: float
    output_tail_lines: int


@dataclass
class NotificationRoute:
    """Normalized notification route definition."""

    name: str
    route_type: str
    url: str
    enabled: bool
    events: List[str]
    headers: Dict[str, str]
    timeout_seconds: float
    max_attempts: int
    backoff_seconds: float
    email_to: List[str] = field(default_factory=list)
    email_from: Optional[str] = None
    smtp_host: Optional[str] = None
    smtp_port: int = 587
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_starttls: bool = True
    smtp_ssl: bool = False


@dataclass
class RouteResolution:
    """Result of route selection for an event."""

    routes: List[NotificationRoute]
    errors: List[str]
    skipped: List[str]


@dataclass
class DeliveryResult:
    """Delivery status for a single route attempt."""

    route_name: str
    route_type: str
    success: bool
    attempts: int
    status_code: Optional[int] = None
    error: Optional[str] = None
    dry_run: bool = False


@dataclass
class CollectionResolution:
    """Resolution result for finding a collection from a job ID."""

    collection: Optional[Collection]
    context_source: str
    warnings: List[str]


@dataclass
class CollectionFinality:
    """Computed collection finality for latest/primary attempt semantics."""

    terminal: bool
    event: Optional[str]
    counts: Dict[str, int]
    effective_rows: List[Dict[str, Any]]


@dataclass
class CollectionFinalConfig:
    """Config settings for collection-final reporting."""

    attempt_mode: str
    min_support: int
    top_k: int
    include_failed_output_tail_lines: int



def _now_iso() -> str:
    """Return current timestamp in ISO format."""
    return datetime.now().isoformat(timespec="seconds")



def _normalize_events(value: Any, fallback: Optional[List[str]] = None) -> List[str]:
    """Normalize event configuration values."""
    if fallback is None:
        fallback = [DEFAULT_EVENT_FAILED]

    if value is None:
        events = list(fallback)
    elif isinstance(value, str):
        events = [value]
    elif isinstance(value, list):
        events = [str(x) for x in value if str(x).strip()]
    else:
        events = list(fallback)

    deduped = []
    seen = set()
    for event in events:
        if event in seen:
            continue
        seen.add(event)
        deduped.append(event)

    return deduped or list(fallback)



def _to_positive_float(value: Any, default: float) -> float:
    """Convert value to positive float with default fallback."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default



def _to_non_negative_float(value: Any, default: float) -> float:
    """Convert value to non-negative float with default fallback."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default



def _to_positive_int(value: Any, default: int) -> int:
    """Convert value to positive int with default fallback."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _to_bool(value: Any, default: bool) -> bool:
    """Convert common scalar values to bool with default fallback."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    return default



def _interpolate_env_string(value: str) -> str:
    """Resolve ${VAR} placeholders from environment variables."""

    def replace(match: re.Match) -> str:
        var_name = match.group(1)
        var_value = os.environ.get(var_name)
        if var_value is None:
            raise NotificationConfigError(
                f"Missing environment variable '{var_name}' required by notification config."
            )
        return var_value

    return _ENV_PATTERN.sub(replace, value)



def _interpolate_env(value: Any) -> Any:
    """Recursively resolve ${VAR} placeholders for strings/dicts/lists."""
    if isinstance(value, str):
        return _interpolate_env_string(value)
    if isinstance(value, list):
        return [_interpolate_env(item) for item in value]
    if isinstance(value, dict):
        resolved: Dict[str, Any] = {}
        for key, item in value.items():
            resolved[str(key)] = _interpolate_env(item)
        return resolved
    return value



def _read_output_tail(path: Path, lines: int) -> Optional[str]:
    """Read the trailing lines from an output file."""
    if not path.exists():
        return None

    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None

    if lines <= 0:
        return None
    return "\n".join(content[-lines:]) if content else ""



def _match_collection_job(
    collection: Collection,
    job_id: str,
) -> Optional[Tuple[Dict[str, Any], Optional[Dict[str, Any]]]]:
    """Find a primary or resubmission job record by job ID."""
    for job in collection.jobs:
        if job.get("job_id") == job_id:
            return job, None

        for resubmission in job.get("resubmissions", []):
            if resubmission.get("job_id") == job_id:
                return job, resubmission

    return None



def _normalize_slurm_state(state: Optional[str]) -> str:
    """Normalize raw SLURM state into toolkit-level categories."""
    if state is None:
        return JOB_STATE_UNKNOWN

    state_upper = str(state).upper()
    if state_upper in ("PENDING", "REQUEUED", "SUSPENDED"):
        return JOB_STATE_PENDING
    if state_upper in ("RUNNING", "COMPLETING"):
        return JOB_STATE_RUNNING
    if state_upper == "COMPLETED":
        return JOB_STATE_COMPLETED
    if state_upper in (
        "FAILED",
        "CANCELLED",
        "TIMEOUT",
        "NODE_FAIL",
        "PREEMPTED",
        "OUT_OF_MEMORY",
    ):
        return JOB_STATE_FAILED
    return JOB_STATE_UNKNOWN



def _collection_final_meta(collection: Collection) -> Dict[str, Any]:
    """Get mutable metadata namespace for collection-final notifications."""
    if not isinstance(collection.meta, dict):
        collection.meta = {}

    notifications_meta = collection.meta.get("notifications")
    if not isinstance(notifications_meta, dict):
        notifications_meta = {}
        collection.meta["notifications"] = notifications_meta

    final_meta = notifications_meta.get("collection_final")
    if not isinstance(final_meta, dict):
        final_meta = {}
        notifications_meta["collection_final"] = final_meta

    return final_meta


class NotificationService:
    """Service for building and delivering notifications."""

    def __init__(
        self,
        config: Optional[Config] = None,
        collection_manager: Optional[CollectionManager] = None,
    ):
        if config is None:
            config = get_config()
        self.config = config
        self.collection_manager = collection_manager or CollectionManager(config=config)

    def get_defaults(self) -> NotificationDefaults:
        """Get normalized notification defaults from config."""
        defaults_raw = self.config.get("notifications.defaults", {}) or {}
        events = _normalize_events(defaults_raw.get("events"), fallback=[DEFAULT_EVENT_FAILED])

        return NotificationDefaults(
            events=events,
            timeout_seconds=_to_positive_float(defaults_raw.get("timeout_seconds"), 5.0),
            max_attempts=_to_positive_int(defaults_raw.get("max_attempts"), 3),
            backoff_seconds=_to_non_negative_float(defaults_raw.get("backoff_seconds"), 0.5),
            output_tail_lines=_to_positive_int(defaults_raw.get("output_tail_lines"), 40),
        )

    def get_collection_final_config(self) -> CollectionFinalConfig:
        """Get normalized configuration for collection-final reporting."""
        raw = self.config.get("notifications.collection_final", {}) or {}
        attempt_mode = str(raw.get("attempt_mode", "latest")).strip().lower()
        if attempt_mode not in ("primary", "latest"):
            attempt_mode = "latest"

        return CollectionFinalConfig(
            attempt_mode=attempt_mode,
            min_support=_to_positive_int(raw.get("min_support"), 3),
            top_k=_to_positive_int(raw.get("top_k"), 10),
            include_failed_output_tail_lines=_to_positive_int(
                raw.get("include_failed_output_tail_lines"),
                20,
            ),
        )

    def _parse_route(self, raw_route: Dict[str, Any], defaults: NotificationDefaults) -> NotificationRoute:
        """Validate and normalize a single notification route."""
        name = str(raw_route.get("name", "")).strip()
        if not name:
            raise NotificationConfigError("Route is missing required field 'name'.")

        route_type = str(raw_route.get("type", "webhook")).strip().lower()
        if route_type not in ROUTE_TYPES:
            raise NotificationConfigError(
                f"Route '{name}' has unsupported type '{route_type}'. "
                f"Supported: {', '.join(sorted(ROUTE_TYPES))}."
            )

        enabled = bool(raw_route.get("enabled", True))

        email_to: List[str] = []
        email_from: Optional[str] = None
        smtp_host: Optional[str] = None
        smtp_port = 587
        smtp_username: Optional[str] = None
        smtp_password: Optional[str] = None
        smtp_starttls = True
        smtp_ssl = False

        if route_type == "email":
            if "url" in raw_route:
                raise NotificationConfigError(
                    f"Route '{name}' of type 'email' must not define field 'url'."
                )
            if "headers" in raw_route:
                raise NotificationConfigError(
                    f"Route '{name}' of type 'email' must not define field 'headers'."
                )

            raw_to = raw_route.get("to")
            if raw_to is None:
                raise NotificationConfigError(
                    f"Route '{name}' of type 'email' is missing required field 'to'."
                )
            resolved_to = _interpolate_env(raw_to)
            candidates: List[str] = []
            if isinstance(resolved_to, str):
                candidates = [part.strip() for part in resolved_to.split(",") if part.strip()]
            elif isinstance(resolved_to, list):
                for entry in resolved_to:
                    for part in str(entry).split(","):
                        trimmed = part.strip()
                        if trimmed:
                            candidates.append(trimmed)
            else:
                raise NotificationConfigError(
                    f"Route '{name}' field 'to' must be a string or list of strings."
                )
            seen_to: set = set()
            email_to = []
            for recipient in candidates:
                if recipient in seen_to:
                    continue
                seen_to.add(recipient)
                email_to.append(recipient)
            if not email_to:
                raise NotificationConfigError(
                    f"Route '{name}' field 'to' must contain at least one recipient."
                )

            raw_from = raw_route.get("from")
            if raw_from is None or str(raw_from).strip() == "":
                raise NotificationConfigError(
                    f"Route '{name}' of type 'email' is missing required field 'from'."
                )
            email_from = str(_interpolate_env(raw_from)).strip()
            if not email_from:
                raise NotificationConfigError(
                    f"Route '{name}' field 'from' resolved to an empty value."
                )

            raw_smtp_host = raw_route.get("smtp_host")
            if raw_smtp_host is None or str(raw_smtp_host).strip() == "":
                raise NotificationConfigError(
                    f"Route '{name}' of type 'email' is missing required field 'smtp_host'."
                )
            smtp_host = str(_interpolate_env(raw_smtp_host)).strip()
            if not smtp_host:
                raise NotificationConfigError(
                    f"Route '{name}' field 'smtp_host' resolved to an empty value."
                )

            smtp_port = _to_positive_int(
                _interpolate_env(raw_route.get("smtp_port", 587)),
                587,
            )
            smtp_starttls = _to_bool(
                _interpolate_env(raw_route.get("smtp_starttls", True)),
                True,
            )
            smtp_ssl = _to_bool(
                _interpolate_env(raw_route.get("smtp_ssl", False)),
                False,
            )
            if smtp_starttls and smtp_ssl:
                raise NotificationConfigError(
                    f"Route '{name}' cannot enable both smtp_starttls and smtp_ssl."
                )

            raw_username = raw_route.get("smtp_username")
            raw_password = raw_route.get("smtp_password")
            if raw_username is not None and str(raw_username).strip() != "":
                smtp_username = str(_interpolate_env(raw_username)).strip()
            if raw_password is not None and str(raw_password).strip() != "":
                smtp_password = str(_interpolate_env(raw_password)).strip()
            if bool(smtp_username) != bool(smtp_password):
                raise NotificationConfigError(
                    f"Route '{name}' must set both smtp_username and smtp_password together."
                )

            url = ""
            normalized_headers: Dict[str, str] = {}
        else:
            raw_url = raw_route.get("url")
            if raw_url is None or str(raw_url).strip() == "":
                raise NotificationConfigError(f"Route '{name}' is missing required field 'url'.")
            url = str(_interpolate_env(raw_url))

            raw_headers = raw_route.get("headers", {}) or {}
            if not isinstance(raw_headers, dict):
                raise NotificationConfigError(f"Route '{name}' field 'headers' must be a mapping.")
            headers = _interpolate_env(raw_headers)
            normalized_headers = {str(k): str(v) for k, v in headers.items()}

        events = _normalize_events(raw_route.get("events"), fallback=defaults.events)

        timeout_seconds = _to_positive_float(raw_route.get("timeout_seconds"), defaults.timeout_seconds)
        max_attempts = _to_positive_int(raw_route.get("max_attempts"), defaults.max_attempts)
        backoff_seconds = _to_non_negative_float(raw_route.get("backoff_seconds"), defaults.backoff_seconds)

        return NotificationRoute(
            name=name,
            route_type=route_type,
            url=url,
            enabled=enabled,
            events=events,
            headers=normalized_headers,
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
            backoff_seconds=backoff_seconds,
            email_to=email_to,
            email_from=email_from,
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_username=smtp_username,
            smtp_password=smtp_password,
            smtp_starttls=smtp_starttls,
            smtp_ssl=smtp_ssl,
        )

    def resolve_routes(
        self,
        event: Optional[str],
        route_names: Optional[List[str]] = None,
    ) -> RouteResolution:
        """
        Resolve routes by event and optional route-name filtering.

        Args:
            event: Event name for filtering. If None, no event filtering is applied.
            route_names: Optional allow-list of route names.

        Returns:
            RouteResolution with routes, parsing errors, and skipped route names.
        """
        defaults = self.get_defaults()
        raw_routes = self.config.get("notifications.routes", []) or []
        if not isinstance(raw_routes, list):
            return RouteResolution(
                routes=[],
                errors=["Configuration key 'notifications.routes' must be a list."],
                skipped=[],
            )

        selected = set(route_names or [])
        known_names: set = set()
        routes: List[NotificationRoute] = []
        errors: List[str] = []
        skipped: List[str] = []

        for idx, raw in enumerate(raw_routes):
            if not isinstance(raw, dict):
                if not selected:
                    errors.append(f"Route entry at index {idx} must be a mapping.")
                continue

            raw_name = str(raw.get("name", "")).strip()
            if raw_name:
                known_names.add(raw_name)

            # When an explicit route allow-list is provided, only validate selected
            # routes so unrelated routes do not block targeted sends/tests.
            if selected and raw_name not in selected:
                if raw_name:
                    skipped.append(raw_name)
                continue

            try:
                route = self._parse_route(raw, defaults)
            except NotificationConfigError as exc:
                errors.append(str(exc))
                continue

            known_names.add(route.name)

            if selected and route.name not in selected:
                skipped.append(route.name)
                continue
            if not route.enabled:
                skipped.append(route.name)
                continue
            if event is not None and event not in route.events:
                skipped.append(route.name)
                continue

            routes.append(route)

        if selected:
            unknown = sorted(selected - known_names)
            for name in unknown:
                errors.append(f"Unknown notification route '{name}'.")

        return RouteResolution(routes=routes, errors=errors, skipped=skipped)

    def resolve_collection_for_job(
        self,
        job_id: str,
        collection_name: Optional[str] = None,
    ) -> CollectionResolution:
        """Resolve a collection by explicit name or job-id lookup across collections."""
        warnings: List[str] = []

        if collection_name:
            if not self.collection_manager.exists(collection_name):
                return CollectionResolution(
                    collection=None,
                    context_source="env_only",
                    warnings=[f"Collection '{collection_name}' was not found."],
                )
            try:
                return CollectionResolution(
                    collection=self.collection_manager.load(collection_name),
                    context_source="collection_match",
                    warnings=[],
                )
            except Exception as exc:
                return CollectionResolution(
                    collection=None,
                    context_source="env_only",
                    warnings=[f"Failed to load collection '{collection_name}': {exc}"],
                )

        matches: List[Collection] = []
        for name in self.collection_manager.list_collections():
            try:
                collection = self.collection_manager.load(name)
            except Exception as exc:
                warnings.append(f"Failed to load collection '{name}': {exc}")
                continue

            if _match_collection_job(collection, job_id) is not None:
                matches.append(collection)

        if len(matches) == 1:
            return CollectionResolution(
                collection=matches[0],
                context_source="collection_match",
                warnings=warnings,
            )

        if len(matches) > 1:
            match_names = sorted(c.name for c in matches)
            warnings.append(
                f"Job ID '{job_id}' matched multiple collections ({', '.join(match_names)}). "
                "Pass --collection to disambiguate."
            )
            return CollectionResolution(
                collection=None,
                context_source="ambiguous_match",
                warnings=warnings,
            )

        warnings.append(f"No collection found for job ID '{job_id}'.")
        return CollectionResolution(collection=None, context_source="env_only", warnings=warnings)

    def _resolve_job_context(
        self,
        job_id: str,
        event: str,
        collection_name: Optional[str] = None,
        tail_lines: Optional[int] = None,
    ) -> Tuple[Dict[str, Any], List[str]]:
        """Resolve job and collection metadata for notifications."""
        warnings: List[str] = []
        defaults = self.get_defaults()
        tail_n = tail_lines if tail_lines is not None else defaults.output_tail_lines

        job_name_env = os.environ.get("SLURM_JOB_NAME")
        context_source = "env_only"
        collection_payload = None

        matches: List[Tuple[Collection, Dict[str, Any], Optional[Dict[str, Any]]]] = []
        collection_names: List[str]

        if collection_name:
            if not self.collection_manager.exists(collection_name):
                warnings.append(f"Collection '{collection_name}' was not found; using env-only context.")
                collection_names = []
            else:
                collection_names = [collection_name]
        else:
            collection_names = self.collection_manager.list_collections()

        for name in collection_names:
            try:
                collection = self.collection_manager.load(name)
            except Exception as exc:
                warnings.append(f"Failed to load collection '{name}': {exc}")
                continue

            matched = _match_collection_job(collection, job_id)
            if matched is None:
                continue
            job_entry, resubmission = matched
            matches.append((collection, job_entry, resubmission))

        selected_job: Optional[Dict[str, Any]] = None
        selected_resub: Optional[Dict[str, Any]] = None

        if len(matches) == 1:
            context_source = "collection_match"
            selected_collection, selected_job, selected_resub = matches[0]
            collection_payload = {
                "name": selected_collection.name,
                "description": selected_collection.description,
                "parameters": selected_collection.parameters,
            }
        elif len(matches) > 1:
            context_source = "ambiguous_match"
            match_names = sorted({m[0].name for m in matches})
            warnings.append(
                "Job ID matched multiple collections "
                f"({', '.join(match_names)}); using env-only context."
            )

        derived_state = "FAILED" if event == EVENT_JOB_FAILED else "COMPLETED"
        job_payload: Dict[str, Any] = {
            "job_id": job_id,
            "job_name": job_name_env,
            "exit_code": None,
            "state": derived_state,
            "submitted_at": None,
            "started_at": None,
            "completed_at": None,
            "output_path": None,
            "output_tail": None,
        }

        if selected_job is not None:
            state = selected_job.get("state")
            if selected_resub is not None:
                state = selected_resub.get("state", state)

            output_path = selected_job.get("output_path")
            output_path_obj: Optional[Path] = None

            if output_path:
                candidate = Path(str(output_path))
                if candidate.exists():
                    output_path_obj = candidate

            if output_path_obj is None:
                jobs_dir = self.config.get_path("jobs_dir")
                if jobs_dir is not None and jobs_dir.exists():
                    matches_output = find_job_output(job_id, jobs_dir, self.config)
                    if matches_output:
                        output_path_obj = matches_output[0]

            job_payload.update(
                {
                    "job_name": selected_job.get("job_name") or job_name_env,
                    "state": state or derived_state,
                    "submitted_at": selected_resub.get("submitted_at") if selected_resub else selected_job.get("submitted_at"),
                    "started_at": selected_job.get("started_at"),
                    "completed_at": selected_job.get("completed_at"),
                    "output_path": str(output_path_obj) if output_path_obj else None,
                }
            )

            if event == EVENT_JOB_FAILED and output_path_obj is not None:
                job_payload["output_tail"] = _read_output_tail(output_path_obj, tail_n)

        return {
            "context_source": context_source,
            "collection": collection_payload,
            "job": job_payload,
        }, warnings

    def _effective_row_for_job(
        self,
        job: Dict[str, Any],
        attempt_mode: str,
    ) -> Dict[str, Any]:
        """Compute effective job row for primary/latest attempt semantics."""
        raw_state = job.get("state")
        effective_job_id = job.get("job_id")

        if attempt_mode == "latest":
            resubmissions = job.get("resubmissions", [])
            if resubmissions:
                latest = resubmissions[-1]
                effective_job_id = latest.get("job_id") or effective_job_id
                latest_state = latest.get("state")
                if latest_state is not None:
                    raw_state = latest_state

        return {
            "job_name": job.get("job_name"),
            "job_id": effective_job_id,
            "state": _normalize_slurm_state(raw_state),
            "raw_state": raw_state,
            "parameters": job.get("parameters", {}) or {},
            "output_path": job.get("output_path"),
            "primary_job_id": job.get("job_id"),
            "resubmission_count": len(job.get("resubmissions", [])),
        }

    def evaluate_collection_finality(
        self,
        collection: Collection,
        attempt_mode: str = "latest",
    ) -> CollectionFinality:
        """Evaluate terminal status and event type for a collection."""
        if attempt_mode not in ("primary", "latest"):
            raise ValueError("attempt_mode must be 'primary' or 'latest'")

        rows = [self._effective_row_for_job(job, attempt_mode=attempt_mode) for job in collection.jobs]

        counts = {
            "total": len(rows),
            JOB_STATE_PENDING: 0,
            JOB_STATE_RUNNING: 0,
            JOB_STATE_COMPLETED: 0,
            JOB_STATE_FAILED: 0,
            JOB_STATE_UNKNOWN: 0,
        }
        for row in rows:
            state = row["state"]
            counts[state] = counts.get(state, 0) + 1

        terminal = (counts[JOB_STATE_PENDING] + counts[JOB_STATE_RUNNING]) == 0

        event: Optional[str] = None
        if terminal:
            has_fail_like = (counts[JOB_STATE_FAILED] + counts[JOB_STATE_UNKNOWN]) > 0
            event = EVENT_COLLECTION_FAILED if has_fail_like else EVENT_COLLECTION_COMPLETED

        return CollectionFinality(
            terminal=terminal,
            event=event,
            counts=counts,
            effective_rows=rows,
        )

    def _recommendations_from_finality(self, finality: CollectionFinality, collection_name: str) -> List[str]:
        """Build concise deterministic recommendations."""
        recommendations: List[str] = []
        if not finality.terminal:
            recommendations.append("Collection is not terminal yet; wait for running/pending jobs to finish.")
            return recommendations

        fail_like = finality.counts[JOB_STATE_FAILED] + finality.counts[JOB_STATE_UNKNOWN]
        if fail_like > 0:
            recommendations.append(
                f"Review failed/unknown jobs and consider: slurmkit resubmit --collection {collection_name} --filter failed"
            )
            recommendations.append(
                "Run detailed parameter analysis locally: slurmkit collection analyze "
                f"{collection_name} --attempt-mode latest"
            )
        else:
            recommendations.append("All jobs completed successfully.")
            recommendations.append(
                "Review top stable parameter values from the report before launching the next sweep."
            )

        return recommendations

    def build_collection_report(
        self,
        collection: Collection,
        trigger_job_id: str,
        attempt_mode: Optional[str] = None,
        min_support: Optional[int] = None,
        top_k: Optional[int] = None,
        failed_tail_lines: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Build deterministic structured report for collection-final notifications."""
        cfg = self.get_collection_final_config()
        effective_attempt_mode = attempt_mode or cfg.attempt_mode
        effective_min_support = min_support if min_support is not None else cfg.min_support
        effective_top_k = top_k if top_k is not None else cfg.top_k
        tail_lines = (
            failed_tail_lines
            if failed_tail_lines is not None
            else cfg.include_failed_output_tail_lines
        )

        finality = self.evaluate_collection_finality(
            collection,
            attempt_mode=effective_attempt_mode,
        )

        analysis = collection.analyze_status_by_params(
            attempt_mode=effective_attempt_mode,
            min_support=effective_min_support,
            top_k=effective_top_k,
        )

        failed_rows = [
            row for row in finality.effective_rows if row["state"] in (JOB_STATE_FAILED, JOB_STATE_UNKNOWN)
        ]

        failed_jobs: List[Dict[str, Any]] = []
        for row in failed_rows:
            output_tail = None
            output_path = row.get("output_path")
            if output_path and tail_lines > 0:
                output_tail = _read_output_tail(Path(str(output_path)), tail_lines)

            failed_jobs.append(
                {
                    "job_name": row.get("job_name"),
                    "job_id": row.get("job_id"),
                    "state": row.get("state"),
                    "exit_code": None,
                    "output_path": output_path,
                    "output_tail": output_tail,
                }
            )

        recommendations = self._recommendations_from_finality(finality, collection.name)

        report = {
            "collection_name": collection.name,
            "generated_at": _now_iso(),
            "trigger_job_id": trigger_job_id,
            "attempt_mode": effective_attempt_mode,
            "summary": {
                "total_jobs": finality.counts["total"],
                "counts": {
                    "completed": finality.counts[JOB_STATE_COMPLETED],
                    "failed": finality.counts[JOB_STATE_FAILED],
                    "unknown": finality.counts[JOB_STATE_UNKNOWN],
                    "running": finality.counts[JOB_STATE_RUNNING],
                    "pending": finality.counts[JOB_STATE_PENDING],
                },
                "terminal": finality.terminal,
            },
            "failed_jobs": failed_jobs,
            "top_risky_values": analysis.get("top_risky_values", []),
            "top_stable_values": analysis.get("top_stable_values", []),
            "analysis_metadata": analysis.get("metadata", {}),
            "recommendations": recommendations,
            "effective_rows": finality.effective_rows,
        }
        return report

    def _ai_callback_config(self) -> Dict[str, Any]:
        """Get normalized AI callback configuration for collection-final reports."""
        raw = self.config.get("notifications.collection_final.ai", {}) or {}
        return {
            "enabled": bool(raw.get("enabled", False)),
            "callback": raw.get("callback"),
        }

    def _load_callback(self, callback_path: str) -> Callable[[Dict[str, Any]], Any]:
        """Load python callback from module:function path."""
        if ":" not in callback_path:
            raise NotificationConfigError(
                "AI callback must use 'module.path:function_name' format."
            )

        module_name, func_name = callback_path.split(":", 1)
        if not module_name.strip() or not func_name.strip():
            raise NotificationConfigError(
                "AI callback must use 'module.path:function_name' format."
            )

        module = importlib.import_module(module_name.strip())
        if not hasattr(module, func_name.strip()):
            raise NotificationConfigError(
                f"AI callback '{func_name.strip()}' not found in module '{module_name.strip()}'."
            )

        callback = getattr(module, func_name.strip())
        if not callable(callback):
            raise NotificationConfigError(
                f"AI callback '{callback_path}' is not callable."
            )

        return callback

    def run_collection_ai_callback(
        self,
        report: Dict[str, Any],
    ) -> Tuple[Optional[str], str, Optional[str]]:
        """
        Execute optional AI callback.

        Returns:
            (ai_summary_markdown, ai_status, warning_message)
        """
        ai_cfg = self._ai_callback_config()
        if not ai_cfg["enabled"]:
            return None, "disabled", None

        callback_path = ai_cfg.get("callback")
        if callback_path is None or str(callback_path).strip() == "":
            return None, "unavailable", "AI callback is enabled but callback path is empty."

        try:
            callback = self._load_callback(str(callback_path))
            output = callback(copy.deepcopy(report))
        except Exception as exc:
            return None, "unavailable", f"AI callback failed: {exc}"

        if isinstance(output, dict):
            summary = "```json\n" + json.dumps(output, indent=2, default=str) + "\n```"
        elif isinstance(output, str):
            summary = output.strip()
        else:
            summary = str(output).strip()

        if not summary:
            return None, "unavailable", "AI callback returned empty output."

        return summary, "available", None

    def compute_collection_final_fingerprint(
        self,
        collection_name: str,
        event: str,
        effective_rows: List[Dict[str, Any]],
    ) -> str:
        """Compute stable fingerprint for deduplicating collection-final sends."""
        snapshot = [
            {
                "job_name": row.get("job_name"),
                "job_id": row.get("job_id"),
                "state": row.get("state"),
            }
            for row in effective_rows
        ]
        snapshot.sort(key=lambda item: (str(item.get("job_name")), str(item.get("job_id"))))

        payload = {
            "collection": collection_name,
            "event": event,
            "snapshot": snapshot,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def should_skip_collection_final(
        self,
        collection: Collection,
        event: str,
        fingerprint: str,
    ) -> bool:
        """Check persisted dedup marker in collection metadata."""
        final_meta = _collection_final_meta(collection)
        return (
            final_meta.get("last_event") == event
            and final_meta.get("last_fingerprint") == fingerprint
        )

    def mark_collection_final_sent(
        self,
        collection: Collection,
        event: str,
        fingerprint: str,
        trigger_job_id: str,
    ) -> None:
        """Persist dedup marker in collection metadata."""
        final_meta = _collection_final_meta(collection)
        final_meta["last_event"] = event
        final_meta["last_fingerprint"] = fingerprint
        final_meta["sent_at"] = _now_iso()
        final_meta["trigger_job_id"] = trigger_job_id
        collection._touch()

    @contextmanager
    def collection_lock(
        self,
        collection_name: str,
        timeout_seconds: float = 10.0,
    ) -> Iterator[None]:
        """Acquire an exclusive lock for collection-final notification workflow."""
        collection_path = self.collection_manager._get_path(collection_name)
        collection_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = collection_path.with_suffix(collection_path.suffix + ".lock")

        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
        start = time.time()
        try:
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if (time.time() - start) >= timeout_seconds:
                        raise TimeoutError(
                            f"Timed out waiting for collection lock: {lock_path}"
                        )
                    time.sleep(0.05)

            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def build_job_payload(
        self,
        job_id: str,
        exit_code: int,
        event: str,
        collection_name: Optional[str] = None,
        tail_lines: Optional[int] = None,
    ) -> Tuple[Dict[str, Any], List[str]]:
        """Build canonical payload for a job lifecycle event."""
        context, warnings = self._resolve_job_context(
            job_id=job_id,
            event=event,
            collection_name=collection_name,
            tail_lines=tail_lines,
        )

        payload = {
            "schema_version": SCHEMA_VERSION,
            "event": event,
            "generated_at": _now_iso(),
            "context_source": context["context_source"],
            "job": context["job"],
            "collection": context["collection"],
            "host": {
                "hostname": socket.gethostname(),
            },
            "meta": {
                "route_name": None,
                "route_type": None,
            },
        }
        payload["job"]["exit_code"] = int(exit_code)
        return payload, warnings

    def build_collection_final_payload(
        self,
        collection: Collection,
        event: str,
        trigger_job_id: str,
        report: Dict[str, Any],
        ai_status: str,
        ai_summary: Optional[str],
    ) -> Dict[str, Any]:
        """Build canonical payload for collection-final events."""
        payload = {
            "schema_version": SCHEMA_VERSION,
            "event": event,
            "generated_at": _now_iso(),
            "context_source": "collection_match",
            "job": {
                "job_id": trigger_job_id,
                "job_name": os.environ.get("SLURM_JOB_NAME"),
                "exit_code": None,
                "state": None,
                "submitted_at": None,
                "started_at": None,
                "completed_at": None,
                "output_path": None,
                "output_tail": None,
            },
            "collection": {
                "name": collection.name,
                "description": collection.description,
                "parameters": collection.parameters,
            },
            "collection_report": report,
            "trigger_job_id": trigger_job_id,
            "ai_status": ai_status,
            "ai_summary": ai_summary,
            "host": {
                "hostname": socket.gethostname(),
            },
            "meta": {
                "route_name": None,
                "route_type": None,
            },
        }
        return payload

    def build_test_payload(self) -> Dict[str, Any]:
        """Build synthetic payload for notification route testing."""
        return {
            "schema_version": SCHEMA_VERSION,
            "event": EVENT_TEST,
            "generated_at": _now_iso(),
            "context_source": "env_only",
            "job": {
                "job_id": os.environ.get("SLURM_JOB_ID"),
                "job_name": os.environ.get("SLURM_JOB_NAME"),
                "exit_code": None,
                "state": None,
                "submitted_at": None,
                "started_at": None,
                "completed_at": None,
                "output_path": None,
                "output_tail": None,
            },
            "collection": None,
            "host": {
                "hostname": socket.gethostname(),
            },
            "meta": {
                "route_name": None,
                "route_type": None,
            },
        }

    def _render_human_message(self, payload: Dict[str, Any]) -> str:
        """Render human-readable message for chat webhook adapters."""
        event = payload.get("event")
        job = payload.get("job", {}) or {}
        collection = payload.get("collection", {}) or {}

        if event == EVENT_JOB_FAILED:
            title = "SLURMKIT ALERT: Job failed"
        elif event == EVENT_JOB_COMPLETED:
            title = "SLURMKIT: Job completed"
        elif event == EVENT_COLLECTION_FAILED:
            title = "SLURMKIT ALERT: Collection failed"
        elif event == EVENT_COLLECTION_COMPLETED:
            title = "SLURMKIT: Collection completed"
        else:
            title = "SLURMKIT: Test notification"

        lines = [title, f"Event: {event}"]

        if event in (EVENT_COLLECTION_COMPLETED, EVENT_COLLECTION_FAILED):
            lines.append(f"Collection: {collection.get('name') or 'unknown'}")
            report = payload.get("collection_report", {}) or {}
            summary = report.get("summary", {}) or {}
            counts = summary.get("counts", {}) or {}
            lines.append(f"Total jobs: {summary.get('total_jobs', 'unknown')}")
            lines.append(
                "Counts: "
                f"completed={counts.get('completed', 0)}, "
                f"failed={counts.get('failed', 0)}, "
                f"unknown={counts.get('unknown', 0)}, "
                f"running={counts.get('running', 0)}, "
                f"pending={counts.get('pending', 0)}"
            )

            failed_jobs = report.get("failed_jobs", []) or []
            if failed_jobs:
                first = failed_jobs[0]
                lines.append(
                    f"Sample issue: {first.get('job_name')} ({first.get('job_id')}) state={first.get('state')}"
                )

            ai_summary = payload.get("ai_summary")
            if ai_summary:
                lines.append("AI summary:")
                lines.append(ai_summary)

        else:
            lines.append(f"Job: {job.get('job_name') or 'unknown'}")
            lines.append(f"Job ID: {job.get('job_id') or 'unknown'}")
            if collection:
                lines.append(f"Collection: {collection.get('name') or 'unknown'}")
            if job.get("exit_code") is not None:
                lines.append(f"Exit code: {job.get('exit_code')}")
            if job.get("state"):
                lines.append(f"State: {job.get('state')}")

            output_tail = job.get("output_tail")
            if output_tail:
                lines.append("Output tail:")
                lines.append(output_tail)

        lines.append(f"Host: {payload.get('host', {}).get('hostname', 'unknown')}")

        return "\n".join(lines)

    def _route_payload(self, route: NotificationRoute, base_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Build adapter-specific payload for a notification route."""
        payload = copy.deepcopy(base_payload)
        payload.setdefault("meta", {})
        payload["meta"]["route_name"] = route.name
        payload["meta"]["route_type"] = route.route_type

        if route.route_type == "webhook":
            return payload
        if route.route_type == "slack":
            return {"text": self._render_human_message(payload)}
        if route.route_type == "discord":
            return {"content": self._render_human_message(payload)}
        if route.route_type == "email":
            return payload
        raise NotificationConfigError(f"Unsupported route type '{route.route_type}'.")

    def _render_email_subject(self, payload: Dict[str, Any]) -> str:
        """Render concise subject line for email delivery."""
        event = payload.get("event")
        job = payload.get("job", {}) or {}
        collection = payload.get("collection", {}) or {}

        if event == EVENT_JOB_FAILED:
            return f"SLURMKIT ALERT: job_failed ({job.get('job_id') or 'unknown'})"
        if event == EVENT_JOB_COMPLETED:
            return f"SLURMKIT: job_completed ({job.get('job_id') or 'unknown'})"
        if event == EVENT_COLLECTION_FAILED:
            return f"SLURMKIT ALERT: collection_failed ({collection.get('name') or 'unknown'})"
        if event == EVENT_COLLECTION_COMPLETED:
            return f"SLURMKIT: collection_completed ({collection.get('name') or 'unknown'})"
        return "SLURMKIT: test_notification"

    def _send_email(
        self,
        route: NotificationRoute,
        payload: Dict[str, Any],
        dry_run: bool = False,
    ) -> DeliveryResult:
        """Send text email through SMTP with retries."""
        if dry_run:
            return DeliveryResult(
                route_name=route.name,
                route_type=route.route_type,
                success=True,
                attempts=0,
                dry_run=True,
            )

        if not route.smtp_host or not route.email_from or not route.email_to:
            return DeliveryResult(
                route_name=route.name,
                route_type=route.route_type,
                success=False,
                attempts=0,
                error="email route is missing required SMTP fields",
            )

        attempts = 0
        for attempts in range(1, route.max_attempts + 1):
            try:
                message = EmailMessage()
                message["Subject"] = self._render_email_subject(payload)
                message["From"] = route.email_from
                message["To"] = ", ".join(route.email_to)
                message.set_content(self._render_human_message(payload))

                if route.smtp_ssl:
                    with smtplib.SMTP_SSL(
                        route.smtp_host,
                        route.smtp_port,
                        timeout=route.timeout_seconds,
                    ) as smtp_conn:
                        if route.smtp_username and route.smtp_password:
                            smtp_conn.login(route.smtp_username, route.smtp_password)
                        smtp_conn.send_message(message)
                else:
                    with smtplib.SMTP(
                        route.smtp_host,
                        route.smtp_port,
                        timeout=route.timeout_seconds,
                    ) as smtp_conn:
                        smtp_conn.ehlo()
                        if route.smtp_starttls:
                            smtp_conn.starttls()
                            smtp_conn.ehlo()
                        if route.smtp_username and route.smtp_password:
                            smtp_conn.login(route.smtp_username, route.smtp_password)
                        smtp_conn.send_message(message)

                return DeliveryResult(
                    route_name=route.name,
                    route_type=route.route_type,
                    success=True,
                    attempts=attempts,
                )
            except (smtplib.SMTPException, OSError) as exc:
                if attempts < route.max_attempts:
                    time.sleep(route.backoff_seconds * (2 ** (attempts - 1)))
                    continue
                return DeliveryResult(
                    route_name=route.name,
                    route_type=route.route_type,
                    success=False,
                    attempts=attempts,
                    error=str(exc),
                )

        return DeliveryResult(
            route_name=route.name,
            route_type=route.route_type,
            success=False,
            attempts=attempts,
            error="Email delivery failed after retries",
        )

    def _send_json(
        self,
        route: NotificationRoute,
        payload: Dict[str, Any],
        dry_run: bool = False,
    ) -> DeliveryResult:
        """Send JSON payload to a route with retries."""
        if dry_run:
            return DeliveryResult(
                route_name=route.name,
                route_type=route.route_type,
                success=True,
                attempts=0,
                dry_run=True,
            )

        if requests is None:
            return DeliveryResult(
                route_name=route.name,
                route_type=route.route_type,
                success=False,
                attempts=0,
                error="requests dependency is not available",
            )

        headers = {"Content-Type": "application/json"}
        headers.update(route.headers)

        attempts = 0
        for attempts in range(1, route.max_attempts + 1):
            try:
                response = requests.post(
                    route.url,
                    json=payload,
                    headers=headers,
                    timeout=route.timeout_seconds,
                )
            except requests.RequestException as exc:
                if attempts < route.max_attempts:
                    time.sleep(route.backoff_seconds * (2 ** (attempts - 1)))
                    continue
                return DeliveryResult(
                    route_name=route.name,
                    route_type=route.route_type,
                    success=False,
                    attempts=attempts,
                    error=str(exc),
                )

            status = response.status_code
            if 200 <= status < 300:
                return DeliveryResult(
                    route_name=route.name,
                    route_type=route.route_type,
                    success=True,
                    attempts=attempts,
                    status_code=status,
                )

            body_excerpt = (response.text or "").strip()[:200]
            error = f"HTTP {status}"
            if body_excerpt:
                error = f"{error}: {body_excerpt}"

            if 400 <= status < 500 or attempts >= route.max_attempts:
                return DeliveryResult(
                    route_name=route.name,
                    route_type=route.route_type,
                    success=False,
                    attempts=attempts,
                    status_code=status,
                    error=error,
                )

            time.sleep(route.backoff_seconds * (2 ** (attempts - 1)))

        return DeliveryResult(
            route_name=route.name,
            route_type=route.route_type,
            success=False,
            attempts=attempts,
            error="Delivery failed after retries",
        )

    def dispatch(
        self,
        payload: Dict[str, Any],
        routes: List[NotificationRoute],
        dry_run: bool = False,
    ) -> List[DeliveryResult]:
        """Dispatch payload to all selected routes."""
        results = []
        for route in routes:
            if route.route_type == "email":
                route_payload = copy.deepcopy(payload)
                route_payload.setdefault("meta", {})
                route_payload["meta"]["route_name"] = route.name
                route_payload["meta"]["route_type"] = route.route_type
                result = self._send_email(route, route_payload, dry_run=dry_run)
            else:
                route_payload = self._route_payload(route, payload)
                result = self._send_json(route, route_payload, dry_run=dry_run)
            results.append(result)
        return results

    def evaluate_delivery(self, results: List[DeliveryResult], strict: bool = False) -> int:
        """
        Evaluate CLI exit code from per-route delivery results.

        Returns:
            0 on success according to strictness policy, otherwise 1.
        """
        if not results:
            return 0

        successes = [result for result in results if result.success]
        if strict:
            return 0 if len(successes) == len(results) else 1
        return 0 if successes else 1
