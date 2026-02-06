"""
Notification utilities for job lifecycle events.

This module provides:
- Notification route parsing from configuration
- Job context lookup from collection metadata
- Canonical payload generation for webhook notifications
- Slack/Discord adapters with human-readable summaries
- HTTP delivery with bounded retries
"""

from __future__ import annotations

import copy
import os
import re
import socket
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from slurmkit.collections import Collection, CollectionManager
from slurmkit.config import Config, get_config
from slurmkit.slurm import find_job_output

try:
    import requests
except ImportError:  # pragma: no cover - guarded by packaging dependency
    requests = None


ROUTE_TYPES = {"webhook", "slack", "discord"}
DEFAULT_EVENT_FAILED = "job_failed"
EVENT_JOB_COMPLETED = "job_completed"
EVENT_JOB_FAILED = "job_failed"
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


def _to_positive_int(value: Any, default: int) -> int:
    """Convert value to positive int with default fallback."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


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


def _match_collection_job(collection: Collection, job_id: str) -> Optional[Tuple[Dict[str, Any], Optional[Dict[str, Any]]]]:
    """Find a primary or resubmission job record by job ID."""
    for job in collection.jobs:
        if job.get("job_id") == job_id:
            return job, None

        for resubmission in job.get("resubmissions", []):
            if resubmission.get("job_id") == job_id:
                return job, resubmission

    return None


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
            backoff_seconds=_to_positive_float(defaults_raw.get("backoff_seconds"), 0.5),
            output_tail_lines=_to_positive_int(defaults_raw.get("output_tail_lines"), 40),
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
        backoff_seconds = _to_positive_float(raw_route.get("backoff_seconds"), defaults.backoff_seconds)

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
                errors.append(f"Route entry at index {idx} must be a mapping.")
                continue

            raw_name = str(raw.get("name", "")).strip()
            if raw_name:
                known_names.add(raw_name)

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
        else:
            title = "SLURMKIT: Test notification"

        lines = [
            title,
            f"Event: {event}",
            f"Job: {job.get('job_name') or 'unknown'}",
            f"Job ID: {job.get('job_id') or 'unknown'}",
        ]

        if collection:
            lines.append(f"Collection: {collection.get('name') or 'unknown'}")
        if job.get("exit_code") is not None:
            lines.append(f"Exit code: {job.get('exit_code')}")
        if job.get("state"):
            lines.append(f"State: {job.get('state')}")
        lines.append(f"Host: {payload.get('host', {}).get('hostname', 'unknown')}")

        output_tail = job.get("output_tail")
        if output_tail:
            lines.append("Output tail:")
            lines.append(output_tail)

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
        raise NotificationConfigError(f"Unsupported route type '{route.route_type}'.")

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
