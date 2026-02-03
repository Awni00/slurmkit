"""
Configuration management for slurmkit.

This module handles loading and merging configuration from multiple sources:
1. Built-in defaults (lowest priority)
2. Project-level config file (.slurm-kit/config.yaml)
3. Environment variables
4. CLI arguments (highest priority, handled at CLI level)

Environment Variables:
    SLURMKIT_CONFIG: Path to config file (default: .slurm-kit/config.yaml)
    SLURMKIT_JOBS_DIR: Default jobs directory
    SLURMKIT_COLLECTIONS_DIR: Collections directory
    SLURMKIT_SYNC_DIR: Sync files directory
    SLURMKIT_WANDB_ENTITY: W&B entity
    SLURMKIT_WANDB_PROJECT: Default W&B project
    SLURMKIT_DRY_RUN: Global dry-run mode (1 or true)
"""

import os
import socket
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml


# =============================================================================
# Default Configuration
# =============================================================================

DEFAULT_CONFIG = {
    # Directory structure
    "jobs_dir": "jobs/",
    "collections_dir": ".job-collections/",
    "sync_dir": ".slurm-kit/sync/",

    # Output file patterns (tried in order to match job outputs)
    # Supported placeholders: {job_name}, {job_id}
    "output_patterns": [
        "{job_name}.{job_id}.out",
        "{job_name}.{job_id}.*.out",
        "slurm-{job_id}.out",
    ],

    # Default SLURM arguments for job generation
    "slurm_defaults": {
        "partition": "compute",
        "time": "24:00:00",
        "mem": "16G",
        "nodes": 1,
        "ntasks": 1,
    },

    # W&B settings (optional)
    "wandb": {
        "entity": None,
        "default_projects": [],
    },

    # Job directory structure within each experiment
    "job_structure": {
        "scripts_subdir": "job_scripts/",
        "logs_subdir": "logs/",
    },

    # Cleanup defaults
    "cleanup": {
        "threshold_seconds": 300,  # Min runtime to keep (5 minutes)
        "min_age_days": 3,         # Min age before considering for cleanup
    },
}

# Environment variable prefix
ENV_PREFIX = "SLURMKIT_"

# Mapping of environment variables to config paths
ENV_VAR_MAP = {
    "SLURMKIT_CONFIG": None,  # Special: path to config file itself
    "SLURMKIT_JOBS_DIR": "jobs_dir",
    "SLURMKIT_COLLECTIONS_DIR": "collections_dir",
    "SLURMKIT_SYNC_DIR": "sync_dir",
    "SLURMKIT_WANDB_ENTITY": "wandb.entity",
    "SLURMKIT_WANDB_PROJECT": "wandb.default_project",
    "SLURMKIT_DRY_RUN": "dry_run",
}


# =============================================================================
# Configuration Class
# =============================================================================

