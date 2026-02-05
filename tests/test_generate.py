"""Tests for slurmkit.generate module."""

import tempfile
from pathlib import Path

import pytest
import yaml

from slurmkit.generate import (
    expand_grid,
    expand_parameters,
    generate_job_name,
    JobGenerator,
    load_job_spec,
)


class TestExpandGrid:
    """Tests for expand_grid function."""

    def test_single_param(self):
        """Test grid expansion with single parameter."""
        params = {"a": [1, 2, 3]}
        result = list(expand_grid(params))
        assert result == [{"a": 1}, {"a": 2}, {"a": 3}]

    def test_two_params(self):
        """Test grid expansion with two parameters."""
        params = {"a": [1, 2], "b": ["x", "y"]}
        result = list(expand_grid(params))
        assert len(result) == 4
        assert {"a": 1, "b": "x"} in result
        assert {"a": 1, "b": "y"} in result
        assert {"a": 2, "b": "x"} in result
        assert {"a": 2, "b": "y"} in result

    def test_empty_params(self):
        """Test grid expansion with empty params."""
        result = list(expand_grid({}))
        assert result == [{}]

    def test_single_value_per_param(self):
        """Test grid expansion when each param has one value."""
        params = {"a": [1], "b": ["x"]}
        result = list(expand_grid(params))
        assert result == [{"a": 1, "b": "x"}]

    def test_grid_filter(self):
        """Test grid expansion with a filter function."""
        params = {"a": [1, 2], "b": ["x"]}

        def include_params(p):
            return p["a"] == 2

        result = list(expand_grid(params, filter_func=include_params))
        assert result == [{"a": 2, "b": "x"}]


class TestExpandParameters:
    """Tests for expand_parameters function."""

    def test_grid_mode(self):
        """Test parameter expansion in grid mode."""
        spec = {
            "mode": "grid",
            "values": {"a": [1, 2], "b": ["x"]},
        }
        result = expand_parameters(spec)
        assert len(result) == 2
        assert {"a": 1, "b": "x"} in result
        assert {"a": 2, "b": "x"} in result

    def test_list_mode(self):
        """Test parameter expansion in list mode."""
        spec = {
            "mode": "list",
            "values": [
                {"a": 1, "b": "x"},
                {"a": 2, "b": "y"},
            ],
        }
        result = expand_parameters(spec)
        assert len(result) == 2
        assert result[0] == {"a": 1, "b": "x"}
        assert result[1] == {"a": 2, "b": "y"}

    def test_default_mode_is_grid(self):
        """Test that default mode is grid."""
        spec = {"values": {"a": [1, 2]}}
        result = expand_parameters(spec)
        assert len(result) == 2

    def test_invalid_mode_raises(self):
        """Test that invalid mode raises error."""
        spec = {"mode": "invalid", "values": {"a": [1]}}
        with pytest.raises(ValueError):
            expand_parameters(spec)

    def test_grid_mode_with_filter_file(self):
        """Test parameter expansion with a filter function loaded from file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filter_path = Path(tmpdir) / "filter.py"
            filter_path.write_text(
                "def include_params(params):\n"
                "    return params.get('a') == 2\n"
            )

            spec = {
                "mode": "grid",
                "values": {"a": [1, 2], "b": ["x"]},
                "filter": {"file": str(filter_path)},
            }

            result = expand_parameters(spec)
            assert result == [{"a": 2, "b": "x"}]

    def test_list_mode_ignores_filter(self):
        """Test that list mode ignores filter logic."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filter_path = Path(tmpdir) / "filter.py"
            filter_path.write_text(
                "def include_params(params):\n"
                "    return False\n"
            )

            spec = {
                "mode": "list",
                "values": [{"a": 1}, {"a": 2}],
                "filter": {"file": str(filter_path)},
            }

            result = expand_parameters(spec)
            assert result == [{"a": 1}, {"a": 2}]


class TestGenerateJobName:
    """Tests for generate_job_name function."""

    def test_default_naming(self):
        """Test default job naming (key-value pairs)."""
        params = {"lr": 0.01, "bs": 32}
        name = generate_job_name(params)
        # Should contain all key-value pairs
        assert "lr" in name
        assert "0.01" in name
        assert "bs" in name
        assert "32" in name

    def test_custom_pattern(self):
        """Test custom naming pattern."""
        params = {"model": "resnet", "lr": 0.01}
        name = generate_job_name(params, pattern="{{ model }}_lr{{ lr }}")
        assert name == "resnet_lr0.01"

    def test_pattern_with_formatting(self):
        """Test pattern with Jinja2 formatting."""
        params = {"value": 0.001}
        name = generate_job_name(params, pattern="val_{{ value }}")
        assert name == "val_0.001"


