"""Main entry point for JEMAIL TUI application."""

import logging
from datetime import datetime, timezone
from imaplib import IMAP4
from pathlib import Path

from jemail.account import Account
from jemail.config import (
    ACCOUNT_CONFIGS,
    APP_DATA,
    APP_NAME,
    APP_ROOT,
    GLOBAL_CONFIG,
    GlobalConfig,
)
from jemail.imap import Imap

# Configure logging
Path(f"{APP_DATA}/.log").mkdir(parents=True, exist_ok=True)
timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
log_filename = f"{APP_DATA}/.log/{APP_NAME}_{timestamp}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(process)d %(levelname)s %(filename)s:%(lineno)d - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(log_filename)],
)


def main() -> None:
    """Start the JEMAIL TUI application."""
    logger = logging.getLogger(__name__)
    logger.info("Starting %s...", APP_NAME)

    config = GlobalConfig(Path(APP_ROOT, GLOBAL_CONFIG))

    logger.info("Loaded global config: %s", config)
    if config["log_level"]:
        logging.getLogger().setLevel(config["log_level"].upper())
        logger.info("Set log level to %s", config["log_level"].upper())

    if not config["enabled"]:
        logger.info("%s is disabled in the global config. Exiting.", APP_NAME)
        return

    imap = Imap(config)  # Initialize the IMAP processor

    # Build a list of all accounts from the config directory
    accounts: list[Account] = []
    accounts_dir = Path(APP_ROOT, ACCOUNT_CONFIGS)
    for account_file in accounts_dir.glob("*.yaml"):
        logger.info(f"Found account config: {account_file}")
        cur_account = Account(account_file)
        email = cur_account["email"]
        logger.info(f"Loaded account config: {email}")
        accounts.append(cur_account)

    for account in accounts:
        logger.info(f"Processing account: {account['email']}")
        failed: Exception = None

        while not failed:
            try:
                imap.sync(account)
                account.backup()
                break  # Exit the retry loop on success
            except IMAP4.abort as e:
                if "Connection is closed." in str(e) or "AccessTokenExpired" in str(e):
                    msg = f"IMAP connection aborted for {account['email']}: {e}. Retrying..."
                    logger.warning(msg)
                else:
                    msg = f"IMAP abort error for {account['email']}: {e}"
                    logger.exception(msg)
                    failed = e
            except Exception as e:
                msg = f"Error processing account {account['email']}: {e}"
                logger.exception(msg)
                failed = e

            account.backup()
            if failed:
                raise failed

        logger.info(f"Cleaning up account: {account['email']}")
        imap.clean(account)
        logger.info(f"Finished processing account: {account['email']}")


if __name__ == "__main__":
    main()