class Config:
    """
    Configuration manager for slurmkit.

    Loads configuration from multiple sources and provides access to settings.
    Configuration precedence (highest to lowest):
    1. Explicit overrides (passed to methods)
    2. Environment variables
    3. Project config file
    4. Built-in defaults

    Attributes:
        config_path: Path to the loaded config file (if any)
        project_root: Root directory of the project (where .slurm-kit/ lives)
        hostname: Current machine's hostname (for cluster identification)

    Example:
        >>> config = Config()
        >>> config.get("jobs_dir")
        'jobs/'
        >>> config.get("slurm_defaults.partition")
        'compute'
    """

    def __init__(
        self,
        config_path: Optional[Union[str, Path]] = None,
        project_root: Optional[Union[str, Path]] = None,
    ):
        """
        Initialize configuration.

        Args:
            config_path: Explicit path to config file. If None, searches for
                .slurm-kit/config.yaml in project_root or current directory.
            project_root: Project root directory. If None, uses current directory.
        """
        self.hostname = socket.gethostname()
        self.project_root = Path(project_root) if project_root else Path.cwd()

        # Determine config file path
        if config_path:
            self.config_path = Path(config_path)
        else:
            # Check environment variable first
            env_config = os.environ.get("SLURMKIT_CONFIG")
            if env_config:
                self.config_path = Path(env_config)
            else:
                self.config_path = self.project_root / ".slurm-kit" / "config.yaml"

        # Load configuration
        self._config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        """
        Load and merge configuration from all sources.

        Returns:
            Merged configuration dictionary.
        """
        # Start with defaults
        config = _deep_copy(DEFAULT_CONFIG)

        # Merge project config file if it exists
        if self.config_path.exists():
            with open(self.config_path, "r") as f:
                file_config = yaml.safe_load(f) or {}
            config = _deep_merge(config, file_config)

        # Apply environment variable overrides
        config = self._apply_env_overrides(config)

        return config

    def _apply_env_overrides(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply environment variable overrides to config.

        Args:
            config: Current configuration dictionary.

        Returns:
            Configuration with environment overrides applied.
        """
        for env_var, config_path in ENV_VAR_MAP.items():
            if config_path is None:
                continue  # Skip special variables like SLURMKIT_CONFIG

            value = os.environ.get(env_var)
            if value is not None:
                # Handle boolean conversion for dry_run
                if config_path == "dry_run":
                    value = value.lower() in ("1", "true", "yes")

                # Set nested config value
                _set_nested(config, config_path, value)

        return config

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a configuration value by dot-separated key path.

        Args:
            key: Dot-separated key path (e.g., "slurm_defaults.partition")
            default: Default value if key not found.

        Returns:
            Configuration value or default.

        Example:
            >>> config.get("jobs_dir")
            'jobs/'
            >>> config.get("slurm_defaults.partition")
            'compute'
            >>> config.get("nonexistent", "fallback")
            'fallback'
        """
        return _get_nested(self._config, key, default)

    def get_path(self, key: str, default: Any = None) -> Optional[Path]:
        """
        Get a configuration value as a Path, resolved relative to project root.

        Args:
            key: Dot-separated key path.
            default: Default value if key not found.

        Returns:
            Resolved Path or None.
        """
        value = self.get(key, default)
        if value is None:
            return None
        path = Path(value)
        if not path.is_absolute():
            path = self.project_root / path
        return path

    def get_output_patterns(self) -> List[str]:
        """
        Get output file patterns in priority order.

        Returns:
            List of output file pattern strings.
        """
        patterns = self.get("output_patterns", DEFAULT_CONFIG["output_patterns"])
        if isinstance(patterns, str):
            patterns = [patterns]
        return patterns

    def get_slurm_defaults(self) -> Dict[str, Any]:
        """
        Get default SLURM arguments.

        Returns:
            Dictionary of default SLURM arguments.
        """
        return self.get("slurm_defaults", DEFAULT_CONFIG["slurm_defaults"])

    def as_dict(self) -> Dict[str, Any]:
        """
        Return the full configuration as a dictionary.

        Returns:
            Complete configuration dictionary.
        """
        return _deep_copy(self._config)

    def save(self, path: Optional[Union[str, Path]] = None) -> Path:
        """
        Save current configuration to a YAML file.

        Args:
            path: Path to save to. Defaults to self.config_path.

        Returns:
            Path where config was saved.
        """
        save_path = Path(path) if path else self.config_path
        save_path.parent.mkdir(parents=True, exist_ok=True)

        with open(save_path, "w") as f:
            yaml.dump(self._config, f, default_flow_style=False, sort_keys=False)

        return save_path

    def __repr__(self) -> str:
        return f"Config(config_path={self.config_path}, project_root={self.project_root})"


# =============================================================================
# Module-level convenience functions
# =============================================================================

# Global config instance (lazily initialized)
_global_config: Optional[Config] = None


def get_config(
    config_path: Optional[Union[str, Path]] = None,
    project_root: Optional[Union[str, Path]] = None,
    reload: bool = False,
) -> Config:
    """
    Get the global configuration instance.

    This function provides a singleton-like access to configuration.
    On first call (or when reload=True), it creates a new Config instance.

    Args:
        config_path: Explicit path to config file.
        project_root: Project root directory.
        reload: Force reload of configuration.

    Returns:
        Global Config instance.

    Example:
        >>> config = get_config()
        >>> config.get("jobs_dir")
        'jobs/'
    """
    global _global_config

    if _global_config is None or reload:
        _global_config = Config(config_path=config_path, project_root=project_root)

    return _global_config


def init_config(
    project_root: Optional[Union[str, Path]] = None,
    overwrite: bool = False,
    **kwargs: Any,
) -> Path:
    """
    Initialize a new project configuration file.

    Creates .slurm-kit/config.yaml with default values, optionally
    customized with provided kwargs.

    Args:
        project_root: Project root directory. Defaults to current directory.
        overwrite: If True, overwrite existing config file.
        **kwargs: Configuration values to set (e.g., jobs_dir="my_jobs/").

    Returns:
        Path to created config file.

    Raises:
        FileExistsError: If config file exists and overwrite=False.

    Example:
        >>> init_config(jobs_dir="experiments/", slurm_defaults={"partition": "gpu"})
        PosixPath('.slurm-kit/config.yaml')
    """
    root = Path(project_root) if project_root else Path.cwd()
    config_path = root / ".slurm-kit" / "config.yaml"

    if config_path.exists() and not overwrite:
        raise FileExistsError(
            f"Config file already exists: {config_path}. "
            "Use overwrite=True to replace."
        )

    # Start with defaults and apply any overrides
    config_data = _deep_copy(DEFAULT_CONFIG)
    for key, value in kwargs.items():
        if isinstance(value, dict) and key in config_data:
            config_data[key] = _deep_merge(config_data[key], value)
        else:
            config_data[key] = value

    # Create directory and write config
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        yaml.dump(config_data, f, default_flow_style=False, sort_keys=False)

    return config_path


# =============================================================================
# Helper Functions
# =============================================================================

def _deep_copy(d: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a deep copy of a dictionary.

    Args:
        d: Dictionary to copy.

    Returns:
        Deep copy of the dictionary.
    """
    import copy
    return copy.deepcopy(d)


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deep merge two dictionaries, with override taking precedence.

    Args:
        base: Base dictionary.
        override: Dictionary with values to override.

    Returns:
        Merged dictionary.
    """
    result = _deep_copy(base)

    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value

    return result


def _get_nested(d: Dict[str, Any], key: str, default: Any = None) -> Any:
    """
    Get a nested dictionary value using dot notation.

    Args:
        d: Dictionary to search.
        key: Dot-separated key path (e.g., "a.b.c").
        default: Default value if not found.

    Returns:
        Value at key path or default.
    """
    keys = key.split(".")
    value = d

    for k in keys:
        if isinstance(value, dict) and k in value:
            value = value[k]
        else:
            return default

    return value


def _set_nested(d: Dict[str, Any], key: str, value: Any) -> None:
    """
    Set a nested dictionary value using dot notation.

    Args:
        d: Dictionary to modify.
        key: Dot-separated key path (e.g., "a.b.c").
        value: Value to set.
    """
    keys = key.split(".")

    for k in keys[:-1]:
        if k not in d:
            d[k] = {}
        d = d[k]

    d[keys[-1]] = value
