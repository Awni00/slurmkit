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
    make_unique_job_name,
)
from slurmkit.collections import Collection


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

    def test_grid_mode_with_filter_compact_spec(self):
        """Test parameter expansion with compact FILE:FUNCTION filter syntax."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filter_path = Path(tmpdir) / "filter.py"
            filter_path.write_text(
                "def keep_only_two(params):\n"
                "    return params.get('a') == 2\n"
            )

            spec = {
                "mode": "grid",
                "values": {"a": [1, 2], "b": ["x"]},
                "filter": f"{filter_path}:keep_only_two",
            }

            result = expand_parameters(spec)
            assert result == [{"a": 2, "b": "x"}]

    def test_grid_mode_with_parse_compact_spec(self):
        """Test parameter expansion with compact FILE:FUNCTION parse syntax."""
        with tempfile.TemporaryDirectory() as tmpdir:
            parse_path = Path(tmpdir) / "parse.py"
            parse_path.write_text(
                "def parse_params(params):\n"
                "    parsed = dict(params)\n"
                "    parsed['tag'] = f\"a{params['a']}\"\n"
                "    return parsed\n"
            )

            spec = {
                "mode": "grid",
                "values": {"a": [1, 2]},
                "parse": f"{parse_path}:parse_params",
            }

            result = expand_parameters(spec)
            assert result == [{"a": 1, "tag": "a1"}, {"a": 2, "tag": "a2"}]

    def test_list_mode_with_parse_compact_spec(self):
        """Test parameter parsing in list mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            parse_path = Path(tmpdir) / "parse.py"
            parse_path.write_text(
                "def parse_params(params):\n"
                "    return {'value': params['value'], 'double': params['value'] * 2}\n"
            )

            spec = {
                "mode": "list",
                "values": [{"value": 2}, {"value": 4}],
                "parse": f"{parse_path}:parse_params",
            }

            result = expand_parameters(spec)
            assert result == [
                {"value": 2, "double": 4},
                {"value": 4, "double": 8},
            ]

    def test_list_mode_with_parse_expansion(self):
        """Test parse can expand a single list entry into multiple jobs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            parse_path = Path(tmpdir) / "parse.py"
            parse_path.write_text(
                "def parse_params(params):\n"
                "    return [\n"
                "        {'n_trials': params['n_trials'], 'seed': seed}\n"
                "        for seed in range(params['n_trials'])\n"
                "    ]\n"
            )

            spec = {
                "mode": "list",
                "values": [{"n_trials": 3}],
                "parse": f"{parse_path}:parse_params",
            }

            result = expand_parameters(spec)
            assert result == [
                {"n_trials": 3, "seed": 0},
                {"n_trials": 3, "seed": 1},
                {"n_trials": 3, "seed": 2},
            ]

    def test_parse_empty_list_drops_source_entry(self):
        """Test empty parse expansions drop the source entry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            parse_path = Path(tmpdir) / "parse.py"
            parse_path.write_text(
                "def parse_params(params):\n"
                "    return []\n"
            )

            spec = {
                "mode": "grid",
                "values": {"a": [1, 2]},
                "parse": f"{parse_path}:parse_params",
            }

            result = expand_parameters(spec)
            assert result == []

    def test_grid_mode_parses_before_filter(self):
        """Test parsed fields are available to the filter callback."""
        with tempfile.TemporaryDirectory() as tmpdir:
            parse_path = Path(tmpdir) / "parse.py"
            filter_path = Path(tmpdir) / "filter.py"
            parse_path.write_text(
                "def parse_params(params):\n"
                "    parsed = dict(params)\n"
                "    parsed['kind'] = 'keep' if params['a'] == 2 else 'drop'\n"
                "    return parsed\n"
            )
            filter_path.write_text(
                "def include_params(params):\n"
                "    return params.get('kind') == 'keep'\n"
            )

            spec = {
                "mode": "grid",
                "values": {"a": [1, 2]},
                "parse": f"{parse_path}:parse_params",
                "filter": f"{filter_path}:include_params",
            }

            result = expand_parameters(spec)
            assert result == [{"a": 2, "kind": "keep"}]

    def test_grid_mode_filters_each_parse_child(self):
        """Test filtering applies independently to each parsed child."""
        with tempfile.TemporaryDirectory() as tmpdir:
            parse_path = Path(tmpdir) / "parse.py"
            filter_path = Path(tmpdir) / "filter.py"
            parse_path.write_text(
                "def parse_params(params):\n"
                "    return [\n"
                "        {'trial': 0, 'keep': False},\n"
                "        {'trial': 1, 'keep': True},\n"
                "    ]\n"
            )
            filter_path.write_text(
                "def include_params(params):\n"
                "    return params['keep']\n"
            )

            spec = {
                "mode": "grid",
                "values": {"a": [1]},
                "parse": f"{parse_path}:parse_params",
                "filter": f"{filter_path}:include_params",
            }

            result = expand_parameters(spec)
            assert result == [{"trial": 1, "keep": True}]


