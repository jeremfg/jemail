"""IMAP sync with incremental updates and SMB backup."""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, ClassVar

from imap_tools import (  # type: ignore[import-not-found]
    FolderInfo,
    MailBox,
    MailMessage,
)
from O365 import Account as O365Account  # type: ignore[import-not-found]
from O365 import Protocol
from O365.utils import to_camel_case  # type: ignore[import-not-found]
from pathvalidate import sanitize_filename  # type: ignore[import-not-found]

import jemail
from jemail.conversation import BotClient
from jemail.internaldate import MailBoxWithInternalDate
from jemail.utils import Serializer

if TYPE_CHECKING:
    from jemail.account import Account
    from jemail.config import GlobalConfig


class ImapAuthenticator(ABC):
    """Handles IMAP authentication for different providers."""

    def __init__(self, config: GlobalConfig) -> None:
        """Initialize the authenticator."""
        self._config = config
        self._logger = logging.getLogger(self.__class__.__name__)

    @abstractmethod
    def authenticate(self, account: Account) -> MailBox:
        """Authenticate and return a connected MailBox."""


class ImapBasicAuthenticator(ImapAuthenticator):
    """Basic IMAP authentication using username and password."""

    def __init__(self, config: GlobalConfig) -> None:
        """Initialize Basic authenticator."""
        super().__init__(config)

    def authenticate(self, account: Account) -> MailBox:
        """Authenticate using IMAP credentials."""
        try:
            if "port" in account["imap"]:
                mailbox = MailBox(account["imap"]["host"], port=account["imap"]["port"])
            else:
                mailbox = MailBox(account["imap"]["host"])

            mailbox.login(
                account["imap"]["username"],
                account["imap"]["password"],
                initial_folder="INBOX",
            )
        except Exception as e:
            self._logger.exception(
                "Failed to connect to IMAP server for %s: %s",
                account["email"],
                exc_info=e,
            )
            raise

        self._logger.info(
            "Successfully connected to IMAP server for %s", account["email"]
        )
        return mailbox


