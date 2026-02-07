"""Tests for slurmkit.config module."""

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from slurmkit.config import (
    Config,
    DEFAULT_CONFIG,
    init_config,
    get_config,
    _deep_merge,
    _get_nested,
    _set_nested,
)


class TestDeepMerge:
    """Tests for _deep_merge function."""

    def test_simple_merge(self):
        """Test merging flat dictionaries."""
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        result = _deep_merge(base, override)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self):
        """Test merging nested dictionaries."""
        base = {"a": {"x": 1, "y": 2}, "b": 3}
        override = {"a": {"y": 5, "z": 6}}
        result = _deep_merge(base, override)
        assert result == {"a": {"x": 1, "y": 5, "z": 6}, "b": 3}

    def test_override_non_dict_with_dict(self):
        """Test overriding a non-dict value with a dict."""
        base = {"a": 1}
        override = {"a": {"x": 2}}
        result = _deep_merge(base, override)
        assert result == {"a": {"x": 2}}


class TestNestedAccess:
    """Tests for _get_nested and _set_nested functions."""

    def test_get_nested_simple(self):
        """Test getting a top-level key."""
        d = {"a": 1, "b": 2}
        assert _get_nested(d, "a") == 1

    def test_get_nested_deep(self):
        """Test getting a nested key."""
        d = {"a": {"b": {"c": 3}}}
        assert _get_nested(d, "a.b.c") == 3

    def test_get_nested_missing(self):
        """Test getting a missing key returns default."""
        d = {"a": 1}
        assert _get_nested(d, "b", "default") == "default"

    def test_set_nested_simple(self):
        """Test setting a top-level key."""
        d = {}
        _set_nested(d, "a", 1)
        assert d == {"a": 1}

    def test_set_nested_deep(self):
        """Test setting a nested key."""
        d = {}
        _set_nested(d, "a.b.c", 3)
        assert d == {"a": {"b": {"c": 3}}}


class TestConfig:
    """Tests for Config class."""

    def test_default_config(self):
        """Test that default config is loaded when no file exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(project_root=tmpdir)
            assert config.get("jobs_dir") == DEFAULT_CONFIG["jobs_dir"]
            assert config.get("ui.mode") == "plain"

    def test_load_from_file(self):
        """Test loading config from a YAML file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / ".slurm-kit"
            config_dir.mkdir()
            config_file = config_dir / "config.yaml"

            # Write custom config
            custom_config = {
                "jobs_dir": "custom_jobs/",
                "slurm_defaults": {"partition": "custom_partition"},
                "ui": {"mode": "auto"},
            }
            with open(config_file, "w") as f:
                yaml.dump(custom_config, f)

            config = Config(project_root=tmpdir)

            # Custom values should be loaded
            assert config.get("jobs_dir") == "custom_jobs/"
            assert config.get("slurm_defaults.partition") == "custom_partition"
            assert config.get("ui.mode") == "auto"

            # Default values should still be present
            assert config.get("slurm_defaults.time") == DEFAULT_CONFIG["slurm_defaults"]["time"]

    def test_get_path(self):
        """Test get_path resolves paths relative to project root."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(project_root=tmpdir)
            jobs_path = config.get_path("jobs_dir")
            assert jobs_path == Path(tmpdir) / "jobs"

    def test_get_output_patterns(self):
        """Test getting output patterns."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(project_root=tmpdir)
            patterns = config.get_output_patterns()
            assert isinstance(patterns, list)
            assert len(patterns) > 0

    def test_env_override(self):
        """Test environment variable overrides."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["SLURMKIT_JOBS_DIR"] = "env_jobs/"
            try:
                config = Config(project_root=tmpdir)
                assert config.get("jobs_dir") == "env_jobs/"
            finally:
                del os.environ["SLURMKIT_JOBS_DIR"]


class TestInitConfig:
    """Tests for init_config function."""

    def test_creates_config_file(self):
        """Test that init_config creates a config file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = init_config(project_root=tmpdir)
            assert config_path.exists()
            assert config_path == Path(tmpdir) / ".slurm-kit" / "config.yaml"

    def test_raises_if_exists(self):
        """Test that init_config raises if file exists and overwrite=False."""
        with tempfile.TemporaryDirectory() as tmpdir:
            init_config(project_root=tmpdir)
            with pytest.raises(FileExistsError):
                init_config(project_root=tmpdir)

    def test_overwrite(self):
        """Test that init_config overwrites when overwrite=True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            init_config(project_root=tmpdir)
            init_config(project_root=tmpdir, overwrite=True)  # Should not raise

    def test_custom_values(self):
        """Test init_config with custom values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = init_config(
                project_root=tmpdir,
                jobs_dir="my_jobs/",
            )

            with open(config_path, "r") as f:
                data = yaml.safe_load(f)

            assert data["jobs_dir"] == "my_jobs/"