def test_make_unique_job_name_appends_numeric_suffix():
    """Duplicate job names should be disambiguated with -N suffixes."""
    assert make_unique_job_name("train", {"train"}) == "train-2"
    assert make_unique_job_name("train", {"train", "train-2"}) == "train-3"


def test_job_generator_plan_and_dry_run_are_append_only(tmp_path):
    """Planning/dry-run should respect collection append mode without mutating it."""
    template = tmp_path / "train.job.j2"
    template.write_text("#!/bin/bash\necho {{ job_name }}\n", encoding="utf-8")
    output_dir = tmp_path / "jobs"

    collection = Collection("exp1")
    collection.add_job(job_name="job", script_path=str(tmp_path / "job.job"))

    generator = JobGenerator(
        template_path=template,
        parameters={"mode": "list", "values": [{"seed": 1}, {"seed": 2}]},
        job_name_pattern="job",
    )

    plan = generator.plan(output_dir=output_dir, collection=collection)
    assert [item["job_name"] for item in plan] == ["job-2", "job-3"]

    generated = generator.generate(output_dir=output_dir, collection=collection, dry_run=True)
    assert [item["job_name"] for item in generated] == ["job-2", "job-3"]
    assert len(collection.jobs) == 1

    def test_parse_mode_requires_mapping_or_list_return(self):
        """Test parameter parsing rejects non-dict/list returns."""
        with tempfile.TemporaryDirectory() as tmpdir:
            parse_path = Path(tmpdir) / "parse.py"
            parse_path.write_text(
                "def parse_params(params):\n"
                "    return None\n"
            )

            spec = {
                "mode": "grid",
                "values": {"a": [1]},
                "parse": f"{parse_path}:parse_params",
            }

            with pytest.raises(TypeError, match="mapping or list of mappings"):
                expand_parameters(spec)

    def test_parse_mode_requires_list_items_to_be_mappings(self):
        """Test parameter parsing rejects list outputs with non-dict items."""
        with tempfile.TemporaryDirectory() as tmpdir:
            parse_path = Path(tmpdir) / "parse.py"
            parse_path.write_text(
                "def parse_params(params):\n"
                "    return [{'a': 1}, 'bad']\n"
            )

            spec = {
                "mode": "grid",
                "values": {"a": [1]},
                "parse": f"{parse_path}:parse_params",
            }

            with pytest.raises(TypeError, match="lists must contain only mappings"):
                expand_parameters(spec)

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
                "job_subdir": "spec_jobs/filter_case",
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

    def test_generator_from_spec_with_parse_relative_path(self, template_dir):
        """Test generator from spec resolves parse file path and uses parsed params."""
        with tempfile.TemporaryDirectory() as tmpdir:
            spec_path = Path(tmpdir) / "spec.yaml"
            parse_path = Path(tmpdir) / "parse_params.py"
            filter_path = Path(tmpdir) / "params_filter.py"
            logic_path = Path(tmpdir) / "slurm_logic.py"
            parse_path.write_text(
                "def parse_params(params):\n"
                "    parsed = dict(params)\n"
                "    parsed['batch_size'] = 128\n"
                "    parsed['tag'] = f\"parsed_{params['learning_rate']}\"\n"
                "    return parsed\n"
            )
            filter_path.write_text(
                "def include_params(params):\n"
                "    return params.get('tag') == 'parsed_0.1'\n"
            )
            logic_path.write_text(
                "def choose_slurm(params, defaults):\n"
                "    args = defaults.copy()\n"
                "    args['partition'] = 'parsed' if params.get('batch_size') == 128 else 'gpu'\n"
                "    return args\n"
            )

            spec_data = {
                "template": str(Path(template_dir) / "test.job.j2"),
                "job_subdir": "spec_jobs/parse_case",
                "parameters": {
                    "mode": "grid",
                    "values": {"learning_rate": [0.01, 0.1], "batch_size": [32]},
                    "parse": "parse_params.py:parse_params",
                    "filter": "params_filter.py:include_params",
                },
                "slurm_args": {
                    "defaults": {"partition": "gpu", "time": "1:00:00"},
                    "logic": "slurm_logic.py:choose_slurm",
                },
                "job_name_pattern": "job_{{ tag }}",
            }
            with open(spec_path, "w") as f:
                yaml.dump(spec_data, f)

            generator = JobGenerator.from_spec(spec_path)
            assert generator.count_jobs() == 1
            assert generator.list_job_names() == ["job_parsed_0.1"]
            preview = generator.preview(0)
            assert "--partition=parsed" in preview
            assert "Learning rate: 0.1" in preview
            assert "Batch size: 128" in preview

    def test_generator_parse_expansion_updates_count_names_and_preview(self, template_dir):
        """Test parse expansion is reflected throughout generation helpers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            spec_path = Path(tmpdir) / "spec.yaml"
            parse_path = Path(tmpdir) / "params_logic.py"
            parse_path.write_text(
                "def parse_params(params):\n"
                "    return [\n"
                "        {\n"
                "            'learning_rate': params['learning_rate'],\n"
                "            'batch_size': params['batch_size'],\n"
                "            'seed': seed,\n"
                "            'trial_name': f\"trial_{seed}\",\n"
                "        }\n"
                "        for seed in range(2)\n"
                "    ]\n"
            )
            spec_data = {
                "template": str(Path(template_dir) / "test.job.j2"),
                "job_subdir": "spec_jobs/parse_expand_case",
                "parameters": {
                    "mode": "list",
                    "values": [{"learning_rate": 0.1, "batch_size": 32}],
                    "parse": "params_logic.py:parse_params",
                },
                "slurm_args": {"defaults": {"partition": "gpu", "time": "1:00:00"}},
                "job_name_pattern": "{{ trial_name }}",
            }
            with open(spec_path, "w") as f:
                yaml.dump(spec_data, f)

            generator = JobGenerator.from_spec(spec_path)
            assert generator.count_jobs() == 2
            assert generator.list_job_names() == ["trial_0", "trial_1"]
            preview = generator.preview(1)
            assert "Learning rate: 0.1" in preview
            assert "Batch size: 32" in preview

    def test_generator_from_spec_with_compact_callback_specs(self, template_dir):
        """Test compact FILE:FUNCTION specs for both filter and SLURM logic."""
        with tempfile.TemporaryDirectory() as tmpdir:
            spec_path = Path(tmpdir) / "spec.yaml"
            filter_path = Path(tmpdir) / "params_filter.py"
            logic_path = Path(tmpdir) / "slurm_logic.py"
            filter_path.write_text(
                "def keep_high_lr(params):\n"
                "    return params.get('learning_rate') == 0.1\n"
            )
            logic_path.write_text(
                "def choose_slurm(params, defaults):\n"
                "    args = defaults.copy()\n"
                "    args['partition'] = 'high_lr'\n"
                "    return args\n"
            )

            spec_data = {
                "template": str(Path(template_dir) / "test.job.j2"),
                "job_subdir": "spec_jobs/compact_case",
                "parameters": {
                    "mode": "grid",
                    "values": {"learning_rate": [0.01, 0.1], "batch_size": [32]},
                    "filter": "params_filter.py:keep_high_lr",
                },
                "slurm_args": {
                    "defaults": {"partition": "gpu", "time": "1:00:00"},
                    "logic": "slurm_logic.py:choose_slurm",
                },
            }
            with open(spec_path, "w") as f:
                yaml.dump(spec_data, f)

            generator = JobGenerator.from_spec(spec_path)
            assert generator.count_jobs() == 1
            preview = generator.preview(0)
            assert "--partition=high_lr" in preview

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

    def test_generator_generate_one(self, template_dir):
        """Test generating a single script from explicit params + job name."""
        with tempfile.TemporaryDirectory() as output_dir:
            generator = JobGenerator(
                template_path=Path(template_dir) / "test.job.j2",
                parameters={"mode": "list", "values": []},
                slurm_defaults={"partition": "gpu", "time": "1:00:00"},
            )
            result = generator.generate_one(
                output_dir=output_dir,
                params={"learning_rate": 0.02, "batch_size": 16},
                job_name="custom.resubmit-1",
            )

            assert result["job_name"] == "custom.resubmit-1"
            assert result["script_path"].name == "custom.resubmit-1.job"
            assert result["script_path"].exists()
            content = result["script_path"].read_text()
            assert "Learning rate: 0.02" in content
            assert "Batch size: 16" in content

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
