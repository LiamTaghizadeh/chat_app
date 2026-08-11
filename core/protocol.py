"""
Binary framing protocol for P2P Chat.

Frame format:
  [4 bytes big-endian length][1 byte type][payload]

Types:
  0x01  JSON control / text message
  0x02  Binary voice chunk / voice message
  0x03  File / attachment (future)
"""

from __future__ import annotations

import json
import struct
from enum import IntEnum
from typing import Any, Dict, Optional, Tuple


class MessageType(IntEnum):
    JSON = 0x01
    VOICE = 0x02
    FILE = 0x03


class Protocol:
    """Encode / decode framed messages."""

    HEADER = struct.Struct("!IB")  # length (4) + type (1)  — length includes type byte

    @staticmethod
    def pack_json(data: Dict[str, Any]) -> bytes:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        length = 1 + len(payload)
        return Protocol.HEADER.pack(length, MessageType.JSON) + payload

    @staticmethod
    def pack_voice(data: bytes, meta: Optional[Dict[str, Any]] = None) -> bytes:
        """
        Voice frame: optional JSON meta header (length-prefixed) + raw audio bytes.
        For simplicity we send pure PCM / WAV bytes; meta is put in a preceding JSON frame.
        """
        length = 1 + len(data)
        return Protocol.HEADER.pack(length, MessageType.VOICE) + data

    @staticmethod
    def pack_file(data: bytes) -> bytes:
        length = 1 + len(data)
        return Protocol.HEADER.pack(length, MessageType.FILE) + data

    @staticmethod
    def unpack_header(header: bytes) -> Tuple[int, int]:
        if len(header) < 5:
            raise ValueError("Incomplete header")
        length, msg_type = Protocol.HEADER.unpack(header[:5])
        return length, msg_type

    @staticmethod
    def parse_json(payload: bytes) -> Dict[str, Any]:
        return json.loads(payload.decode("utf-8"))


# Convenient message builders -------------------------------------------------

def make_hello(username: str, peer_id: str, listen_port: int) -> Dict[str, Any]:
    return {
        "type": "hello",
        "username": username,
        "peer_id": peer_id,
        "listen_port": listen_port,
        "version": "1.0",
    }


def make_text(room_id: str, sender: str, text: str, msg_id: str, timestamp: float) -> Dict[str, Any]:
    return {
        "type": "text",
        "room_id": room_id,
        "sender": sender,
        "text": text,
        "msg_id": msg_id,
        "ts": timestamp,
    }


def make_voice_meta(room_id: str, sender: str, msg_id: str, timestamp: float,
                    duration: float, sample_rate: int, channels: int) -> Dict[str, Any]:
    return {
        "type": "voice_meta",
        "room_id": room_id,
        "sender": sender,
        "msg_id": msg_id,
        "ts": timestamp,
        "duration": duration,
        "sample_rate": sample_rate,
        "channels": channels,
        "format": "pcm16",
    }


def make_room_invite(room_id: str, room_name: str, is_group: bool, creator: str) -> Dict[str, Any]:
    return {
        "type": "room_invite",
        "room_id": room_id,
        "room_name": room_name,
        "is_group": is_group,
        "creator": creator,
    }


def make_join_room(room_id: str, username: str) -> Dict[str, Any]:
    return {
        "type": "join_room",
        "room_id": room_id,
        "username": username,
    }


def make_leave_room(room_id: str, username: str) -> Dict[str, Any]:
    return {
        "type": "leave_room",
        "room_id": room_id,
        "username": username,
    }


def make_peer_list(room_id: str, peers: list) -> Dict[str, Any]:
    return {
        "type": "peer_list",
        "room_id": room_id,
        "peers": peers,
    }


def make_typing(room_id: str, username: str, is_typing: bool) -> Dict[str, Any]:
    return {
        "type": "typing",
        "room_id": room_id,
        "username": username,
        "is_typing": is_typing,
    }


def make_ack(msg_id: str) -> Dict[str, Any]:
    return {
        "type": "ack",
        "msg_id": msg_id,
    }
