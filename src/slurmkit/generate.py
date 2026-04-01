"""
Job generation from templates and parameter specifications.

This module provides utilities for generating SLURM job scripts from:
- Jinja2 templates
- Parameter grids (all combinations) or explicit parameter lists
- Optional Python functions for dynamic SLURM argument logic

The generated scripts can be automatically added to collections for tracking.
"""

from __future__ import annotations

import importlib.util
import itertools
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Mapping, Optional, Tuple, Union

import yaml
from jinja2 import Environment, FileSystemLoader, Template

from slurmkit.config import JOB_LOGS_SUBDIR, JOB_SCRIPTS_SUBDIR, Config, get_config
from slurmkit.collections import Collection, CollectionManager
from slurmkit.spec_interpolation import build_job_subdir_context, render_spec_string


# =============================================================================
# Parameter Expansion
# =============================================================================

def expand_grid(
    params: Dict[str, List[Any]],
    filter_func: Optional[Callable[[Dict[str, Any]], bool]] = None,
) -> Iterator[Dict[str, Any]]:
    """
    Expand a parameter grid into all combinations.

    Takes a dictionary where values are lists and yields all
    combinations as individual dictionaries.

    Args:
        params: Dictionary mapping parameter names to lists of values.
        filter_func: Optional predicate to include/exclude combinations.
            If provided, only combinations where filter_func(params) is True
            are yielded.

    Yields:
        Dictionary for each combination of parameter values.

    Example:
        >>> list(expand_grid({"a": [1, 2], "b": ["x", "y"]}))
        [{'a': 1, 'b': 'x'}, {'a': 1, 'b': 'y'}, {'a': 2, 'b': 'x'}, {'a': 2, 'b': 'y'}]
    """
    if not params:
        yield {}
        return

    keys = list(params.keys())
    values = [params[k] if isinstance(params[k], list) else [params[k]] for k in keys]

    for combo in itertools.product(*values):
        combo_dict = dict(zip(keys, combo))
        if filter_func is not None and not filter_func(combo_dict):
            continue
        yield combo_dict


def expand_parameters(
    spec: Dict[str, Any],
    filter_func: Optional[Callable[[Dict[str, Any]], bool]] = None,
    parse_func: Optional[Callable[[Dict[str, Any]], Union[Dict[str, Any], List[Dict[str, Any]]]]] = None,
) -> List[Dict[str, Any]]:
    """
    Expand a parameter specification into a list of parameter dicts.

    Supports two modes:
    - "grid": All combinations of parameter values
    - "list": Explicit list of parameter dictionaries

    Args:
        spec: Parameter specification with "mode" and "values" keys.
            mode: "grid" or "list"
            values: For grid mode, dict of param_name -> list of values.
                    For list mode, list of param dicts.
        filter_func: Optional predicate for grid mode to include/exclude
            combinations.
        parse_func: Optional callback to derive effective parameters for each
            generated job before filtering and rendering. The callback may
            return a single dict or a list of dicts.

    Returns:
        List of parameter dictionaries.

    Example:
        >>> spec = {"mode": "grid", "values": {"lr": [0.01, 0.1], "bs": [32]}}
        >>> expand_parameters(spec)
        [{'lr': 0.01, 'bs': 32}, {'lr': 0.1, 'bs': 32}]

        >>> spec = {"mode": "list", "values": [{"lr": 0.01}, {"lr": 0.1}]}
        >>> expand_parameters(spec)
        [{'lr': 0.01}, {'lr': 0.1}]
    """
    mode = spec.get("mode", "grid")
    values = spec.get("values", {})

    if parse_func is None:
        parse_spec = spec.get("parse")
        if callable(parse_spec):
            parse_func = parse_spec
        else:
            parsed_parse = parse_python_file_function_spec(
                parse_spec,
                default_function="parse_params",
                spec_label="Parameter parser",
            )
            if parsed_parse is not None:
                parse_func = load_param_parse_function(
                    parsed_parse["file"],
                    parsed_parse["function"],
                )

    if mode == "list":
        param_list = values if isinstance(values, list) else [values]
        expanded = []
        for params in param_list:
            expanded.extend(normalize_param_parse_output(params, parse_func))
        return expanded

    elif mode == "grid":
        if filter_func is None:
            filter_spec = spec.get("filter")
            if callable(filter_spec):
                filter_func = filter_spec
            else:
                parsed_filter = parse_python_file_function_spec(
                    filter_spec,
                    default_function="include_params",
                    spec_label="Parameter filter",
                )
                if parsed_filter is not None:
                    filter_func = load_param_filter_function(
                        parsed_filter["file"],
                        parsed_filter["function"],
                    )
        expanded = []
        for params in expand_grid(values):
            parsed_params = normalize_param_parse_output(params, parse_func)
            for effective_params in parsed_params:
                if filter_func is not None and not filter_func(effective_params):
                    continue
                expanded.append(effective_params)
        return expanded

    else:
        raise ValueError(f"Unknown parameter mode: {mode}. Use 'grid' or 'list'.")


