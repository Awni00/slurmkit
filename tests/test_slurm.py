"""Tests for slurmkit.slurm module."""

import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from slurmkit.slurm import (
    get_canonical_sacct_states,
    get_pending_jobs,
    parse_elapsed_to_seconds,
    parse_timestamp,
    match_output_pattern,
    _try_match_pattern,
)


class TestParseElapsedToSeconds:
    """Tests for parse_elapsed_to_seconds function."""

    def test_minutes_seconds(self):
        """Test parsing MM:SS format."""
        assert parse_elapsed_to_seconds("05:30") == 330
        assert parse_elapsed_to_seconds("00:45") == 45

    def test_hours_minutes_seconds(self):
        """Test parsing HH:MM:SS format."""
        assert parse_elapsed_to_seconds("01:30:00") == 5400
        assert parse_elapsed_to_seconds("02:15:30") == 8130

    def test_days_hours_minutes_seconds(self):
        """Test parsing D-HH:MM:SS format."""
        assert parse_elapsed_to_seconds("1-00:00:00") == 86400
        assert parse_elapsed_to_seconds("2-12:30:00") == 2 * 86400 + 12 * 3600 + 30 * 60

    def test_invalid_returns_negative(self):
        """Test that invalid input returns -1."""
        assert parse_elapsed_to_seconds("") == -1
        assert parse_elapsed_to_seconds("N/A") == -1
        assert parse_elapsed_to_seconds("UNKNOWN") == -1
        assert parse_elapsed_to_seconds("invalid") == -1


class TestParseTimestamp:
    """Tests for parse_timestamp function."""

    def test_valid_timestamp(self):
        """Test parsing valid ISO timestamp."""
        dt = parse_timestamp("2025-01-15T14:30:00")
        assert dt is not None
        assert dt.year == 2025
        assert dt.month == 1
        assert dt.day == 15
        assert dt.hour == 14
        assert dt.minute == 30

    def test_invalid_returns_none(self):
        """Test that invalid input returns None."""
        assert parse_timestamp("") is None
        assert parse_timestamp("N/A") is None
        assert parse_timestamp("invalid") is None


class TestTryMatchPattern:
    """Tests for _try_match_pattern function."""

    def test_simple_pattern(self):
        """Test matching simple job_name.job_id.out pattern."""
        result = _try_match_pattern(
            "train_model.12345678.out",
            "{job_name}.{job_id}.out"
        )
        assert result is not None
        assert result[0] == "train_model"
        assert result[1] == "12345678"

    def test_pattern_with_wildcard(self):
        """Test matching pattern with wildcard."""
        result = _try_match_pattern(
            "train_model.12345678.node01.out",
            "{job_name}.{job_id}.*.out"
        )
        assert result is not None
        assert result[0] == "train_model"
        assert result[1] == "12345678"

    def test_slurm_default_pattern(self):
        """Test matching slurm-{job_id}.out pattern."""
        result = _try_match_pattern(
            "slurm-12345678.out",
            "slurm-{job_id}.out"
        )
        assert result is not None
        # job_name is captured as "slurm" in this case
        assert result[1] == "12345678"

    def test_array_job_id(self):
        """Test matching array job ID with underscore."""
        result = _try_match_pattern(
            "train_model.12345_10.out",
            "{job_name}.{job_id}.out"
        )
        assert result is not None
        assert result[0] == "train_model"
        assert result[1] == "12345_10"

    def test_no_match(self):
        """Test that non-matching filename returns None."""
        result = _try_match_pattern(
            "random_file.txt",
            "{job_name}.{job_id}.out"
        )
        assert result is None

    def test_complex_job_name(self):
        """Test matching job name with underscores and dots."""
        result = _try_match_pattern(
            "train_lr0.01_bs32.12345678.out",
            "{job_name}.{job_id}.out"
        )
        assert result is not None
        assert result[0] == "train_lr0.01_bs32"
        assert result[1] == "12345678"


class TestMatchOutputPattern:
    """Tests for match_output_pattern function."""

    def test_matches_first_pattern(self):
        """Test that first matching pattern is used."""
        # This test depends on config, so we use a mock
        from unittest.mock import MagicMock
        mock_config = MagicMock()
        mock_config.get_output_patterns.return_value = [
            "{job_name}.{job_id}.out",
            "slurm-{job_id}.out",
        ]

        result = match_output_pattern(
            "train.12345.out",
            patterns=["{job_name}.{job_id}.out", "slurm-{job_id}.out"],
        )
        assert result is not None
        assert result[0] == "train"
        assert result[1] == "12345"

    def test_fallback_to_later_pattern(self):
        """Test that later patterns are tried if earlier don't match."""
        result = match_output_pattern(
            "slurm-12345.out",
            patterns=["{job_name}.{job_id}.out", "slurm-{job_id}.out"],
        )
        assert result is not None
        assert result[1] == "12345"

    def test_no_match_returns_none(self):
        """Test that None is returned if no pattern matches."""
        result = match_output_pattern(
            "random.txt",
            patterns=["{job_name}.{job_id}.out"],
        )
        assert result is None


