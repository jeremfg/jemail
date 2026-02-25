"""Overrides for imap-tools so we can access INTERNALDATE."""

from __future__ import annotations

import re
from functools import cached_property
from typing import TYPE_CHECKING

from imap_tools import MailBox, MailMessage  # type: ignore[import-not-found]
from typing_extensions import override

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from imap_tools.mailbox import Criteria  # type: ignore[import-not-found]


class MailMessageWithInternalDate(MailMessage):  # type: ignore[misc]
    """MailMessage subclass that parses and exposes INTERNALDATE."""

    @cached_property
    def internal_date(self) -> str | None:
        """Parse INTERNALDATE from the raw email data."""
        for raw_flag_item in self._raw_flag_data:
            date_match = re.search(
                r"INTERNALDATE\s+\"(?P<date>[^\"]+)\"", raw_flag_item.decode()
            )
            if date_match:
                return date_match.group("date")
        return None


class MailBoxWithInternalDate(MailBox):  # type: ignore[misc]
    """MailBox subclass that fetches INTERNALDATE and uses MailMessageWithInternalDate."""

    email_message_class = MailMessageWithInternalDate

    @override
    def fetch(
        self,
        criteria: Criteria = "ALL",
        charset: str = "US-ASCII",
        limit: int | slice | None = None,
        mark_seen: bool | int = True,
        reverse: bool = False,
        headers_only: bool = False,
        bulk: bool | int = False,
        sort: str | Iterable[str] | None = None,
    ) -> Iterator[MailMessageWithInternalDate]:
        """Override fetch method (copy) to construct a MailMessageWithInternalDate with INTERNALDATE."""
        message_parts = f"(BODY{'' if mark_seen else '.PEEK'}[{'HEADER' if headers_only else ''}] UID FLAGS RFC822.SIZE INTERNALDATE)"
        limit_range = slice(0, limit) if type(limit) is int else limit or slice(None)
        uids = tuple(
            (reversed if reverse else iter)(self.uids(criteria, charset, sort))
        )[limit_range]
        if bulk:
            message_generator = self._fetch_in_bulk(uids, message_parts, reverse, bulk)
        else:
            message_generator = self._fetch_by_one(uids, message_parts)
        for fetch_item in message_generator:
            yield self.email_message_class(fetch_item)