# =============================================================================
# Parameter Parser / Filter Logic
# =============================================================================

def normalize_param_parse_output(
    params: Dict[str, Any],
    parse_func: Optional[Callable[[Dict[str, Any]], Union[Dict[str, Any], List[Dict[str, Any]]]]],
) -> List[Dict[str, Any]]:
    """Apply the parameter parser and normalize its output to a list."""
    if parse_func is None:
        return [params]

    if not isinstance(params, dict):
        raise TypeError(
            "Parameter parser requires each parameter entry to be a mapping, "
            f"got {type(params).__name__}."
        )

    parsed = parse_func(dict(params))
    if isinstance(parsed, dict):
        return [dict(parsed)]

    if not isinstance(parsed, list):
        raise TypeError(
            "Parameter parser must return a mapping or list of mappings, "
            f"got {type(parsed).__name__}."
        )

    normalized = []
    for item in parsed:
        if not isinstance(item, dict):
            raise TypeError(
                "Parameter parser lists must contain only mappings, "
                f"got {type(item).__name__}."
            )
        normalized.append(dict(item))

    return normalized


def parse_python_file_function_spec(
    spec: Any,
    *,
    default_function: str,
    spec_label: str,
) -> Optional[Dict[str, str]]:
    """
    Parse callback spec for python-file-backed functions.

    Accepts ``path.py:function_name`` or a bare ``path.py``. A bare path uses
    the provided default function. A mapping with ``file`` and optional
    ``function`` is also accepted as the normalized in-memory representation.
    """
    if spec is None:
        return None

    if isinstance(spec, str):
        normalized = spec.strip()
        if not normalized:
            return None
        if ":" in normalized:
            file_path, function_name = normalized.rsplit(":", 1)
            if not file_path.strip() or not function_name.strip():
                raise ValueError(
                    f"{spec_label} must use 'path.py:function_name' or 'path.py' format."
                )
            return {
                "file": file_path.strip(),
                "function": function_name.strip(),
            }
        return {"file": normalized, "function": default_function}

    if not isinstance(spec, dict):
        raise ValueError(
            f"{spec_label} must use 'path.py:function_name', 'path.py', or a mapping with 'file'."
        )

    file_path = str(spec.get("file", "")).strip()
    if not file_path:
        return None

    function_name = str(spec.get("function", default_function)).strip() or default_function
    return {"file": file_path, "function": function_name}


def resolve_job_subdir(
    spec: Dict[str, Any],
    *,
    interpolation_context: Optional[Mapping[str, Any]] = None,
) -> str:
    """Return the validated relative jobs subdirectory for a spec."""
    job_subdir_raw = spec.get("job_subdir")
    if not job_subdir_raw:
        raise ValueError("Job spec is missing required field 'job_subdir'.")

    rendered_subdir = render_spec_string(
        job_subdir_raw,
        field_name="job_subdir",
        context=interpolation_context or {},
    )
    job_subdir = Path(rendered_subdir)
    if job_subdir.is_absolute():
        raise ValueError("Job spec field 'job_subdir' must be relative.")
    if ".." in job_subdir.parts:
        raise ValueError("Job spec field 'job_subdir' cannot contain '..'.")
    return job_subdir.as_posix()


