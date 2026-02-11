"""Phase 2 tests for collection-final notifications."""

from pathlib import Path

import pytest
import yaml

from slurmkit.collections import CollectionManager
from slurmkit.config import Config
from slurmkit.notifications import (
    EVENT_COLLECTION_COMPLETED,
    EVENT_COLLECTION_FAILED,
    NotificationService,
)


def _make_config(tmp_path: Path, data: dict) -> Config:
    """Create config file and return Config instance."""
    config_dir = tmp_path / ".slurm-kit"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(data, f)
    return Config(project_root=tmp_path)


def test_latest_attempt_finality_uses_resubmission_state(tmp_path):
    """Latest-attempt mode should treat successful resubmission as completed."""
    config = _make_config(tmp_path, {"collections_dir": ".job-collections/"})
    manager = CollectionManager(config=config)
    collection = manager.create("exp")
    collection.add_job(job_name="job1", job_id="100", state="FAILED")
    collection.add_resubmission("job1", job_id="101")
    collection.get_job("job1")["resubmissions"][-1]["state"] = "COMPLETED"
    manager.save(collection)

    service = NotificationService(config=config)
    loaded = manager.load("exp")
    finality = service.evaluate_collection_finality(loaded, attempt_mode="latest")

    assert finality.terminal is True
    assert finality.event == EVENT_COLLECTION_COMPLETED
    assert finality.counts["completed"] == 1
    assert finality.counts["failed"] == 0


def test_collection_finality_non_terminal_when_running(tmp_path):
    """Running jobs should prevent collection-final notification."""
    config = _make_config(tmp_path, {"collections_dir": ".job-collections/"})
    manager = CollectionManager(config=config)
    collection = manager.create("exp")
    collection.add_job(job_name="job1", job_id="100", state="RUNNING")
    manager.save(collection)

    service = NotificationService(config=config)
    finality = service.evaluate_collection_finality(manager.load("exp"), attempt_mode="latest")

    assert finality.terminal is False
    assert finality.event is None
    assert finality.counts["running"] == 1


def test_collection_finality_trigger_only_active_with_zero_exit_code(tmp_path):
    """Sole active trigger row with zero exit should infer completed terminality."""
    config = _make_config(tmp_path, {"collections_dir": ".job-collections/"})
    manager = CollectionManager(config=config)
    collection = manager.create("exp")
    collection.add_job(job_name="job1", job_id="100", state="RUNNING")
    manager.save(collection)

    service = NotificationService(config=config)
    finality = service.evaluate_collection_finality(
        manager.load("exp"),
        attempt_mode="latest",
        trigger_job_id="100",
        trigger_exit_code=0,
    )

    assert finality.terminal is True
    assert finality.event == EVENT_COLLECTION_COMPLETED
    assert finality.counts["completed"] == 1
    assert finality.counts["running"] == 0
    assert finality.warnings == []


def test_collection_finality_trigger_only_active_without_exit_code_warns(tmp_path):
    """Missing trigger exit code should infer unknown with warning when fallback is used."""
    config = _make_config(tmp_path, {"collections_dir": ".job-collections/"})
    manager = CollectionManager(config=config)
    collection = manager.create("exp")
    collection.add_job(job_name="job1", job_id="100", state="RUNNING")
    manager.save(collection)

    service = NotificationService(config=config)
    finality = service.evaluate_collection_finality(
        manager.load("exp"),
        attempt_mode="latest",
        trigger_job_id="100",
        trigger_exit_code=None,
    )

    assert finality.terminal is True
    assert finality.event == EVENT_COLLECTION_FAILED
    assert finality.counts["unknown"] == 1
    assert len(finality.warnings) == 1
    assert "--trigger-exit-code" in finality.warnings[0]


def test_collection_finality_trigger_not_only_active_stays_non_terminal(tmp_path):
    """No inference should happen when active rows include non-trigger jobs."""
    config = _make_config(tmp_path, {"collections_dir": ".job-collections/"})
    manager = CollectionManager(config=config)
    collection = manager.create("exp")
    collection.add_job(job_name="job1", job_id="100", state="RUNNING")
    collection.add_job(job_name="job2", job_id="200", state="PENDING")
    manager.save(collection)

    service = NotificationService(config=config)
    finality = service.evaluate_collection_finality(
        manager.load("exp"),
        attempt_mode="latest",
        trigger_job_id="100",
        trigger_exit_code=0,
    )

    assert finality.terminal is False
    assert finality.event is None
    assert finality.counts["running"] == 1
    assert finality.counts["pending"] == 1
    assert finality.warnings == []


def test_collection_finality_unknown_is_failure_like(tmp_path):
    """Unknown terminal states should classify as collection_failed."""
    config = _make_config(tmp_path, {"collections_dir": ".job-collections/"})
    manager = CollectionManager(config=config)
    collection = manager.create("exp")
    collection.add_job(job_name="job1", job_id="100", state=None)
    manager.save(collection)

    service = NotificationService(config=config)
    finality = service.evaluate_collection_finality(manager.load("exp"), attempt_mode="latest")

    assert finality.terminal is True
    assert finality.event == EVENT_COLLECTION_FAILED
    assert finality.counts["unknown"] == 1