class TestFindJobOutput:
    """Tests for find_job_output function."""

    def test_find_output_file(self):
        """Test finding an output file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            jobs_dir = Path(tmpdir) / "jobs"
            jobs_dir.mkdir()

            # Create test output file
            output_file = jobs_dir / "train.12345678.out"
            output_file.write_text("test output")

            from slurmkit.slurm import find_job_output
            from unittest.mock import MagicMock

            mock_config = MagicMock()
            mock_config.get_output_patterns.return_value = ["{job_name}.{job_id}.out"]

            results = find_job_output("12345678", jobs_dir, mock_config)
            assert len(results) == 1
            assert results[0].name == "train.12345678.out"

    def test_find_no_match(self):
        """Test finding with no matching files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            jobs_dir = Path(tmpdir) / "jobs"
            jobs_dir.mkdir()

            from slurmkit.slurm import find_job_output
            from unittest.mock import MagicMock

            mock_config = MagicMock()
            mock_config.get_output_patterns.return_value = ["{job_name}.{job_id}.out"]

            results = find_job_output("99999999", jobs_dir, mock_config)
            assert len(results) == 0


def test_get_pending_jobs_preserves_dot_suffixes(monkeypatch):
    """Pending job names should preserve dotted suffixes like `.resubmit-1`."""
    from slurmkit import slurm

    fake_output = "123|train.resubmit-1|PENDING|N/A\n"
    monkeypatch.setattr(
        slurm,
        "run_command",
        lambda _cmd: SimpleNamespace(stdout=fake_output),
    )

    pending = get_pending_jobs()
    assert pending[0]["job_name"] == "train.resubmit-1"


def _mock_sacct_rows(monkeypatch, output: str) -> None:
    from slurmkit import slurm

    monkeypatch.setattr(
        slurm,
        "run_command",
        lambda _cmd: SimpleNamespace(stdout=output),
    )


def test_canonical_state_prefers_batch_completed_zero_exit(monkeypatch):
    _mock_sacct_rows(
        monkeypatch,
        (
            "123|PREEMPTED|0:0|0:0|Preempted by scheduler|2026-04-05T10:00:00|2026-04-05T10:12:00\n"
            "123.batch|COMPLETED|0:0|0:0||2026-04-05T10:00:00|2026-04-05T10:11:00\n"
            "123.extern|COMPLETED|0:0|0:0||2026-04-05T10:00:00|2026-04-05T10:11:30\n"
        ),
    )

    result = get_canonical_sacct_states(["123"])
    assert result["123"]["state"] == "COMPLETED"
    assert result["123"]["end"] == "2026-04-05T10:11:00"
    assert result["123"]["raw_state"]["resolution"]["rule"] == "batch_completed_exit_zero"


def test_canonical_state_completed_nonzero_exit_is_failed(monkeypatch):
    _mock_sacct_rows(
        monkeypatch,
        (
            "200|FAILED|1:0|1:0||2026-04-05T10:00:00|2026-04-05T10:01:00\n"
            "200.batch|COMPLETED|1:0|1:0||2026-04-05T10:00:00|2026-04-05T10:01:00\n"
        ),
    )

    result = get_canonical_sacct_states(["200"])
    assert result["200"]["state"] == "FAILED"
    assert result["200"]["raw_state"]["resolution"]["rule"] == "batch_completed_nonzero_exit"


def test_canonical_state_live_rows_take_precedence(monkeypatch):
    _mock_sacct_rows(
        monkeypatch,
        (
            "300|FAILED|1:0|1:0||2026-04-05T10:00:00|2026-04-05T10:01:00\n"
            "300.batch|COMPLETED|0:0|0:0||2026-04-05T10:00:00|2026-04-05T10:01:00\n"
            "300.extern|RUNNING|0:0|0:0||2026-04-05T10:00:00|Unknown\n"
        ),
    )

    result = get_canonical_sacct_states(["300"])
    assert result["300"]["state"] == "RUNNING"
    assert result["300"]["raw_state"]["resolution"]["rule"] == "live_state_present"


def test_canonical_state_queue_rows_take_precedence_when_no_live(monkeypatch):
    _mock_sacct_rows(
        monkeypatch,
        (
            "400|FAILED|1:0|1:0||2026-04-05T10:00:00|2026-04-05T10:01:00\n"
            "400.batch|FAILED|1:0|1:0||2026-04-05T10:00:00|2026-04-05T10:01:00\n"
            "400.extern|PENDING|0:0|0:0|Priority|Unknown|Unknown\n"
        ),
    )

    result = get_canonical_sacct_states(["400"])
    assert result["400"]["state"] == "PENDING"
    assert result["400"]["raw_state"]["resolution"]["rule"] == "queue_state_present"