def resolve_spec_job_paths(
    spec: Dict[str, Any],
    config: Config,
    *,
    interpolation_context: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Path | str]:
    """Resolve canonical scripts/logs paths for a spec from config `jobs_dir`."""
    jobs_dir = config.get_path("jobs_dir")
    if jobs_dir is None:
        raise ValueError("Config is missing 'jobs_dir'.")

    job_subdir = resolve_job_subdir(spec, interpolation_context=interpolation_context)
    job_dir = jobs_dir / Path(job_subdir)
    return {
        "job_subdir": job_subdir,
        "job_dir": job_dir,
        "scripts_dir": job_dir / JOB_SCRIPTS_SUBDIR,
        "logs_dir": job_dir / JOB_LOGS_SUBDIR,
    }


def resolve_python_file_function_spec(
    spec: Any,
    *,
    base_dir: Union[str, Path],
    default_function: str,
    spec_label: str,
) -> Optional[Dict[str, str]]:
    """Resolve relative callback file paths against ``base_dir``."""
    parsed = parse_python_file_function_spec(
        spec,
        default_function=default_function,
        spec_label=spec_label,
    )
    if parsed is None:
        return None

    file_path = Path(parsed["file"])
    if not file_path.is_absolute():
        file_path = Path(base_dir) / file_path

    return {
        "file": str(file_path),
        "function": parsed["function"],
    }