def test_collection_report_includes_failed_rows_and_recommendations(tmp_path):
    """Collection report should include failed rows, analysis sections, and recommendations."""
    out = tmp_path / "job.out"
    out.write_text("line1\nline2\nline3\n")

    config = _make_config(
        tmp_path,
        {
            "collections_dir": ".job-collections/",
            "notifications": {
                "collection_final": {
                    "attempt_mode": "latest",
                    "min_support": 1,
                    "top_k": 5,
                    "include_failed_output_tail_lines": 2,
                }
            },
        },
    )
    manager = CollectionManager(config=config)
    collection = manager.create("exp")
    collection.add_job(job_name="a", job_id="1", state="FAILED", output_path=out, parameters={"algo": "x"})
    collection.add_job(job_name="b", job_id="2", state="COMPLETED", parameters={"algo": "y"})
    manager.save(collection)

    service = NotificationService(config=config)
    report = service.build_collection_report(manager.load("exp"), trigger_job_id="1")

    assert report["summary"]["terminal"] is True
    assert report["summary"]["counts"]["failed"] == 1
    assert len(report["failed_jobs"]) == 1
    assert report["failed_jobs"][0]["output_tail"] == "line2\nline3"
    assert isinstance(report["top_risky_values"], list)
    assert isinstance(report["top_stable_values"], list)
    assert len(report["recommendations"]) >= 1


def test_collection_final_dedup_marker_persists(tmp_path):
    """Dedup marker should survive save/load roundtrip via collection metadata."""
    config = _make_config(tmp_path, {"collections_dir": ".job-collections/"})
    manager = CollectionManager(config=config)
    collection = manager.create("exp")
    collection.add_job(job_name="a", job_id="1", state="COMPLETED")
    manager.save(collection)

    service = NotificationService(config=config)
    loaded = manager.load("exp")
    finality = service.evaluate_collection_finality(loaded, attempt_mode="latest")
    fingerprint = service.compute_collection_final_fingerprint(
        collection_name=loaded.name,
        event=EVENT_COLLECTION_COMPLETED,
        effective_rows=finality.effective_rows,
    )

    assert service.should_skip_collection_final(loaded, EVENT_COLLECTION_COMPLETED, fingerprint) is False
    service.mark_collection_final_sent(loaded, EVENT_COLLECTION_COMPLETED, fingerprint, trigger_job_id="1")
    manager.save(loaded)

    reloaded = manager.load("exp")
    assert service.should_skip_collection_final(reloaded, EVENT_COLLECTION_COMPLETED, fingerprint) is True


def test_route_filtering_for_collection_events(tmp_path):
    """Collection events should route independently from job events."""
    config = _make_config(
        tmp_path,
        {
            "notifications": {
                "routes": [
                    {
                        "name": "r_complete",
                        "type": "webhook",
                        "url": "https://example.test/c",
                        "events": [EVENT_COLLECTION_COMPLETED],
                    },
                    {
                        "name": "r_failed",
                        "type": "webhook",
                        "url": "https://example.test/f",
                        "events": [EVENT_COLLECTION_FAILED],
                    },
                ]
            }
        },
    )
    service = NotificationService(config=config)
    complete_routes = service.resolve_routes(event=EVENT_COLLECTION_COMPLETED).routes
    failed_routes = service.resolve_routes(event=EVENT_COLLECTION_FAILED).routes

    assert [r.name for r in complete_routes] == ["r_complete"]
    assert [r.name for r in failed_routes] == ["r_failed"]


def test_ai_callback_success_returns_summary(tmp_path, monkeypatch):
    """Configured AI callback should return markdown summary."""
    module_path = tmp_path / "ai_module.py"
    module_path.write_text(
        "def summarize(payload):\n"
        "    return f\"AI summary for {payload['collection_name']}\"\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    config = _make_config(
        tmp_path,
        {
            "notifications": {
                "collection_final": {
                    "ai": {
                        "enabled": True,
                        "callback": "ai_module:summarize",
                    }
                }
            }
        },
    )
    service = NotificationService(config=config)
    ai_summary, ai_status, warning = service.run_collection_ai_callback({"collection_name": "exp"})

    assert ai_status == "available"
    assert warning is None
    assert ai_summary == "AI summary for exp"


def test_ai_callback_failure_falls_back(tmp_path):
    """Bad callback path should mark AI status unavailable and continue."""
    config = _make_config(
        tmp_path,
        {
            "notifications": {
                "collection_final": {
                    "ai": {
                        "enabled": True,
                        "callback": "missing.module:fn",
                    }
                }
            }
        },
    )
    service = NotificationService(config=config)
    ai_summary, ai_status, warning = service.run_collection_ai_callback({"collection_name": "exp"})

    assert ai_summary is None
    assert ai_status == "unavailable"
    assert "AI callback failed" in warning


