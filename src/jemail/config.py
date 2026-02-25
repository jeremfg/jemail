"""Global configuration loader for JEMAIL."""

import json
import shutil
import subprocess  # nosec: B404
from os import environ
from pathlib import Path
from typing import Any, cast

import tomllib
import yaml
from jsonschema import ValidationError as JsonSchemaValidationError
from jsonschema import validate as jsonschema_validate

# Global constants
APP_ROOT: Path = Path(__file__).resolve().parent.parent.parent


def __get_app_name() -> str:
    toml_file = Path(APP_ROOT, "pyproject.toml")
    with toml_file.open("rb") as f:
        return str(tomllib.load(f)["project"]["name"])


def __get_app_data() -> str:
    app_data = environ.get("APP_DATA")
    if not app_data:
        msg = "APP_DATA environment variable not set for cache location"
        raise ConfigGlobalError(msg)
    return app_data


APP_NAME: str = __get_app_name()
APP_DATA: str = __get_app_data()
GLOBAL_CONFIG = "data/global.settings.yaml"
ACCOUNT_CONFIGS = "data/accounts"

# Local constants
GLOBAL_VALIDATOR = "doc/global.settings.schema.json"


class ConfigGlobalError(Exception):
    """Custom exception for configuration errors."""


class GlobalConfig:
    """Represents the global JEMAIL configuration."""

    def __init__(self, path: Path) -> None:
        """Load the global configuration from YAML (SOPS or plain)."""
        self.path = Path(path)
        self.data: dict[str, Any] = self._validate()

    def _load_yaml(self) -> dict[str, Any]:
        p = self.path
        if (
            not p.is_file()
            or p.is_symlink()
            or (p.is_absolute() and not str(p).startswith(str(Path.cwd())))
        ):
            msg = f"Config file not found or invalid: {p}"
            raise ConfigGlobalError(msg)
        sops_path = shutil.which("sops")
        if not sops_path:
            msg = "sops binary not found in PATH"
            raise ConfigGlobalError(msg)
        try:
            result = subprocess.run(  # noqa: S603
                [sops_path, "-d", str(p)],
                capture_output=True,
                text=True,
                check=False,
                shell=False,  # nosec: B603
            )
            if result.returncode == 0:
                return cast("dict[str, Any]", yaml.safe_load(result.stdout))
            with p.open(encoding="utf-8") as f:
                return cast("dict[str, Any]", yaml.safe_load(f))
        except Exception as e:
            msg = f"Failed to load config: {e}"
            raise ConfigGlobalError(msg) from e

    def _validate(self) -> dict[str, Any]:
        cfg = self._load_yaml()
        schema_path = Path(APP_ROOT, GLOBAL_VALIDATOR)
        try:
            with schema_path.open("r", encoding="utf-8") as f:
                schema = json.load(f)
        except Exception as e:
            msg = f"Failed to load schema: {e}"
            raise ConfigGlobalError(msg) from e
        try:
            jsonschema_validate(instance=cfg, schema=schema)
        except JsonSchemaValidationError as e:
            msg = f"Config validation error: {e.message}"
            raise ConfigGlobalError(msg) from e
        return cfg

    def __contains__(self, key: str) -> bool:
        """Allow 'in' operator for global config."""
        return key in self.data

    def __getitem__(self, key: str) -> Any:
        """Allow dict-like access to global config."""
        return self.data[key]

    def get(self, key: str, default: Any = None) -> Any:
        """Get a value from the global config with a default."""
        return self.data.get(key, default)

    @property
    def config(self) -> dict[str, Any]:
        """Return the global configuration dictionary."""
        return self.data