class TestJobGenerator:
    """Tests for JobGenerator class."""

    @pytest.fixture
    def template_dir(self):
        """Create a temporary directory with a test template."""
        with tempfile.TemporaryDirectory() as tmpdir:
            template_path = Path(tmpdir) / "test.job.j2"
            template_path.write_text("""#!/bin/bash
#SBATCH --job-name={{ job_name }}
#SBATCH --partition={{ slurm.partition }}
#SBATCH --time={{ slurm.time }}

echo "Learning rate: {{ learning_rate }}"
echo "Batch size: {{ batch_size }}"
""")
            yield tmpdir

    def test_generator_count_jobs(self, template_dir):
        """Test counting jobs to generate."""
        generator = JobGenerator(
            template_path=Path(template_dir) / "test.job.j2",
            parameters={
                "mode": "grid",
                "values": {"learning_rate": [0.01, 0.1], "batch_size": [32, 64]},
            },
            slurm_defaults={"partition": "gpu", "time": "1:00:00"},
        )
        assert generator.count_jobs() == 4

    def test_generator_list_names(self, template_dir):
        """Test listing job names."""
        generator = JobGenerator(
            template_path=Path(template_dir) / "test.job.j2",
            parameters={
                "mode": "grid",
                "values": {"learning_rate": [0.01, 0.1]},
            },
            slurm_defaults={"partition": "gpu", "time": "1:00:00"},
            job_name_pattern="job_lr{{ learning_rate }}",
        )
        names = generator.list_job_names()
        assert len(names) == 2
        assert "job_lr0.01" in names
        assert "job_lr0.1" in names

    def test_generator_from_spec_with_filter(self, template_dir):
        """Test generator from spec resolves filter file path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            spec_path = Path(tmpdir) / "spec.yaml"
            filter_path = Path(tmpdir) / "params_filter.py"
            filter_path.write_text(
                "def include_params(params):\n"
                "    return params.get('learning_rate') == 0.1\n"
            )

            spec_data = {
                "template": str(Path(template_dir) / "test.job.j2"),
                "parameters": {
                    "mode": "grid",
                    "values": {"learning_rate": [0.01, 0.1]},
                    "filter": {"file": "params_filter.py"},
                },
                "slurm_args": {"defaults": {"partition": "gpu", "time": "1:00:00"}},
            }
            with open(spec_path, "w") as f:
                yaml.dump(spec_data, f)

            generator = JobGenerator.from_spec(spec_path)
            assert generator.count_jobs() == 1

    def test_generator_preview(self, template_dir):
        """Test previewing a generated job."""
        generator = JobGenerator(
            template_path=Path(template_dir) / "test.job.j2",
            parameters={
                "mode": "grid",
                "values": {"learning_rate": [0.01], "batch_size": [32]},
            },
            slurm_defaults={"partition": "gpu", "time": "1:00:00"},
        )
        preview = generator.preview(0)
        assert "#!/bin/bash" in preview
        assert "--partition=gpu" in preview
        assert "Learning rate: 0.01" in preview

    def test_generator_generate(self, template_dir):
        """Test generating job scripts."""
        with tempfile.TemporaryDirectory() as output_dir:
            generator = JobGenerator(
                template_path=Path(template_dir) / "test.job.j2",
                parameters={
                    "mode": "grid",
                    "values": {"learning_rate": [0.01, 0.1], "batch_size": [32]},
                },
                slurm_defaults={"partition": "gpu", "time": "1:00:00"},
                job_name_pattern="job_lr{{ learning_rate }}",
            )

            result = generator.generate(output_dir)

            assert len(result) == 2
            assert (Path(output_dir) / "job_lr0.01.job").exists()
            assert (Path(output_dir) / "job_lr0.1.job").exists()

    def test_generator_dry_run(self, template_dir):
        """Test dry run mode."""
        with tempfile.TemporaryDirectory() as output_dir:
            generator = JobGenerator(
                template_path=Path(template_dir) / "test.job.j2",
                parameters={"mode": "grid", "values": {"learning_rate": [0.01]}},
                slurm_defaults={"partition": "gpu", "time": "1:00:00"},
            )

            result = generator.generate(output_dir, dry_run=True)

            assert len(result) == 1
            # Files should not be created in dry run
            assert not any(Path(output_dir).iterdir())


class TestLoadJobSpec:
    """Tests for load_job_spec function."""

    def test_load_valid_spec(self):
        """Test loading a valid job spec."""
        with tempfile.TemporaryDirectory() as tmpdir:
            spec_path = Path(tmpdir) / "spec.yaml"
            spec_data = {
                "name": "test_experiment",
                "template": "template.j2",
                "parameters": {
                    "mode": "grid",
                    "values": {"lr": [0.01, 0.1]},
                },
            }
            with open(spec_path, "w") as f:
                yaml.dump(spec_data, f)

            loaded = load_job_spec(spec_path)
            assert loaded["name"] == "test_experiment"
            assert loaded["parameters"]["mode"] == "grid"

    def test_load_nonexistent_raises(self):
        """Test loading nonexistent file raises error."""
        with pytest.raises(FileNotFoundError):
            load_job_spec("/nonexistent/path.yaml")
