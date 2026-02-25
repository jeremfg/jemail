"""Utility functions for JEMAIL."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class Serializer:
    """Utility class for deep serialization of complex objects."""

    @staticmethod
    def obj_serialize(
        obj: Any, seen: dict[int, str] | None = None, cur: str = "/"
    ) -> Any:
        """Serialize an object by introspecting its attributes."""
        new_dict = {}
        for attr in dir(obj):
            val = getattr(obj, attr)
            if callable(val) or isinstance(val, type):
                pass
            else:
                try:
                    new_dict[attr] = Serializer.deep_serialize(
                        val, seen, cur + f"{attr}/"
                    )
                except Exception:  # noqa: BLE001
                    new_dict[attr] = f"<unreadable> {attr}"
        return new_dict

    @staticmethod
    def dict_serialize(
        obj: Any, seen: dict[int, str] | None = None, cur: str = "/"
    ) -> Any:
        """Serialize a dictionary by deep serializing its keys and values."""
        new_dict = {}
        for k, v in obj.items():
            key = Serializer.deep_serialize(
                k, seen, cur + f"dict_key<{type(k).__name__}>({k})/"
            )
            new_dict[key] = Serializer.deep_serialize(
                v, seen, cur + f"{key}=<{type(v).__name__}>/"
            )
        return new_dict

    @staticmethod
    def list_serialize(
        obj: Any, seen: dict[int, str] | None = None, cur: str = "/"
    ) -> Any:
        """Serialize a list/tuple/set by deep serializing its elements."""
        new_list = []
        for index, value in enumerate(obj):
            new_list.append(
                Serializer.deep_serialize(
                    value, seen, cur + f"{type(obj).__name__}[{index}]/"
                )
            )
        return new_list

    @staticmethod
    def deep_serialize(
        obj: Any, seen: dict[int, str] | None = None, cur: str = "/"
    ) -> Any:
        """Recursively serialize an object to a JSON-serializable format."""
        if seen is None:
            seen = {}
        obj_id = id(obj)
        if obj_id in seen:
            try:
                value_str = str(obj)
            except Exception:  # noqa: BLE001
                value_str = "<unstringifiable>"
            return f"<Circular reference of a {type(obj).__name__} @ {seen[obj_id]}>: {value_str}"
        seen[obj_id] = f"{cur}"

        # Standard types
        if isinstance(obj, (str, int, float, bool, type(None))):
            return obj
        # bytes
        if isinstance(obj, bytes):
            try:
                res = obj.decode(encoding="utf-8")
            except Exception:  # noqa: BLE001
                res = f"<undecodable bytes>: {obj.hex().upper()}"
            return res
        # dict
        if isinstance(obj, dict):
            return Serializer.dict_serialize(obj, seen, cur)
        # list/tuple/set
        if isinstance(obj, (list, tuple, set)):
            return Serializer.list_serialize(obj, seen, cur)
        # Custom object
        return Serializer.obj_serialize(obj, seen, cur)


def hash_email(message: Any) -> str:
    """Generate a hash of an email for deduplication.

    TODO: Implement email hashing by Message-ID.
    """
    logger.debug("Hashing email for deduplication")
    return ""


def normalize_path(path: str) -> str:
    """Normalize a file system path.

    TODO: Implement path normalization.
    """
    return path