class ImapMsOauth2Authenticator(ImapAuthenticator):
    """IMAP authentication using Microsoft OAuth2."""

    class MSOutlookProtocol(Protocol):  # type: ignore[misc]
        """A Microsoft Outlook Protocol Implementation.

        https://docs.microsoft.com/en-us/outlook/rest/compare-graph-outlook
        """

        protocol_url: ClassVar[str] = "https://outlook.office.com/"
        oauth_scope_prefix: ClassVar[str] = "https://outlook.office.com/"

        def __init__(
            self,
            **kwargs: Any,
        ) -> None:
            """Create a new Microsoft Outlook protocol object.

            _protocol_url = 'https://outlook.office.com/'

            _oauth_scope_prefix = 'https://outlook.office.com/'

            :param str api_version: api version to use
            :param str default_resource: the default resource to use when there is
            nothing explicitly specified during the requests
            """
            super().__init__(
                protocol_url=ImapMsOauth2Authenticator.MSOutlookProtocol.protocol_url,
                api_version="v1.0",
                casing_function=to_camel_case,
                protocol_scope_prefix=ImapMsOauth2Authenticator.MSOutlookProtocol.oauth_scope_prefix,
                **kwargs,
            )
            #: The max value for 'top' (999).  |br| **Type:** str
            self.max_top_value = 999  # Max $top parameter value

    def __init__(self, config: GlobalConfig) -> None:
        """Initialize Microsoft OAuth2 authenticator."""
        super().__init__(config)
        if "entraID" not in config:
            msg = (
                "Missing 'entraID' in global config for Microsoft OAuth2 authentication"
            )
            raise ValueError(msg)

    def __discord_bot(self, account: Account) -> BotClient:
        """Prepare a Discord bot for authentication delegation."""
        # Making sure we have the necessary configuration
        if "discord" not in account["imap"]:
            msg = "Missing 'discord' configuration for account %s for authentication delegation"
            raise ValueError(msg % account["email"])
        if "discord" not in self._config:
            msg = "Missing 'discord' in global config for authentication delegation"
            raise ValueError(msg)
        if not self._config["discord"]["enabled"]:
            msg = "Discord integration is disabled in global config for authentication delegation"
            raise ValueError(msg)

        # Connect the bot
        discord_token = self._config["discord"]["secret"]
        channel_id = account["imap"]["discord"]["channel_id"]
        user_id = account["imap"]["discord"]["user_id"]
        bot_client = BotClient(discord_token)
        bot_client.bot_connect(channel_id, user_id)

        return bot_client

    def __authorize_with_o365(
        self, o365_account: O365Account, bot_client: BotClient
    ) -> None:
        """Handle the Microsoft OAuth2 authorization flow with user interaction via Discord."""
        required_scopes: list[str] = ["IMAP.AccessAsUser.All"]

        def ask_for_consent(consent_url: str) -> str:
            return bot_client.bot_ask(
                (
                    "I need access to your emails. Please follow these steps:\n\n"
                    "1. Visit the URL below.\n"
                    "2. Follow the instructions on the website and authenticate.\n"
                    "3. Reply to this message with the URL you've been redirected to.\n\n"
                    f"{consent_url}"
                ),
                timeout=300,
            )

        try:
            if o365_account.authenticate(
                requested_scopes=required_scopes, handle_consent=ask_for_consent
            ):
                bot_client.bot_send("Authentication succeeded. Thank you!")
            else:
                bot_client.bot_send("Authentication failed.")
        except Exception as e:
            bot_client.bot_send(f"Authentication error: {e}")
            raise

        if (
            not o365_account.is_authenticated
            or not o365_account.connection.token_backend.has_data
        ):
            msg = "Authentication failed for Microsoft OAuth2 account"
            raise RuntimeError(msg)

    def __token_get(self, o365_account: O365Account, account: Account) -> str:
        """Get a valid access token from the O365 account, refreshing if necessary."""
        if not o365_account.connection.refresh_token():
            msg = "Failed to refresh token for Microsoft OAuth2 account"
            raise RuntimeError(msg)
        token_dict = o365_account.connection.token_backend.get_access_token(
            username=account["email"]
        )
        imap_token = token_dict["secret"]
        if not imap_token or not isinstance(imap_token, str) or len(imap_token) <= 0:
            msg = "No valid access token available with Microsoft OAuth2 account"
            raise RuntimeError(msg)

        return str(imap_token)

    def __imap_authenticate(self, account: Account, token: str) -> MailBox:
        """Perform the IMAP authentication."""
        host = account["imap"]["host"]
        if "port" in account["imap"]:
            mailbox = MailBoxWithInternalDate(host, port=account["imap"]["port"])
        else:
            mailbox = MailBoxWithInternalDate(host)
        try:
            mailbox.xoauth2(
                username=account["email"],
                access_token=token,
                initial_folder="INBOX",
            )
            self._logger.info(
                "Successfully connected to IMAP server for %s using Microsoft OAuth2",
                account["email"],
            )
        except Exception as e:
            self._logger.exception(
                "Failed to connect to IMAP server for %s using Microsoft OAuth2: %s",
                account["email"],
                exc_info=e,
            )
            raise

        return mailbox

    def authenticate(self, account: Account) -> MailBox:
        """Authenticate using Microsoft OAuth2 and return a connectedMailBox."""
        token_storage = Path(account.cache_path, ".oauth2_token.json")
        credentials = (self._config["entraID"]["id"], self._config["entraID"]["secret"])
        protocol = ImapMsOauth2Authenticator.MSOutlookProtocol()

        token_storage.touch()
        o365_account = O365Account(
            credentials=credentials, protocol=protocol, token_path=token_storage
        )
        if not o365_account.is_authenticated:
            # 1. Let's prepare the discord bot that will be asking the user for authentication
            bot_client = self.__discord_bot(account)

            # 2. Let's authenticate
            try:
                self.__authorize_with_o365(o365_account, bot_client)
            finally:
                bot_client.bot_disconnect()

        # 3. Get the access token needed for IMAP authentication
        oauth_token = self.__token_get(o365_account, account)

        # 4. Estblish the IMAP connection
        return self.__imap_authenticate(account, oauth_token)


