"""Discord Conversation Bot Client."""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import CancelledError
from threading import Event, Thread
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from asyncio.events import AbstractEventLoop

from discord import (  # type: ignore[import-not-found]
    Client,
    Intents,
    Message,
    MessageType,
)


class BotClient(Client):  # type: ignore[misc]
    """A Discord bot client for conversational interactions."""

    def __init__(self, token: str) -> None:
        """Create a new BotClient instance."""
        intents = Intents.default()
        intents.messages = True
        super().__init__(intents=intents)
        self.__logger = logging.getLogger(__name__)
        self.__token = token
        self.__last_message = None
        self.__channel: Any = None
        self.__channel_id: int | None = None
        self.__user_id: int | None = None
        self.__ready_event = Event()
        self.__reply_event = Event()
        self.__loop: AbstractEventLoop | None = None

    def bot_connect(self, channel_id: int, user_id: int) -> None:
        """Connect the bot to a specific channel and user for conversation."""
        if self.__token is None or len(self.__token) <= 0:
            msg = "No token to connect with the bot"
            raise ValueError(msg)
        self.__last_message = None
        self.__channel_id = channel_id
        self.__user_id = user_id
        if self.__channel is None:
            self.__ready_event.clear()
            self.__logger.info("Connecting to Discord bot...")

            def run_bot() -> None:
                asyncio.run(self.start(self.__token))

            Thread(target=run_bot, daemon=True).start()
            self.__ready_event.wait()
            self.__logger.info("Bot connected and ready.")
        else:
            self.__logger.warning("Switched channel.")
            if self.__channel_id is not None:
                self.__channel = self.get_channel(self.__channel_id)

    def bot_disconnect(self) -> None:
        """Disconnect the bot cleanly."""
        self.__logger.info("Disconnecting from Discord bot...")
        self.__channel = None
        self.__channel_id = None
        self.__user_id = None
        if self.__loop is not None:
            fut = asyncio.run_coroutine_threadsafe(self.close(), self.__loop)
            try:
                fut.result()
            except CancelledError as e:
                msg = f"Ignore this during disconnect: {type(e).__name__}: {e}"
                self.__logger.warning(msg)
        else:
            self.__logger.warning(
                "Bot event loop not initialized; cannot close cleanly."
            )
        self.__logger.info("Bot disconnected.")

    async def on_ready(self) -> None:
        """Set up channel and signal readiness when bot is ready."""
        if self.__channel_id is not None:
            self.__channel = self.get_channel(self.__channel_id)
        self.__loop = asyncio.get_running_loop()
        self.__ready_event.set()

    async def on_message(self, message: Message) -> None:
        """Check if received message is a reply to the bot, then store it and signal if so."""
        # Ignore messages sent by the bot itself
        if self.user is not None and message.author.id == self.user.id:
            return
        if (
            message.type == MessageType.reply
            and self.__last_message is not None
            and message.reference is not None
            and message.reference.message_id == self.__last_message.id
        ):
            self.__logger.info(f"Received expected reply: {message.content}")
            self.__last_message = message
            self.__reply_event.set()
        else:
            self.__logger.debug(f"Received an unexpected message: {message.content}")

    def bot_send(self, message: str) -> None:
        """Send a message to the connected channel."""
        if self.__channel is None:
            msg = "Bot is not connected to a channel."
            raise RuntimeError(msg)

        self.__reply_event.clear()
        loop = self._get_loop()
        if self.__last_message is None:
            content = f"Hello <@{self.__user_id}>,\n {message}"
            fut = asyncio.run_coroutine_threadsafe(self.__channel.send(content), loop)
        else:
            fut = asyncio.run_coroutine_threadsafe(
                self.__channel.send(message, reference=self.__last_message), loop
            )
        sent = fut.result()
        self.__last_message = sent

    def bot_receive(self, timeout: int = 60) -> str:
        """Receive a message from the connected channel."""
        if self.__channel is None:
            msg = "Bot is not connected to a channel."
            raise RuntimeError(msg)

        received = self.__reply_event.wait(timeout=timeout)
        if not received:
            self.__logger.warning("No reply received within timeout.")
            return ""
        if self.__last_message is not None and hasattr(self.__last_message, "content"):
            return str(getattr(self.__last_message, "content", ""))
        self.__logger.warning("No message content available.")
        return ""

    def _get_loop(self) -> asyncio.AbstractEventLoop:
        """Return the loop from the bot thread."""
        if self.__loop is None:
            msg = "Bot event loop not initialized yet."
            raise RuntimeError(msg)
        return self.__loop

    def bot_ask(self, message: str, timeout: int = 60) -> str:
        """Send a message and wait for a reply from the connected channel."""
        self.bot_send(message)
        return self.bot_receive(timeout=timeout)
