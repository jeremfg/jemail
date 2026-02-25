"""Account configuration loader and backup for JEMAIL."""

import json
import logging
import shutil
import subprocess  # nosec: B404
from pathlib import Path
from typing import Any, cast

import yaml
from jsonschema import ValidationError as JsonSchemaValidationError
from jsonschema import validate as jsonschema_validate

from jemail import config

ACCOUNT_VALIDATOR = "doc/account.settings.schema.json"
SMB_INVALID_MSG = "Invalid SMB location."
SMB_DIR_NOT_EXIST_CODE = 3


class ConfigAccountError(Exception):
    """Custom exception for configuration errors."""


class Account:
    """Represents an email account configuration."""

    def __init__(self, path: Path) -> None:
        """Load an account configuration from YAML."""
        self.__logger = logging.getLogger(__name__)
        self.path = Path(path)
        self.data: dict[str, Any] = self._validate()
        self.__cache_init()

    def __cache_init(self) -> None:
        """Initialize local cache for account."""
        cache_path = config.APP_DATA
        if not cache_path:
            msg = "APP_DATA environment variable not set for cache location"
            raise ConfigAccountError(msg)
        self.cache_path = Path(cache_path) / self.data["email"]
        self.cache_path.mkdir(parents=True, exist_ok=True)
        if self.data["backup-smb"]:
            dest = self._rclone_cache_dir()
            src = self._rclone_backup_dir()
            if len(src) <= 0:
                raise ConfigAccountError(SMB_INVALID_MSG)
            self.__logger.info("Syncing cache from SMB for %s", self.data["email"])
            rclone_path = shutil.which("rclone")
            if not rclone_path:
                msg = "rclone binary not found in PATH for cache sync"
                raise ConfigAccountError(msg)
            try:
                # Check if the src directory exists and create it if it doesn't
                cmd: list[str] = [
                    rclone_path,
                    "lsd",
                    src,
                ]
                self.__logger.debug(
                    "Checking if SMB source exists with command: %s", " ".join(cmd)
                )
                result = subprocess.run(  # noqa: S603
                    cmd,
                    capture_output=True,
                    text=True,
                    check=False,
                    shell=False,  # nosec: B603
                )
                if (
                    result.returncode == SMB_DIR_NOT_EXIST_CODE
                ):  # Error code for 'directory does not exist'
                    self.__logger.warning("SMB source does not exist. Create it...")
                    cmd = [
                        rclone_path,
                        "mkdir",
                        src,
                    ]
                    self.__logger.debug(
                        "Creating SMB source with command: %s", " ".join(cmd)
                    )
                    subprocess.run(  # noqa: S603
                        cmd,
                        check=True,
                        shell=False,  # nosec: B603
                    )
                elif result.returncode != 0:
                    msg = f"Failed to check SMB source: {result.stderr.strip()}"
                    raise ConfigAccountError(msg)  # noqa: TRY301
                else:
                    self.__logger.debug("SMB source exists. Proceeding with sync...")
                    cmd = [
                        rclone_path,
                        "sync",
                        src,
                        dest,
                    ]
                    self.__logger.debug("Running rclone command: %s", " ".join(cmd))
                    subprocess.run(  # noqa: S603
                        cmd,
                        check=True,
                        shell=False,  # nosec: B603
                    )
                    self.__logger.info(
                        "Cache sync from SMB completed for %s", self.data["email"]
                    )
            except Exception as e:
                msg = f"Failed to sync cache from SMB: {e}"
                raise ConfigAccountError(msg) from e

    def _load_yaml(self) -> dict[str, Any]:
        """Load account configuration from file."""
        p = self.path
        if (
            not p.is_file()
            or p.is_symlink()
            or (p.is_absolute() and not str(p).startswith(str(Path.cwd())))
        ):
            msg = f"Config file not found or invalid: {p}"
            raise ConfigAccountError(msg)
        sops_path = shutil.which("sops")
        if not sops_path:
            msg = "sops binary not found in PATH"
            raise ConfigAccountError(msg)
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
            raise ConfigAccountError(msg) from e

    def _rclone_backup_dir(self) -> str:
        """Construct rclone backup directory string for SMB."""
        if self.data["backup-smb"]:
            smb = self.data["backup-smb"]
            return (
                f":smb,"
                f"host={smb['host']},"
                f"user={smb['username']},"
                f"pass={smb['password']},"
                f"domain={smb['domain']}:"
                f"/{smb['path']}"
            )
        return ""

    def _rclone_cache_dir(self) -> str:
        """Construct rclone cache directory string."""
        return str(self.cache_path)

    def _validate(self) -> dict[str, Any]:
        """Validate config against JSON schema and required fields."""
        cfg = self._load_yaml()
        validator_path = Path(config.APP_ROOT, ACCOUNT_VALIDATOR)
        try:
            with validator_path.open("r", encoding="utf-8") as f:
                schema = json.load(f)
        except Exception as e:
            msg = f"Failed to load schema: {e}"
            raise ConfigAccountError(msg) from e
        try:
            jsonschema_validate(instance=cfg, schema=schema)
        except JsonSchemaValidationError as e:
            msg = f"Config validation error: {e.message}"
            raise ConfigAccountError(msg) from e
        return cfg

    def backup(self) -> None:
        """Perform backup of emails from local cache."""
        if self.data["backup-smb"]:
            src: str = self._rclone_cache_dir()
            dst: str = self._rclone_backup_dir()
            if len(dst) <= 0:
                raise ConfigAccountError(SMB_INVALID_MSG)

            self.__logger.info("Starting backup to SMB for %s", self.data["email"])
            rclone_path = shutil.which("rclone")
            if not rclone_path:
                msg = "rclone binary not found in PATH for backup"
                raise ConfigAccountError(msg)
            try:
                cmd: list[str] = [
                    rclone_path,
                    "sync",
                    src,
                    dst,
                ]
                self.__logger.debug("Running rclone command: %s", " ".join(cmd))
                subprocess.run(  # noqa: S603
                    cmd,
                    check=True,
                    shell=False,  # nosec: B603
                )
                self.__logger.info("SMB backup completed for %s", self.data["email"])
            except Exception as e:
                msg = f"Failed to perform SMB backup: {e}"
                raise ConfigAccountError(msg) from e
        else:
            self.__logger.info("No SMB backup configured for %s", self.data["email"])

    def __getitem__(self, key: str) -> Any:
        """Allow dict-like access to account config."""
        return self.data[key]

    def __contains__(self, key: str) -> bool:
        """Allow 'in' operator for account config."""
        return key in self.data

    def get(self, key: str, default: Any = None) -> Any:
        """Get a value from the account config with a default."""
        return self.data.get(key, default)

    @property
    def account(self) -> dict[str, Any]:
        """Return the account configuration."""
        return self.data