def load_param_parse_function(
    file_path: Union[str, Path],
    function_name: str = "parse_params",
) -> Callable[[Dict[str, Any]], Union[Dict[str, Any], List[Dict[str, Any]]]]:
    """
    Load a Python function for deriving effective job parameters.

    The function should have signature:
        def parse_params(params: dict) -> dict | list[dict]
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"Parameter parser file not found: {file_path}")

    spec = importlib.util.spec_from_file_location("param_parse_module", file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module from {file_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules["param_parse_module"] = module
    spec.loader.exec_module(module)

    if not hasattr(module, function_name):
        raise AttributeError(
            f"Function '{function_name}' not found in {file_path}"
        )

    return getattr(module, function_name)


def load_param_filter_function(
    file_path: Union[str, Path],
    function_name: str = "include_params",
) -> Callable[[Dict[str, Any]], bool]:
    """
    Load a Python function for filtering parameter combinations.

    The function should have signature:
        def include_params(params: dict) -> bool

    Args:
        file_path: Path to the Python file.
        function_name: Name of the function to load.

    Returns:
        The loaded function.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        AttributeError: If the function isn't found in the file.
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"Parameter filter file not found: {file_path}")

    # Load the module dynamically
    spec = importlib.util.spec_from_file_location("param_filter_module", file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module from {file_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules["param_filter_module"] = module
    spec.loader.exec_module(module)

    # Get the function
    if not hasattr(module, function_name):
        raise AttributeError(
            f"Function '{function_name}' not found in {file_path}"
        )

    return getattr(module, function_name)


def resolve_parameters_callback_specs(
    parameters: Dict[str, Any],
    base_dir: Union[str, Path],
) -> Dict[str, Any]:
    """
    Resolve filter and parse file paths in a parameter spec relative to base_dir.

    Returns a shallow-copied spec without mutating the input.
    """
    if not isinstance(parameters, dict):
        return parameters

    resolved = parameters.copy()
    changed = False

    for key, default_function, spec_label in (
        ("parse", "parse_params", "Parameter parser"),
        ("filter", "include_params", "Parameter filter"),
    ):
        callback_spec = parameters.get(key)
        if callable(callback_spec):
            continue

        resolved_callback = resolve_python_file_function_spec(
            callback_spec,
            base_dir=base_dir,
            default_function=default_function,
            spec_label=spec_label,
        )
        if resolved_callback is None:
            continue
        resolved[key] = resolved_callback
        changed = True

    if not changed:
        return parameters

    return resolved


def resolve_parameters_filter_spec(
    parameters: Dict[str, Any],
    base_dir: Union[str, Path],
) -> Dict[str, Any]:
    """Backward-compatible wrapper for parameter callback path resolution."""
    return resolve_parameters_callback_specs(parameters, base_dir)


# =============================================================================
# SLURM Arguments Logic
# =============================================================================

def load_slurm_args_function(
    file_path: Union[str, Path],
    function_name: str = "get_slurm_args",
) -> Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]:
    """
    Load a Python function for computing SLURM arguments.

    The function should have signature:
        def get_slurm_args(params: dict, defaults: dict) -> dict

    Args:
        file_path: Path to the Python file.
        function_name: Name of the function to load.

    Returns:
        The loaded function.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        AttributeError: If the function isn't found in the file.
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"SLURM args file not found: {file_path}")

    # Load the module dynamically
    spec = importlib.util.spec_from_file_location("slurm_args_module", file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module from {file_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules["slurm_args_module"] = module
    spec.loader.exec_module(module)

    # Get the function
    if not hasattr(module, function_name):
        raise AttributeError(
            f"Function '{function_name}' not found in {file_path}"
        )

    return getattr(module, function_name)


def compute_slurm_args(
    params: Dict[str, Any],
    defaults: Dict[str, Any],
    logic_func: Optional[Callable] = None,
) -> Dict[str, Any]:
    """
    Compute SLURM arguments for a job.

    If a logic function is provided, it is called to customize the arguments.
    Otherwise, defaults are returned unchanged.

    Args:
        params: Job parameters.
        defaults: Default SLURM arguments.
        logic_func: Optional function to customize arguments.

    Returns:
        Final SLURM arguments dictionary.
    """
    if logic_func is None:
        return defaults.copy()

    return logic_func(params, defaults.copy())


# =============================================================================
# Job Name Generation
# =============================================================================

def generate_job_name(
    params: Dict[str, Any],
    pattern: Optional[str] = None,
    env: Optional[Environment] = None,
) -> str:
    """
    Generate a job name from parameters.

    Uses a Jinja2 pattern to format the job name from parameter values.

    Args:
        params: Job parameters.
        pattern: Jinja2 pattern for job name. If None, uses param values joined by underscores.
        env: Jinja2 environment. If None, creates a new one.

    Returns:
        Generated job name.

    Example:
        >>> generate_job_name({"model": "resnet", "lr": 0.01}, "{{ model }}_lr{{ lr }}")
        'resnet_lr0.01'
    """
    if pattern is None:
        # Default: join param values with underscores
        parts = [f"{k}{v}" for k, v in sorted(params.items())]
        return "_".join(parts)

    if env is None:
        env = Environment()

    template = env.from_string(pattern)
    return template.render(**params)


def make_unique_job_name(job_name: str, existing_names: Iterable[str]) -> str:
    """
    Make a generated job name unique by appending ``-N`` when needed.

    Args:
        job_name: Base generated job name.
        existing_names: Already-reserved names in the target collection/plan.

    Returns:
        Unique job name.
    """
    taken = set(existing_names)
    if job_name not in taken:
        return job_name

    suffix = 2
    while True:
        candidate = f"{job_name}-{suffix}"
        if candidate not in taken:
            return candidate
        suffix += 1


# =============================================================================
# Job Spec Loading
# =============================================================================

def load_job_spec(spec_path: Union[str, Path]) -> Dict[str, Any]:
    """
    Load a job specification from a YAML file.

    Args:
        spec_path: Path to the job spec YAML file.

    Returns:
        Parsed job specification dictionary.

    Raises:
        FileNotFoundError: If the file doesn't exist.
    """
    spec_path = Path(spec_path)

    if not spec_path.exists():
        raise FileNotFoundError(f"Job spec not found: {spec_path}")

    with open(spec_path, "r") as f:
        spec = yaml.safe_load(f) or {}

    return spec


def render_job_spec_template(
    *,
    config: Optional[Config] = None,
    job_subdir_example: str = "experiments/my_experiment",
) -> str:
    """
    Render a starter job spec template with practical defaults and hints.

    Args:
        config: Optional config used to display jobs_dir-derived path hints.
        job_subdir_example: Example relative job_subdir shown in the template.

    Returns:
        YAML template content with explanatory comments.
    """
    if config is None:
        config = get_config()

    jobs_dir_value = str(config.get("jobs_dir", ".jobs/"))
    jobs_root = Path(jobs_dir_value)
    scripts_hint = (jobs_root / job_subdir_example / JOB_SCRIPTS_SUBDIR).as_posix()
    logs_hint = (jobs_root / job_subdir_example / JOB_LOGS_SUBDIR).as_posix()

    template = f"""# slurmkit job spec template
# Fill in values, then run:
#   slurmkit generate job_spec.yaml --into my_experiment
#
# Using jobs_dir from config ({jobs_dir_value!r}), this spec would write:
#   scripts: {scripts_hint}
#   logs:    {logs_hint}

name: my_experiment
description: "Short description of this run"

# Path to Jinja2 template for rendering job scripts.
# Can be absolute or relative to this spec file.
template: template.job.j2
job_subdir: {job_subdir_example}

# Optional: template `job_subdir` with built-ins and variables.
# Built-ins: collection_name, collection_slug, spec_name, spec_stem, spec_dir.
# Example:
# job_subdir: experiments/{{{{ collection_slug }}}}/{{{{ vars.stage }}}}
#
# Optional variables available as vars.<key> in templated fields:
# variables:
#   stage: baseline

parameters:
  mode: grid
  values:
    learning_rate: [0.001, 0.01]
    batch_size: [32, 64]

  # Optional advanced hooks:
  # parse: params_logic.py:parse_params
  # A callback to parse/update parameters for each generated job. Takes params dict and returns updated dict or list of dicts.

  # filter: params_logic.py:include_params
  # A callback to filter parameter combinations in grid mode. Should return True to include a combination, False to exclude.

  # Optional alternative: explicit list mode
  # mode: list
  # values:
  #   - learning_rate: 0.001
  #     batch_size: 32
  #   - learning_rate: 0.01
  #     batch_size: 64

slurm_args:
  defaults:
    # partition: compute
    time: "24:00:00"
    mem: "16G"
    nodes: 1
    ntasks: 1
    cpus_per_task: 1

  # Optional advanced hook to programmatically customize SLURM arguments based on parameters or other logic
  # logic: slurm_logic.py:get_slurm_args

# Optional Jinja2 pattern for job names. Can use any parameter keys as variables.
job_name_pattern: "exp_{{{{ learning_rate }}}}_bs{{{{ batch_size }}}}"

# Optional collection-level notification overrides:
# notifications:
#   defaults:
#     output_tail_lines: 20
#   job:
#     ai:
#       enabled: true
#       callback: "utilities.slurmkit.ai_callbacks:summarize_job_payload"
#   collection_final:
#     ai:
#       enabled: true
#       callback: "utilities.slurmkit.ai_callbacks:summarize_collection_report"
"""
    return template


# =============================================================================
# Job Generator Class
# =============================================================================

class JobGenerator:
    """
    Generator for SLURM job scripts from templates and parameters.

    The generator combines:
    - Jinja2 templates for job script structure
    - Parameter grids or lists for job variations
    - Optional Python logic for SLURM argument customization
    - Collection integration for tracking generated jobs

    Example:
        >>> generator = JobGenerator(
        ...     template_path="templates/train.job.j2",
        ...     parameters={"mode": "grid", "values": {"lr": [0.01, 0.1]}},
        ...     slurm_defaults={"partition": "gpu", "time": "24:00:00"},
        ... )
        >>> scripts = generator.generate(output_dir="jobs/exp1/job_scripts")
    """

    def __init__(
        self,
        template_path: Union[str, Path],
        parameters: Dict[str, Any],
        slurm_defaults: Optional[Dict[str, Any]] = None,
        slurm_logic_file: Optional[Union[str, Path]] = None,
        slurm_logic_function: str = "get_slurm_args",
        job_name_pattern: Optional[str] = None,
        logs_dir: Optional[Union[str, Path]] = None,
        config: Optional[Config] = None,
    ):
        """
        Initialize the job generator.

        Args:
            template_path: Path to the Jinja2 template file.
            parameters: Parameter specification (mode + values).
            slurm_defaults: Default SLURM arguments.
            slurm_logic_file: Path to Python file with SLURM args function.
            slurm_logic_function: Name of the function in slurm_logic_file.
            job_name_pattern: Jinja2 pattern for job names.
            logs_dir: Directory for job output files (used in templates).
            config: Configuration object.
        """
        if config is None:
            config = get_config()

        self.config = config
        self.template_path = Path(template_path)
        self.parameters = parameters
        self.job_name_pattern = job_name_pattern
        self.logs_dir = Path(logs_dir) if logs_dir else None
        self.slurm_logic_file = Path(slurm_logic_file) if slurm_logic_file else None
        self.slurm_logic_function = slurm_logic_function

        # Parameter parse / filter logic (optional)
        self.param_parse_func = None
        if isinstance(self.parameters, dict):
            parse_spec = self.parameters.get("parse")
            if callable(parse_spec):
                self.param_parse_func = parse_spec
            else:
                parsed_parse = parse_python_file_function_spec(
                    parse_spec,
                    default_function="parse_params",
                    spec_label="Parameter parser",
                )
                if parsed_parse is not None:
                    self.param_parse_func = load_param_parse_function(
                        parsed_parse["file"],
                        parsed_parse["function"],
                    )

        self.param_filter_func = None
        if isinstance(self.parameters, dict) and self.parameters.get("mode", "grid") == "grid":
            filter_spec = self.parameters.get("filter")
            if callable(filter_spec):
                self.param_filter_func = filter_spec
            else:
                parsed_filter = parse_python_file_function_spec(
                    filter_spec,
                    default_function="include_params",
                    spec_label="Parameter filter",
                )
                if parsed_filter is not None:
                    self.param_filter_func = load_param_filter_function(
                        parsed_filter["file"],
                        parsed_filter["function"],
                    )

        # SLURM arguments - merge config defaults with job spec defaults
        # Config defaults provide the base, job spec defaults override
        self.slurm_defaults = config.get_slurm_defaults().copy()
        if slurm_defaults:
            self.slurm_defaults.update(slurm_defaults)
        self.slurm_logic_func = None

        if self.slurm_logic_file:
            self.slurm_logic_func = load_slurm_args_function(
                self.slurm_logic_file,
                self.slurm_logic_function,
            )

        # Set up Jinja2 environment
        template_dir = self.template_path.parent
        self._env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            keep_trailing_newline=True,
            trim_blocks=True,    # removes the first newline after a block tag
            lstrip_blocks=True,  # strips leading whitespace from block-tag lines
        )

    def _render_job(self, params: Dict[str, Any], job_name: str) -> Tuple[Dict[str, Any], str]:
        """
        Render a single job and return computed SLURM args + script content.

        Args:
            params: Effective parameters for the job.
            job_name: Final SLURM job name to inject into the template.

        Returns:
            Tuple of (slurm_args, rendered_content).
        """
        template = self._env.get_template(self.template_path.name)
        slurm_args = compute_slurm_args(
            params,
            self.slurm_defaults,
            self.slurm_logic_func,
        )
        context = {
            "job_name": job_name,
            "slurm": slurm_args,
            "logs_dir": str(self.logs_dir) if self.logs_dir else ".",
            "params": params,
            **params,
        }
        content = template.render(**context)
        return slurm_args, content

    def generate_one(
        self,
        output_dir: Union[str, Path],
        params: Dict[str, Any],
        job_name: str,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Generate one job script from explicit params and an explicit job name.

        Args:
            output_dir: Directory to write the generated script.
            params: Effective parameters to render with.
            job_name: Job name for file naming + template context.
            dry_run: If True, do not write the file.

        Returns:
            Job info dictionary containing job_name/script_path/parameters/slurm_args.
        """
        output_dir = Path(output_dir)
        if not dry_run:
            output_dir.mkdir(parents=True, exist_ok=True)

        slurm_args, content = self._render_job(params, job_name)
        script_path = output_dir / f"{job_name}.job"
        if not dry_run:
            script_path.write_text(content, encoding="utf-8")

        return {
            "job_name": job_name,
            "script_path": script_path,
            "parameters": params,
            "slurm_args": slurm_args,
        }

    def render_script(
        self,
        params: Dict[str, Any],
        job_name: str,
    ) -> str:
        """Render one script without writing it to disk."""
        _slurm_args, content = self._render_job(params, job_name)
        return content

    @classmethod
    def from_spec(
        cls,
        spec_path: Union[str, Path],
        config: Optional[Config] = None,
        collection_name: Optional[str] = None,
        interpolation_context: Optional[Mapping[str, Any]] = None,
    ) -> "JobGenerator":
        """
        Create a generator from a job spec file.

        Args:
            spec_path: Path to the job spec YAML file.
            config: Configuration object.
            collection_name: Optional collection name used in path interpolation.
            interpolation_context: Optional explicit interpolation context.

        Returns:
            Configured JobGenerator instance.
        """
        spec_path = Path(spec_path)
        spec = load_job_spec(spec_path)

        # Resolve template/callback paths relative to spec file.
        spec_dir = spec_path.parent

        template_path = spec.get("template", "")
        if not Path(template_path).is_absolute():
            template_path = spec_dir / template_path

        parameters = resolve_parameters_callback_specs(
            spec.get("parameters", {}),
            base_dir=spec_dir,
        )

        slurm_logic_file = None
        slurm_logic_function = "get_slurm_args"
        slurm_args = spec.get("slurm_args", {})

        logic_spec = resolve_python_file_function_spec(
            slurm_args.get("logic"),
            base_dir=spec_dir,
            default_function="get_slurm_args",
            spec_label="SLURM args logic",
        )
        if logic_spec is not None:
            slurm_logic_file = Path(logic_spec["file"])
            slurm_logic_function = logic_spec["function"]

        config = config or get_config()
        context = dict(interpolation_context or {})
        if not context:
            context = build_job_subdir_context(
                spec_data=spec,
                spec_path=spec_path,
                collection_name=collection_name,
                project_root=getattr(config, "project_root", None),
            )
        job_paths = resolve_spec_job_paths(spec, config, interpolation_context=context)

        return cls(
            template_path=template_path,
            parameters=parameters,
            slurm_defaults=slurm_args.get("defaults"),
            slurm_logic_file=slurm_logic_file,
            slurm_logic_function=slurm_logic_function,
            job_name_pattern=spec.get("job_name_pattern"),
            logs_dir=job_paths["logs_dir"],
            config=config,
        )

    def generate(
        self,
        output_dir: Union[str, Path],
        collection: Optional[Collection] = None,
        dry_run: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Generate job scripts.

        Args:
            output_dir: Directory to write generated scripts.
            collection: Collection to add generated jobs to.
            dry_run: If True, don't write files, just return what would be generated.

        Returns:
            List of generated job info dicts with keys:
            - job_name: Generated job name
            - script_path: Path to the script file
            - parameters: Job parameters
            - slurm_args: Computed SLURM arguments
        """
        generated = []
        for item in self.plan(output_dir=output_dir, collection=collection):
            job_info = self.generate_one(
                output_dir=output_dir,
                params=item["parameters"],
                job_name=item["job_name"],
                dry_run=dry_run,
            )

            generated.append(job_info)

            # Dry-run planning must not mutate the target collection.
            if collection is not None and not dry_run:
                collection.add_job(
                    job_name=item["job_name"],
                    script_path=job_info["script_path"],
                    parameters=item["parameters"],
                )

        return generated

    def plan(
        self,
        output_dir: Union[str, Path],
        collection: Optional[Collection] = None,
    ) -> List[Dict[str, Any]]:
        """
        Plan generated jobs without mutating the filesystem or collection.

        Args:
            output_dir: Directory where scripts will be written.
            collection: Optional target collection used for append-only naming.

        Returns:
            List of planned job entries with resolved unique names.
        """
        output_dir = Path(output_dir)

        param_list = expand_parameters(
            self.parameters,
            filter_func=self.param_filter_func,
            parse_func=self.param_parse_func,
        )

        used_names = set()
        if collection is not None:
            used_names.update(
                str(job.get("job_name"))
                for job in collection.jobs
                if job.get("job_name")
            )

        planned = []
        for params in param_list:
            base_job_name = generate_job_name(
                params,
                pattern=self.job_name_pattern,
                env=self._env,
            )
            job_name = make_unique_job_name(base_job_name, used_names)
            used_names.add(job_name)
            planned.append(
                {
                    "base_job_name": base_job_name,
                    "job_name": job_name,
                    "parameters": params,
                    "script_path": output_dir / f"{job_name}.job",
                }
            )

        return planned

    def preview(self, index: int = 0) -> str:
        """
        Preview a generated script without writing files.

        Args:
            index: Index of the parameter combination to preview.

        Returns:
            Rendered script content.
        """
        # Expand parameters
        param_list = expand_parameters(
            self.parameters,
            filter_func=self.param_filter_func,
            parse_func=self.param_parse_func,
        )

        if index >= len(param_list):
            raise IndexError(f"Index {index} out of range (max {len(param_list) - 1})")

        params = param_list[index]

        # Generate job name
        job_name = generate_job_name(
            params,
            pattern=self.job_name_pattern,
            env=self._env,
        )

        _, content = self._render_job(params=params, job_name=job_name)
        return content

    def count_jobs(self) -> int:
        """
        Count how many jobs would be generated.

        Returns:
            Number of parameter combinations.
        """
        return len(
            expand_parameters(
                self.parameters,
                filter_func=self.param_filter_func,
                parse_func=self.param_parse_func,
            )
        )

    def list_job_names(self) -> List[str]:
        """
        List all job names that would be generated.

        Returns:
            List of job names.
        """
        param_list = expand_parameters(
            self.parameters,
            filter_func=self.param_filter_func,
            parse_func=self.param_parse_func,
        )
        return [
            generate_job_name(params, pattern=self.job_name_pattern, env=self._env)
            for params in param_list
        ]


# =============================================================================
# Convenience Functions
# =============================================================================

def generate_jobs(
    template_path: Union[str, Path],
    parameters: Dict[str, Any],
    output_dir: Union[str, Path],
    slurm_defaults: Optional[Dict[str, Any]] = None,
    slurm_logic_file: Optional[Union[str, Path]] = None,
    job_name_pattern: Optional[str] = None,
    collection_name: Optional[str] = None,
    dry_run: bool = False,
) -> List[Dict[str, Any]]:
    """
    Generate job scripts (convenience function).

    Args:
        template_path: Path to the Jinja2 template.
        parameters: Parameter specification.
        output_dir: Output directory for scripts.
        slurm_defaults: Default SLURM arguments.
        slurm_logic_file: Path to SLURM args logic file.
        job_name_pattern: Pattern for job names.
        collection_name: Name of collection to add jobs to.
        dry_run: If True, don't write files.

    Returns:
        List of generated job info dicts.
    """
    generator = JobGenerator(
        template_path=template_path,
        parameters=parameters,
        slurm_defaults=slurm_defaults,
        slurm_logic_file=slurm_logic_file,
        job_name_pattern=job_name_pattern,
    )

    collection = None
    if collection_name:
        manager = CollectionManager()
        collection = manager.get_or_create(collection_name)

    result = generator.generate(
        output_dir=output_dir,
        collection=collection,
        dry_run=dry_run,
    )

    if collection and not dry_run:
        # Update collection with generation parameters
        collection.parameters = parameters
        manager.save(collection)

    return result


def generate_jobs_from_spec(
    spec_path: Union[str, Path],
    collection_name: Optional[str] = None,
    dry_run: bool = False,
) -> List[Dict[str, Any]]:
    """
    Generate job scripts from a spec file (convenience function).

    Args:
        spec_path: Path to the job spec YAML file.
        collection_name: Name of collection to add jobs to.
        dry_run: If True, don't write files.

    Returns:
        List of generated job info dicts.
    """
    spec_path = Path(spec_path)
    spec = load_job_spec(spec_path)
    config = get_config()
    context = build_job_subdir_context(
        spec_data=spec,
        spec_path=spec_path,
        collection_name=collection_name,
        project_root=getattr(config, "project_root", None),
    )
    generator = JobGenerator.from_spec(
        spec_path,
        config=config,
        collection_name=collection_name,
        interpolation_context=context,
    )
    job_paths = resolve_spec_job_paths(spec, config, interpolation_context=context)

    collection = None
    manager = None
    if collection_name:
        manager = CollectionManager()
        collection = manager.get_or_create(
            collection_name,
            description=spec.get("description", ""),
        )

    result = generator.generate(
        output_dir=job_paths["scripts_dir"],
        collection=collection,
        dry_run=dry_run,
    )

    if collection and not dry_run:
        # Update collection with generation parameters
        collection.parameters = spec.get("parameters", {})
        collection.description = spec.get("description", "")
        manager.save(collection)

    return result
