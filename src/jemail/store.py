"""Maildir storage and queries."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def load_maildir(maildir_path: str) -> None:
    """Load emails from a Maildir directory.

    TODO: Implement Maildir reading with:
    - cur/, new/, tmp/ support
    - Sync state management
    - Optional index support.
    """
    logger.info("Loading Maildir from %s", maildir_path)


def save_email(maildir_path: str, email_message: Any) -> None:
    """Save an email to Maildir.

    TODO: Implement email saving with proper Maildir format.
    """
    logger.debug("Saving email to Maildir")


def delete_email(maildir_path: str, email_filename: str) -> None:
    """Delete an email from Maildir.

    TODO: Implement email deletion.
    """
    logger.debug("Deleting email: %s", email_filename)