class AuthenticatorType(Enum):
    """Enum for supported IMAP authentication types."""

    AUTH_BASIC = "Basic"
    AUTH_MSOAUTH2 = "MsOAuth2"

    # A mapping from authenticator ID to the corresponding Authenticator class
    __AUTHENTICATOR_MAP: ClassVar[dict[str, type[ImapAuthenticator]]] = {
        AUTH_BASIC: ImapBasicAuthenticator,
        AUTH_MSOAUTH2: ImapMsOauth2Authenticator,
    }

    @property
    def id(self) -> str:
        """Get the string identifier for this authenticator type."""
        return str(self.value)

    @staticmethod
    def get_authenticator(config: GlobalConfig, account: Account) -> ImapAuthenticator:
        """Get the appropriate authenticator based on account config."""
        try:
            authenticator_class = AuthenticatorType.__AUTHENTICATOR_MAP[
                account["imap"]["authentication"]
            ]
            return authenticator_class(config)
        except KeyError as err:
            msg = f"Unknown authenticator type: {account['imap']['authentication']}"
            raise ValueError(msg) from err


class Imap:
    """IMAP processor."""

    def __init__(self, config: GlobalConfig) -> None:
        """Initialize IMAP processor with global configuration."""
        self.__config = config
        self.__auth: ImapAuthenticator | None = None
        self.__box: MailBox | None = None
        self.__logger = logging.getLogger(self.__class__.__name__)
        self.__start = datetime.now(timezone.utc)
        self.dts = self.__start.strftime("%Y-%m-%d_%H%M%S")

        self.mime_handlers: dict[str, Callable[[Path, str, bytes], None]] = {
            "image/png": self._process_png,
            "image/x-png": self._process_png,
            "image/jpeg": self._process_jpeg,
            "image/gif": self._process_gif,
            "text/html": self._process_html,
            "text/plain": self._process_text,
            "application/octet-stream": self._process_generic_binary,
            "message/rfc822": self._process_rf822,
        }

    def connect(self, account_config: Account) -> MailBox:
        """Get an authenticated MailBox object for the given account config."""
        if self.__box:
            return self.__box
        self.__logger.info(
            "Connecting to IMAP server for account: %s", account_config["email"]
        )
        if self.__auth is None:
            self.__auth = AuthenticatorType.get_authenticator(
                self.__config, account_config
            )
        self.__box = self.__auth.authenticate(account_config)
        return self.__box

    KNOWN_CAPABILITIES: ClassVar[list[str]] = [
        "IMAP4",  # RFC-1730
        "IMAP4rev1",  # RFC-3501
        "AUTH=PLAIN",  # RFC-2595
        "AUTH=XOAUTH2",  # https://learn.microsoft.com/en-us/exchange/client-developer/legacy-protocols/how-to-authenticate-an-imap-pop-smtp-application-by-using-oauth
        "SASL-IR",  # RFC-4959
        "UIDPLUS",  # RFC-4315
        "MOVE",  # RFC-6851
        "ID",  # RFC-2971
        "UNSELECT",  # RFC-3691
        "CLIENTACCESSRULES",  # Microsoft Proprietary
        "CLIENTNETWORKPRESENCELOCATION",  # Microsoft Proprietary
        "BACKENDAUTHENTICATE",  # Microsoft Proprietary
        "BACKENDAUTHENTICATE-IR",  # Microsoft Proprietary
        "CHILDREN",  # RFC-3348
        "IDLE",  # RFC-2177
        "NAMESPACE",  # RFC-2342
        "LITERAL+",  # RFC-2088
    ]

    def get_capabilities(self, mailbox: MailBox) -> list[str]:
        """Get the capabilities of the connected IMAP server."""
        typ, dat = mailbox.client.capability()
        if typ != "OK":
            msg = f"Unexpected response from IMAP server when getting capabilities: {typ} {dat}"
            raise RuntimeError(msg)

        caps = str(dat[0], mailbox.client._encoding).split(" ")  # noqa: SLF001
        # Make sure they are all known capabilities
        for cap in caps:
            if cap not in Imap.KNOWN_CAPABILITIES:
                msg = f"Unknown capability from IMAP server: {cap}. Full capabilities: {caps}"
                raise RuntimeError(msg)
        return caps

    R_STR: ClassVar[str] = r"\"([^\"\\\r\n]|\\.)*\""
    R_EXT: ClassVar[str] = (
        r"\"(?P<param>(?:[^\"\\\r\n]|\\.)*)\" \((?P<flags>(?:\"(?:[^\"\\\r\n]|\\.)*\")(?: \"(?:[^\"\\\r\n]|\\.)*\")*)\)"
    )
    R_NM: ClassVar[str] = (
        r"\(\"(?P<name>(?:[^\"\\\r\n]|\\.)*)\" (?:\"(?P<delim>(?:[^\"\\\r\n]|\\.)*)\"|NIL)(?P<ext>(?: (?:\"(?:[^\"\\\r\n]|\\.)*\" \((?:\"(?:[^\"\\\r\n]|\\.)*\")(?: \"(?:[^\"\\\r\n]|\\.)*\")*\)))*)\)|NIL"
    )
    R_USR: ClassVar[str] = (
        r"\((?:\(\"(?:(?:[^\"\\\r\n]|\\.)*)\" (?:\"(?:(?:[^\"\\\r\n]|\\.)*)\"|NIL)(?: (?:\"(?:(?:[^\"\\\r\n]|\\.)*)\" \((?:\"(?:(?:[^\"\\\r\n]|\\.)*)\")(?: \"(?:(?:[^\"\\\r\n]|\\.)*)\")*\)))*\))+\)|NIL"
    )
    R_NMS: ClassVar[str] = (
        r"^(?:(?:\((?:\(\"(?:[^\"\\\r\n]|\\.)*\" (?:\"(?:(?:[^\"\\\r\n]|\\.)*)\"|NIL)(?: (?:\"(?:(?:[^\"\\\r\n]|\\.)*)\" \((?:\"(?:(?:[^\"\\\r\n]|\\.)*)\")(?: \"(?:[^\"\\\r\n]|\\.)*\")*\)))*\))+\)|NIL) ?){3}$"
    )

    def get_namespaces(self, mailbox: MailBox) -> dict[str, Any]:
        """Get the namespaces of the connected IMAP server."""

        def parse_ext_params(ext: re.Match[str]) -> dict[str, Any]:
            return {
                "Parameter": ext.group("param"),
                "Flags": [
                    flag.group(0)
                    for flag in re.finditer(Imap.R_STR, ext.group("flags"))
                ],
            }

        def parse_ext(ext: str) -> list[dict[str, Any]] | None:
            if not ext or len(ext.strip()) == 0:
                return None

            return [parse_ext_params(m) for m in re.finditer(Imap.R_EXT, ext)]

        def parse_user(usr: str) -> dict[str, Any] | None:
            usr_m: re.Match[str] | None = re.match(Imap.R_NM, usr)
            if usr_m is None or usr_m.group(0) == "NIL":
                return None
            return {
                "Prefix": usr_m.group("name"),
                "Delimiter": usr_m.group("delim"),
                "Extension": parse_ext(usr_m.group("ext")),
            }

        typ, dat = mailbox.client.namespace()
        if typ == "OK":
            answerwer = str(dat[0], mailbox.client._encoding)  # noqa: SLF001
            res = {}
            if re.match(Imap.R_NMS, answerwer):
                keys = ["Personal", "Other Users", "Shared"]
                vals = list(re.finditer(Imap.R_NM, answerwer))
                if len(vals) != len(keys):
                    msg = f"Namespace response does not contain exactly {len(keys)} namespaces: {answerwer}"
                    raise ValueError(msg)
                res = {
                    key: parse_user(match.group(0)) for key, match in zip(keys, vals)
                }
            else:
                msg = f"Namespace response does not match expected format: {answerwer}"
                raise ValueError(msg)

            return res
        msg = (
            f"Unexpected response from IMAP server when getting namespaces: {typ} {dat}"
        )
        raise RuntimeError(msg)

    R_ID = r"^\((?:(?:\"(?:(?:[^\"\\\r\n]|\\.)*)\" (?:(?:\"(?:[^\"\\\r\n]|\\.)*)\"|NIL)) ?)*\)$"
    R_KV = r"(?:\"(?P<key>(?:[^\"\\\r\n]|\\.)*)\" (?P<value>(?:\"(?:[^\"\\\r\n]|\\.)*)\"|NIL))"

    def get_id(self, mailbox: MailBox) -> dict[str, str | None] | None:
        """Get the ID information of the connected IMAP server."""
        name = "ID"
        typ, dat = mailbox.client.xatom(name, "NIL")
        typ, dat = mailbox.client._untagged_response(typ, dat, name)  # noqa: SLF001
        if typ == "OK":
            answer = str(dat[0], mailbox.client._encoding)  # noqa: SLF001
            res: dict[str, str | None] = {}
            if re.match(Imap.R_ID, answer):
                for match in re.finditer(Imap.R_KV, answer):
                    key = match.group("key")
                    value = match.group("value")
                    if value == "NIL":
                        res[key] = None
                    elif value.startswith('"') and value.endswith('"'):
                        res[key] = value[1:-1]
                    else:
                        msg = f"ID value does not match expected format: {value}"
                        raise ValueError(msg)
            else:
                msg = f"ID response does not match expected format: {answer}"
                raise ValueError(msg)
            return res
        msg = f"Failed to get ID from IMAP server: {typ} {dat}"
        raise RuntimeError(msg)

    def server_info(self, mailbox: MailBox, account: Account) -> None:
        """Get information about the connected IMAP server."""
        server_log = Path(account.cache_path, "server_log", f"{self.dts}_server.json")

        stuff = {"Mailbox": Serializer.deep_serialize(mailbox)}

        # app details
        stuff["App"] = {
            "Name": jemail.__app_name__,
            "Version": jemail.__version__,
            "Timestamp": self.dts,
        }

        # Get server capabilities
        caps = self.get_capabilities(mailbox)
        stuff["Capabilities"] = caps

        # Fetch namespace information if supported
        if "NAMESPACE" in caps:
            stuff["Namespaces"] = self.get_namespaces(mailbox)
        else:
            self.__logger.warning("IMAP server does not support NAMESPACE capability")

        # Fetch server ID if supported
        if "ID" in caps:
            stuff["ID"] = self.get_id(mailbox)
        else:
            self.__logger.warning("IMAP server does not support ID capability")

        server_log.parent.mkdir(parents=True, exist_ok=True)
        with server_log.open("w", encoding="utf-8") as f:
            json.dump(stuff, f, indent=4)

    def _get_last_id(self, id_file: Path) -> int:
        """Get the last synced message ID from a file."""
        result = 0
        if id_file.exists():
            with id_file.open("r") as f:
                try:
                    result = int(f.read().strip())
                except ValueError:
                    self.__logger.warning(
                        "Invalid last sync ID in file %s. Resetting to 0.", id_file
                    )
        return result

    def _process_folder(
        self, mailbox: MailBox, account_config: Account, folder: FolderInfo
    ) -> None:
        """Process a single folder in the mailbox."""
        maildir = Path(account_config.cache_path, "maildir")
        maildir.mkdir(parents=True, exist_ok=True)
        mailbox.folder.set(folder.name)

        fd = Path(maildir, *folder.name.split(folder.delim))
        fd.mkdir(parents=True, exist_ok=True)

        # Load last sync ID if we have one
        last_sync_id_path = Path(fd, ".last_sync_id")
        last_sync_id = self._get_last_id(last_sync_id_path)

        # Get last ID from the server to determine if there's anything new to sync
        status = mailbox.folder.status()

        # Store folder info
        folder_info_path = Path(fd, f".{self.dts}_folder.json")
        data = {
            "Folder": Serializer.deep_serialize(folder),
            "Status": Serializer.deep_serialize(status),
            "Last_ID": last_sync_id,
        }
        with folder_info_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)

        if "UIDNEXT" in status:
            next_id = status["UIDNEXT"]
            self.__logger.info(
                "Next UID on server for folder %s: %s", folder.name, next_id
            )
            if last_sync_id and int(last_sync_id) >= next_id - 1:
                self.__logger.info(
                    "Folder %s is already up to date. Skipping.", folder.name
                )
                return

        batch_size = self.__config["sync"]["batch_size"]
        criteria = f"(UID {int(last_sync_id) + 1}:*)"

        # Robust paging: fetch all matching UIDs, process in batches of 100
        if batch_size == 0:
            for msg in mailbox.fetch(criteria=criteria, mark_seen=False, bulk=True):
                self._process_message(fd, msg)
        elif batch_size > 0:
            all_uids = mailbox.uids(criteria=criteria)
            for i in range(0, len(all_uids), batch_size):
                batch_uids = all_uids[i : i + batch_size]
                last_uid_in_batch = batch_uids[-1]
                for msg in mailbox.fetch(
                    criteria=",".join(batch_uids), mark_seen=False
                ):
                    self._process_message(fd, msg)
                # Save current progress after each batch
                with last_sync_id_path.open("w", encoding="utf-8") as f:
                    f.write(str(last_uid_in_batch))
        else:
            msg = f"Invalid batch size in config: {batch_size}. Must be positive or zero for infinite."
            raise ValueError(msg)

        # Update last sync ID
        with last_sync_id_path.open("w", encoding="utf-8") as f:
            f.write(str(status["UIDNEXT"] - 1))

        # Delete old messages from server

    def _cleanup_folder(self, mailbox: MailBox, folder: Path) -> None:
        """Delete messages from the server that have already been synced."""
        nb_days_to_keep = int(self.__config["sync"]["retention_days"])
        if nb_days_to_keep <= 0:
            self.__logger.warning(
                "Cleanup disabled with retention_days=%s.", nb_days_to_keep
            )
            return

        to_delete = []
        # Parse all message files to extract the Internal Date and UID
        for msg_meta_file in folder.glob("*.json"):
            if msg_meta_file.is_file() and msg_meta_file.name.startswith("."):
                continue
            with msg_meta_file.open("r", encoding="utf-8") as f:
                meta = json.load(f)
                uid = meta["UID"]
                internal_date = meta["InternalDate"]

            arrival = datetime.strptime(internal_date, "%d-%b-%Y %H:%M:%S %z")
            age = (self.__start - arrival).days
            if age > nb_days_to_keep:
                to_delete.append(uid)

        if len(to_delete) == 0:
            self.__logger.info(
                "No messages to delete from server for folder %s.", folder
            )
            return

        mailbox.delete(to_delete, int(self.__config["sync"]["batch_size"]))

    def _process_png(
        self, attachment_folder: Path, filename_prefix: str, payload: bytes
    ) -> None:
        """Process PNG attachments. Placeholder for any special handling needed."""
        self._write_payload(Path(attachment_folder, f"{filename_prefix}.png"), payload)

    def _process_jpeg(
        self, attachment_folder: Path, filename_prefix: str, payload: bytes
    ) -> None:
        """Process JPEG attachments. Placeholder for any special handling needed."""
        self._write_payload(Path(attachment_folder, f"{filename_prefix}.jpg"), payload)

    def _process_gif(
        self, attachment_folder: Path, filename_prefix: str, payload: bytes
    ) -> None:
        """Process GIF attachments. Placeholder for any special handling needed."""
        self._write_payload(Path(attachment_folder, f"{filename_prefix}.gif"), payload)

    def _process_html(
        self, attachment_folder: Path, filename_prefix: str, payload: bytes
    ) -> None:
        """Process HTML attachments. Placeholder for any special handling needed."""
        self._write_payload(Path(attachment_folder, f"{filename_prefix}.html"), payload)

    def _process_text(
        self, attachment_folder: Path, filename_prefix: str, payload: bytes
    ) -> None:
        """Process plain text attachments. Placeholder for any special handling needed."""
        self._write_payload(Path(attachment_folder, f"{filename_prefix}.txt"), payload)

    def _process_generic_binary(
        self, attachment_folder: Path, filename_prefix: str, payload: bytes
    ) -> None:
        """Process generic binary attachments. Placeholder for any special handling needed."""
        self._write_payload(Path(attachment_folder, f"{filename_prefix}.bin"), payload)

    def _process_rf822(
        self, attachment_folder: Path, filename_prefix: str, payload: bytes
    ) -> None:
        """Process message/rfc822 attachments. Placeholder for any special handling needed."""
        self._write_payload(Path(attachment_folder, f"{filename_prefix}.eml"), payload)

    def _write_payload(self, file: Path, payload: bytes) -> None:
        """Write attachment payload to a file."""
        with file.open("wb") as f:
            f.write(payload)

    def _process_message(self, folder_path: Path, msg: MailMessage) -> None:
        """Process a single email message and save it to the cache."""
        msg_id = msg.uid
        msg_meta_path = Path(folder_path, f"{msg_id}.json")
        msg_path = Path(folder_path, f"{msg_id}.eml")

        meta = {
            "Flags": msg.flags,
            "InternalDate": msg.internal_date,
            "RFC822_size": msg.size_rfc822,
            "UID": msg.uid,
        }

        with msg_meta_path.open("w", encoding="utf-8") as f:
            json.dump(meta, f, indent=4)

        with msg_path.open("wb") as f:
            f.write(msg.obj.as_bytes())

        # Save all attachments, if any
        unamed_attachment_count = 0
        if msg.attachments and len(msg.attachments) > 0:
            attachments_path = Path(folder_path, f"{msg_id}.attachments")
            attachments_path.mkdir(parents=True, exist_ok=True)
            for attachment in msg.attachments:
                if not attachment.filename or len(attachment.filename.strip()) == 0:
                    handler = self.mime_handlers.get(attachment.content_type)
                    if handler:
                        handler(
                            attachments_path,
                            f"body_{unamed_attachment_count}",
                            attachment.payload,
                        )
                    else:
                        msg = f"Attachment with empty filename in message {msg_id} in folder {folder_path} with content type {attachment.content_type}. Skipping."
                        self.__logger.warning(msg)
                        raise RuntimeError(msg)
                    unamed_attachment_count += 1
                else:
                    # Sanitize filename to prevent issues with special characters or path traversal
                    att_path = Path(
                        attachments_path, sanitize_filename(attachment.filename)
                    )
                    with att_path.open("wb") as f:
                        f.write(attachment.payload)

    def sync(self, account_config: Account) -> None:
        """Sync IMAP account with incremental updates."""
        mailbox = self.connect(account_config)

        self.server_info(mailbox, account_config)

        # Loop on all folders and process them one by one
        folders = mailbox.folder.list()
        for folder in folders:
            self.__logger.info("Processing folder: %s", folder.name)
            self._process_folder(mailbox, account_config, folder)

    def clean(self, account_config: Account) -> None:
        """Clean up old messages from the server based on retention policy."""
        mailbox = self.connect(account_config)

        # Loop on all folders and clean them one by one
        folders = mailbox.folder.list()
        for folder in folders:
            self.__logger.info("Cleaning folder: %s", folder.name)
            fd = Path(
                account_config.cache_path,
                "maildir",
                *folder.name.split(folder.delim),
            )
            if fd.exists() and fd.is_dir():
                self._cleanup_folder(mailbox, fd)
            else:
                self.__logger.warning(
                    "Folder path %s does not exist or is not a directory. Skipping cleanup for this folder.",
                    fd,
                )
