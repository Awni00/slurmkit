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
from typing import Any, Callable, Dict, Iterator, List, Optional, Union

import yaml
from jinja2 import Environment, FileSystemLoader, Template

from slurmkit.config import Config, get_config
from slurmkit.collections import Collection, CollectionManager


# =============================================================================
# Parameter Expansion
# =============================================================================

def expand_grid(params: Dict[str, List[Any]]) -> Iterator[Dict[str, Any]]:
    """
    Expand a parameter grid into all combinations.

    Takes a dictionary where values are lists and yields all
    combinations as individual dictionaries.

    Args:
        params: Dictionary mapping parameter names to lists of values.

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
        yield dict(zip(keys, combo))


def expand_parameters(
    spec: Dict[str, Any],
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

    if mode == "list":
        if isinstance(values, list):
            return values
        else:
            return [values]

    elif mode == "grid":
        return list(expand_grid(values))

    else:
        raise ValueError(f"Unknown parameter mode: {mode}. Use 'grid' or 'list'.")


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
        >>> scripts = generator.generate(output_dir="jobs/exp1/scripts")
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

        # SLURM arguments - merge config defaults with job spec defaults
        # Config defaults provide the base, job spec defaults override
        self.slurm_defaults = config.get_slurm_defaults().copy()
        if slurm_defaults:
            self.slurm_defaults.update(slurm_defaults)
        self.slurm_logic_func = None

        if slurm_logic_file:
            self.slurm_logic_func = load_slurm_args_function(
                slurm_logic_file,
                slurm_logic_function,
            )

        # Set up Jinja2 environment
        template_dir = self.template_path.parent
        self._env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            keep_trailing_newline=True,
        )

    @classmethod
    def from_spec(
        cls,
        spec_path: Union[str, Path],
        config: Optional[Config] = None,
    ) -> "JobGenerator":
        """
        Create a generator from a job spec file.

        Args:
            spec_path: Path to the job spec YAML file.
            config: Configuration object.

        Returns:
            Configured JobGenerator instance.
        """
        spec_path = Path(spec_path)
        spec = load_job_spec(spec_path)

        # Resolve paths relative to spec file
        spec_dir = spec_path.parent

        template_path = spec.get("template", "")
        if not Path(template_path).is_absolute():
            template_path = spec_dir / template_path

        slurm_logic_file = None
        slurm_logic_function = "get_slurm_args"
        slurm_args = spec.get("slurm_args", {})

        if "logic" in slurm_args:
            logic_spec = slurm_args["logic"]
            logic_file = logic_spec.get("file", "")
            if logic_file:
                if not Path(logic_file).is_absolute():
                    slurm_logic_file = spec_dir / logic_file
                else:
                    slurm_logic_file = Path(logic_file)
            slurm_logic_function = logic_spec.get("function", "get_slurm_args")

        logs_dir = spec.get("logs_dir")
        if logs_dir and not Path(logs_dir).is_absolute():
            logs_dir = spec_dir / logs_dir

        return cls(
            template_path=template_path,
            parameters=spec.get("parameters", {}),
            slurm_defaults=slurm_args.get("defaults"),
            slurm_logic_file=slurm_logic_file,
            slurm_logic_function=slurm_logic_function,
            job_name_pattern=spec.get("job_name_pattern"),
            logs_dir=logs_dir,
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
        output_dir = Path(output_dir)

        if not dry_run:
            output_dir.mkdir(parents=True, exist_ok=True)

        # Load template
        template = self._env.get_template(self.template_path.name)

        # Expand parameters
        param_list = expand_parameters(self.parameters)

        generated = []

        for params in param_list:
            # Generate job name
            job_name = generate_job_name(
                params,
                pattern=self.job_name_pattern,
                env=self._env,
            )

            # Compute SLURM args
            slurm_args = compute_slurm_args(
                params,
                self.slurm_defaults,
                self.slurm_logic_func,
            )

            # Prepare template context
            context = {
                "job_name": job_name,
                "slurm": slurm_args,
                "logs_dir": str(self.logs_dir) if self.logs_dir else ".",
                "params": params,  # Also include params dict for iteration
                **params,  # Unpack for direct access (e.g., {{ algorithm }})
            }

            # Render template
            content = template.render(**context)

            # Determine output path
            script_path = output_dir / f"{job_name}.job"

            # Write script
            if not dry_run:
                script_path.write_text(content)

            job_info = {
                "job_name": job_name,
                "script_path": script_path,
                "parameters": params,
                "slurm_args": slurm_args,
            }

            generated.append(job_info)

            # Add to collection if provided
            if collection is not None:
                collection.add_job(
                    job_name=job_name,
                    script_path=script_path,
                    parameters=params,
                )

        return generated

    def preview(self, index: int = 0) -> str:
        """
        Preview a generated script without writing files.

        Args:
            index: Index of the parameter combination to preview.

        Returns:
            Rendered script content.
        """
        # Load template
        template = self._env.get_template(self.template_path.name)

        # Expand parameters
        param_list = expand_parameters(self.parameters)

        if index >= len(param_list):
            raise IndexError(f"Index {index} out of range (max {len(param_list) - 1})")

        params = param_list[index]

        # Generate job name
        job_name = generate_job_name(
            params,
            pattern=self.job_name_pattern,
            env=self._env,
        )

        # Compute SLURM args
        slurm_args = compute_slurm_args(
            params,
            self.slurm_defaults,
            self.slurm_logic_func,
        )

        # Prepare template context
        context = {
            "job_name": job_name,
            "slurm": slurm_args,
            "logs_dir": str(self.logs_dir) if self.logs_dir else ".",
            "params": params,  # Also include params dict for iteration
            **params,  # Unpack for direct access
        }

        return template.render(**context)

    def count_jobs(self) -> int:
        """
        Count how many jobs would be generated.

        Returns:
            Number of parameter combinations.
        """
        return len(expand_parameters(self.parameters))

    def list_job_names(self) -> List[str]:
        """
        List all job names that would be generated.

        Returns:
            List of job names.
        """
        param_list = expand_parameters(self.parameters)
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
    output_dir: Optional[Union[str, Path]] = None,
    collection_name: Optional[str] = None,
    dry_run: bool = False,
) -> List[Dict[str, Any]]:
    """
    Generate job scripts from a spec file (convenience function).

    Args:
        spec_path: Path to the job spec YAML file.
        output_dir: Override output directory from spec.
        collection_name: Name of collection to add jobs to.
        dry_run: If True, don't write files.

    Returns:
        List of generated job info dicts.
    """
    spec_path = Path(spec_path)
    spec = load_job_spec(spec_path)

    # Determine output directory
    if output_dir is None:
        output_dir = spec.get("output_dir", ".")
        if not Path(output_dir).is_absolute():
            output_dir = spec_path.parent / output_dir

    generator = JobGenerator.from_spec(spec_path)

    collection = None
    manager = None
    if collection_name:
        manager = CollectionManager()
        collection = manager.get_or_create(
            collection_name,
            description=spec.get("description", ""),
        )

    result = generator.generate(
        output_dir=output_dir,
        collection=collection,
        dry_run=dry_run,
    )

    if collection and not dry_run:
        # Update collection with generation parameters
        collection.parameters = spec.get("parameters", {})
        collection.description = spec.get("description", "")
        manager.save(collection)

    return result