def test_job_ai_callback_success_returns_summary(tmp_path, monkeypatch):
    """Configured job AI callback should return markdown summary."""
    module_path = tmp_path / "job_ai_module_phase2.py"
    module_path.write_text(
        "def summarize(payload):\n"
        "    return f\"AI summary for job {payload['job']['job_id']}\"\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    config = _make_config(
        tmp_path,
        {
            "notifications": {
                "job": {
                    "ai": {
                        "enabled": True,
                        "callback": "job_ai_module_phase2:summarize",
                    }
                }
            }
        },
    )
    service = NotificationService(config=config)
    ai_summary, ai_status, warning = service.run_job_ai_callback(
        {"job": {"job_id": "123"}, "event": "job_failed"}
    )

    assert ai_status == "available"
    assert warning is None
    assert ai_summary == "AI summary for job 123"


def test_job_ai_callback_failure_falls_back(tmp_path):
    """Bad job callback path should mark AI status unavailable and continue."""
    config = _make_config(
        tmp_path,
        {
            "notifications": {
                "job": {
                    "ai": {
                        "enabled": True,
                        "callback": "missing.module:fn",
                    }
                }
            }
        },
    )
    service = NotificationService(config=config)
    ai_summary, ai_status, warning = service.run_job_ai_callback({"job": {"job_id": "123"}})

    assert ai_summary is None
    assert ai_status == "unavailable"
    assert "AI callback failed" in warning


def test_collection_final_config_uses_spec_override(tmp_path):
    """Collection-final report knobs should resolve from collection spec overrides."""
    spec_path = tmp_path / "specs" / "exp_spec.yaml"
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(
        "notifications:\n"
        "  collection_final:\n"
        "    attempt_mode: primary\n"
        "    min_support: 7\n"
        "    top_k: 4\n"
        "    include_failed_output_tail_lines: 3\n",
        encoding="utf-8",
    )

    config = _make_config(
        tmp_path,
        {
            "collections_dir": ".job-collections/",
            "notifications": {
                "collection_final": {
                    "attempt_mode": "latest",
                    "min_support": 3,
                    "top_k": 10,
                    "include_failed_output_tail_lines": 20,
                }
            },
        },
    )
    manager = CollectionManager(config=config)
    collection = manager.create("exp")
    collection.meta["generation"] = {"spec_path": "specs/exp_spec.yaml"}
    collection.add_job(job_name="job1", job_id="100", state="COMPLETED")
    manager.save(collection)

    service = NotificationService(config=config)
    warnings = []
    cfg = service.get_collection_final_config(collection_name="exp", warnings=warnings)

    assert warnings == []
    assert cfg.attempt_mode == "primary"
    assert cfg.min_support == 7
    assert cfg.top_k == 4
    assert cfg.include_failed_output_tail_lines == 3


def test_collection_ai_callback_uses_spec_override(tmp_path, monkeypatch):
    """Collection-final AI callback should resolve from collection spec overrides."""
    module_path = tmp_path / "spec_collection_ai.py"
    module_path.write_text(
        "def summarize(payload):\n"
        "    return f\"spec-summary-{payload['collection_name']}\"\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    spec_path = tmp_path / "specs" / "exp_spec.yaml"
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(
        "notifications:\n"
        "  collection_final:\n"
        "    ai:\n"
        "      enabled: true\n"
        "      callback: spec_collection_ai:summarize\n",
        encoding="utf-8",
    )

    config = _make_config(
        tmp_path,
        {
            "collections_dir": ".job-collections/",
            "notifications": {
                "collection_final": {
                    "ai": {
                        "enabled": True,
                        "callback": "missing.module:fn",
                    }
                }
            },
        },
    )
    manager = CollectionManager(config=config)
    collection = manager.create("exp")
    collection.meta["generation"] = {"spec_path": "specs/exp_spec.yaml"}
    collection.add_job(job_name="job1", job_id="100", state="COMPLETED")
    manager.save(collection)

    service = NotificationService(config=config)
    ai_summary, ai_status, warning = service.run_collection_ai_callback({"collection_name": "exp"})

    assert warning is None
    assert ai_status == "available"
    assert ai_summary == "spec-summary-exp"


def test_collection_lock_timeout_when_already_locked(tmp_path):
    """Second lock acquisition should timeout while first lock is held."""
    config = _make_config(tmp_path, {"collections_dir": ".job-collections/"})
    manager = CollectionManager(config=config)
    manager.create("exp")

    service = NotificationService(config=config)
    with service.collection_lock("exp", timeout_seconds=0.2):
        with pytest.raises(TimeoutError):
            with service.collection_lock("exp", timeout_seconds=0.1):
                pass