def test_canonical_state_cancelled_preemption_and_timeout_reason(monkeypatch):
    _mock_sacct_rows(
        monkeypatch,
        (
            "500|PREEMPTED|0:0|0:0||2026-04-05T10:00:00|2026-04-05T10:05:00\n"
            "500.batch|CANCELLED|0:0|0:0|QOS preempted|2026-04-05T10:00:00|2026-04-05T10:05:00\n"
            "501|CANCELLED|0:0|0:0||2026-04-05T10:00:00|2026-04-05T10:06:00\n"
            "501.batch|CANCELLED|0:0|0:0|TIME LIMIT reached|2026-04-05T10:00:00|2026-04-05T10:06:00\n"
        ),
    )

    result = get_canonical_sacct_states(["500", "501"])
    assert result["500"]["state"] == "PREEMPTED"
    assert result["500"]["raw_state"]["resolution"]["rule"] == "batch_cancelled_preempted"
    assert result["501"]["state"] == "TIMEOUT"
    assert result["501"]["raw_state"]["resolution"]["rule"] == "batch_cancelled_timeout"


def test_canonical_state_parent_fallback_without_batch(monkeypatch):
    _mock_sacct_rows(
        monkeypatch,
        "600|COMPLETED|1:0|1:0||2026-04-05T10:00:00|2026-04-05T10:07:00\n",
    )

    result = get_canonical_sacct_states(["600"])
    assert result["600"]["state"] == "FAILED"
    assert result["600"]["raw_state"]["resolution"]["rule"] == "parent_completed_nonzero_exit"


def test_canonical_state_normalizes_state_tokens(monkeypatch):
    _mock_sacct_rows(
        monkeypatch,
        (
            "700|FAILED|1:0|1:0||2026-04-05T10:00:00|2026-04-05T10:01:00\n"
            "700.batch|COMPLETED+|0:0|0:0||2026-04-05T10:00:00|2026-04-05T10:01:00\n"
            "701|FAILED|1:0|1:0||2026-04-05T10:00:00|2026-04-05T10:01:00\n"
            "701.batch|CANCELLED by 1234|0:0|0:0||2026-04-05T10:00:00|2026-04-05T10:01:00\n"
        ),
    )

    result = get_canonical_sacct_states(["700", "701"])
    assert result["700"]["raw_state"]["rows"]["batch"]["state_base"] == "COMPLETED"
    assert result["700"]["state"] == "COMPLETED"
    assert result["701"]["raw_state"]["rows"]["batch"]["state_base"] == "CANCELLED"
    assert result["701"]["state"] == "CANCELLED"


def test_canonical_state_prefers_latest_duplicate_batch_row(monkeypatch):
    _mock_sacct_rows(
        monkeypatch,
        (
            "800|PREEMPTED|0:0|0:0|preempted|2026-04-05T10:00:00|2026-04-05T10:03:00\n"
            "800.batch|COMPLETED|1:0|1:0||2026-04-05T10:00:00|2026-04-05T10:02:00\n"
            "800.batch|COMPLETED|0:0|0:0||2026-04-05T10:00:00|2026-04-05T10:04:00\n"
        ),
    )

    result = get_canonical_sacct_states(["800"])
    assert result["800"]["state"] == "COMPLETED"
    assert result["800"]["end"] == "2026-04-05T10:04:00"


def test_canonical_state_uses_derived_exit_code_when_exit_code_missing(monkeypatch):
    _mock_sacct_rows(
        monkeypatch,
        (
            "900|FAILED|Unknown|Unknown||2026-04-05T10:00:00|2026-04-05T10:03:00\n"
            "900.batch|COMPLETED|Unknown|1:0||2026-04-05T10:00:00|2026-04-05T10:03:00\n"
        ),
    )

    result = get_canonical_sacct_states(["900"])
    assert result["900"]["state"] == "FAILED"
    assert result["900"]["raw_state"]["resolution"]["rule"] == "batch_completed_nonzero_exit"


def test_canonical_state_resolves_when_parent_row_missing(monkeypatch):
    _mock_sacct_rows(
        monkeypatch,
        "910.batch|COMPLETED|0:0|0:0||2026-04-05T10:00:00|2026-04-05T10:02:00\n",
    )

    result = get_canonical_sacct_states(["910"])
    assert result["910"]["state"] == "COMPLETED"
    assert result["910"]["raw_state"]["rows"]["parent"] is None
