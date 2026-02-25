"""Tests for Account configuration."""

from pathlib import Path

from jemail.account import Account
from jemail.config import APP_ROOT


class TestAccountConfig:
    """Tests for Account configuration loading and validation."""

    def test_load_hotmail_account_config(self) -> None:
        """Test loading a valid Hotmail account configuration."""
        example_path = Path(
            APP_ROOT,
            "data",
            "accounts",
            "hotmail.settings.yaml",
        )
        hotmail = Account(example_path)
        assert hotmail is not None
