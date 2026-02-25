"""JEMAIL - Interactive email management tool."""

import logging
import subprocess  # nosec: B404
from pathlib import Path

import tomllib

logger = logging.getLogger(__name__)


def _get_version() -> str:
    """Get version from semver command in project root."""
    try:
        result = subprocess.run(  # nosec: B603, B607
            ["semver"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        logger.exception("Could not get version from semver", exc_info=e)
    return "0.0.0-unknown"


def _get_app_name() -> str:
    """Get app name from pyproject.toml."""
    try:
        with Path("pyproject.toml").open("rb") as f:
            return str(tomllib.load(f)["project"]["name"])
    except Exception as e:
        logger.exception("Could not get app name from pyproject.toml", exc_info=e)
        return "JEMAIL"


__version__ = _get_version()
__app_name__ = _get_app_name()
