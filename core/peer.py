"""
PeerNode – each user runs both a TCP server and can open client connections.
Supports 1:1 direct rooms and multi-peer group rooms (mesh).
"""

from __future__ import annotations

import socket
import struct
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from . import protocol as proto
from .protocol import MessageType, Protocol
from .storage import Storage


class Connection:
    """One TCP connection to a remote peer."""

    def __init__(self, sock: socket.socket, addr: Tuple[str, int], peer_id: str = ""):
        self.sock = sock
        self.addr = addr
        self.peer_id = peer_id
        self.username = ""
        self.lock = threading.Lock()
        self.alive = True

    def send(self, data: bytes) -> bool:
        if not self.alive:
            return False
        try:
            with self.lock:
                self.sock.sendall(data)
            return True
        except Exception:
            self.alive = False
            return False

    def close(self) -> None:
        self.alive = False
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass


class PeerNode:
    """
    Full-duplex P2P node.

    Callbacks (set by UI):
      on_text(room_id, sender, text, msg_id, ts)
      on_voice(room_id, sender, wav_bytes, msg_id, ts)
      on_peer_joined(room_id, username, peer_id)
      on_peer_left(room_id, username, peer_id)
      on_status(message: str)
      on_connection_change(connected: bool, info: str)
    """

    def __init__(
        self,
        username: str,
        listen_port: int = 5050,
        storage: Optional[Storage] = None,
    ):
        self.username = username
        self.listen_port = listen_port
        self.peer_id = str(uuid.uuid4())
        self.storage = storage or Storage()

        self._server_sock: Optional[socket.socket] = None
        self._server_thread: Optional[threading.Thread] = None
        self._running = False

        # peer_id -> Connection
        self.connections: Dict[str, Connection] = {}
        # also index by (ip, port) for incoming before hello
        self._pending: List[Connection] = []
        self._conn_lock = threading.Lock()

        # room_id -> set of peer_ids that are in that room (from our perspective)
        self.rooms: Dict[str, Set[str]] = {}
        self._rooms_lock = threading.Lock()

        # Callbacks
        self.on_text: Optional[Callable] = None
        self.on_voice: Optional[Callable] = None
        self.on_peer_joined: Optional[Callable] = None
        self.on_peer_left: Optional[Callable] = None
        self.on_status: Optional[Callable] = None
        self.on_connection_change: Optional[Callable] = None

        # Persist our own identity
        self.storage.set_setting("username", username)
        self.storage.set_setting("peer_id", self.peer_id)

    # ── Lifecycle ─────────────────────────────────────────────

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind(("0.0.0.0", self.listen_port))
        self._server_sock.listen(20)
        self._server_sock.settimeout(1.0)
        self._server_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._server_thread.start()
        self._status(f"در حال گوش دادن روی پورت {self.listen_port}")

    def stop(self) -> None:
        self._running = False
        with self._conn_lock:
            for c in list(self.connections.values()):
                c.close()
            self.connections.clear()
            for c in self._pending:
                c.close()
            self._pending.clear()
        if self._server_sock:
            try:
                self._server_sock.close()
            except Exception:
                pass
        self._status("نود متوقف شد")

    def _status(self, msg: str) -> None:
        if self.on_status:
            self.on_status(msg)

    # ── Accept incoming ───────────────────────────────────────

    def _accept_loop(self) -> None:
        while self._running:
            try:
                client, addr = self._server_sock.accept()
                client.settimeout(60.0)
                conn = Connection(client, addr)
                with self._conn_lock:
                    self._pending.append(conn)
                t = threading.Thread(
                    target=self._handle_connection, args=(conn,), daemon=True
                )
                t.start()
                self._status(f"اتصال ورودی از {addr[0]}:{addr[1]}")
            except socket.timeout:
                continue
            except Exception:
                if self._running:
                    time.sleep(0.2)

    # ── Outgoing connect ──────────────────────────────────────

    def connect_to(self, host: str, port: int, timeout: float = 8.0) -> bool:
        """Connect to a remote peer. Returns True on success."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((host, port))
            sock.settimeout(60.0)
            conn = Connection(sock, (host, port))
            # Send hello immediately
            hello = proto.make_hello(self.username, self.peer_id, self.listen_port)
            if not conn.send(Protocol.pack_json(hello)):
                conn.close()
                return False
            with self._conn_lock:
                self._pending.append(conn)
            t = threading.Thread(
                target=self._handle_connection, args=(conn,), daemon=True
            )
            t.start()
            self._status(f"متصل شد به {host}:{port}")
            if self.on_connection_change:
                self.on_connection_change(True, f"{host}:{port}")
            return True
        except Exception as e:
            self._status(f"خطا در اتصال به {host}:{port} → {e}")
            return False

    # ── Connection handler ────────────────────────────────────

    def _handle_connection(self, conn: Connection) -> None:
        sock = conn.sock
        buffer = b""
        try:
            while self._running and conn.alive:
                try:
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    buffer += chunk
                    while len(buffer) >= 5:
                        length, msg_type = Protocol.unpack_header(buffer[:5])
                        if length < 1 or length > 16 * 1024 * 1024:
                            raise ValueError("Invalid frame length")
                        total = 4 + length  # length field + payload (incl. type)
                        if len(buffer) < total:
                            break
                        frame = buffer[5:total]
                        buffer = buffer[total:]
                        self._dispatch(conn, msg_type, frame)
                except socket.timeout:
                    continue
                except Exception:
                    break
        finally:
            self._on_disconnect(conn)

    def _dispatch(self, conn: Connection, msg_type: int, payload: bytes) -> None:
        if msg_type == MessageType.JSON:
            try:
                data = Protocol.parse_json(payload)
            except Exception:
                return
            self._handle_json(conn, data)
        elif msg_type == MessageType.VOICE:
            self._handle_voice_raw(conn, payload)
        # FILE reserved

    def _handle_json(self, conn: Connection, data: Dict[str, Any]) -> None:
        t = data.get("type")

        if t == "hello":
            conn.peer_id = data.get("peer_id", "")
            conn.username = data.get("username", "unknown")
            remote_port = data.get("listen_port")
            with self._conn_lock:
                if conn in self._pending:
                    self._pending.remove(conn)
                self.connections[conn.peer_id] = conn
            self.storage.upsert_contact(
                conn.peer_id,
                conn.username,
                conn.addr[0],
                remote_port or conn.addr[1],
            )
            # Reply with our hello if we are the server side (incoming)
            # (outgoing already sent hello)
            # Always send hello back to complete handshake
            hello = proto.make_hello(self.username, self.peer_id, self.listen_port)
            conn.send(Protocol.pack_json(hello))
            self._status(f"همتا شناسایی شد: {conn.username} ({conn.peer_id[:8]}…)")
            if self.on_connection_change:
                self.on_connection_change(True, f"{conn.username}@{conn.addr[0]}")
            return

        if t == "text":
            room_id = data.get("room_id", "")
            sender = data.get("sender", conn.username or "?")
            text = data.get("text", "")
            msg_id = data.get("msg_id", str(uuid.uuid4()))
            ts = data.get("ts", time.time())
            # Persist on our side
            self.storage.save_message(room_id, sender, "text", text, msg_id, ts, True)
            # ACK
            conn.send(Protocol.pack_json(proto.make_ack(msg_id)))
            if self.on_text:
                self.on_text(room_id, sender, text, msg_id, ts)
            return

        if t == "voice_meta":
            # Store meta; actual audio comes as VOICE frame right after
            conn._pending_voice_meta = data  # type: ignore
            return

        if t == "room_invite":
            room_id = data["room_id"]
            name = data.get("room_name", "Room")
            is_group = bool(data.get("is_group", False))
            self.storage.create_room(name, is_group, room_id)
            with self._rooms_lock:
                self.rooms.setdefault(room_id, set()).add(conn.peer_id)
            self.storage.add_member(room_id, conn.peer_id, conn.username)
            self.storage.add_member(room_id, self.peer_id, self.username)
            # Accept & join
            conn.send(Protocol.pack_json(proto.make_join_room(room_id, self.username)))
            if self.on_peer_joined:
                self.on_peer_joined(room_id, conn.username, conn.peer_id)
            self._status(f"دعوت به روم «{name}» پذیرفته شد")
            return

        if t == "join_room":
            room_id = data.get("room_id", "")
            username = data.get("username", conn.username)
            with self._rooms_lock:
                self.rooms.setdefault(room_id, set()).add(conn.peer_id)
            self.storage.add_member(room_id, conn.peer_id, username)
            if self.on_peer_joined:
                self.on_peer_joined(room_id, username, conn.peer_id)
            return

        if t == "leave_room":
            room_id = data.get("room_id", "")
            username = data.get("username", conn.username)
            with self._rooms_lock:
                if room_id in self.rooms:
                    self.rooms[room_id].discard(conn.peer_id)
            if self.on_peer_left:
                self.on_peer_left(room_id, username, conn.peer_id)
            return

        if t == "ack":
            msg_id = data.get("msg_id")
            if msg_id:
                self.storage.mark_delivered(msg_id)
            return

        if t == "typing":
            # UI can show typing indicator
            return

    def _handle_voice_raw(self, conn: Connection, payload: bytes) -> None:
        meta = getattr(conn, "_pending_voice_meta", None)
        if not meta:
            return
        conn._pending_voice_meta = None  # type: ignore
        room_id = meta.get("room_id", "")
        sender = meta.get("sender", conn.username or "?")
        msg_id = meta.get("msg_id", str(uuid.uuid4()))
        ts = meta.get("ts", time.time())

        # Save voice file to disk
        voice_dir = Path_home_voice()
        voice_dir.mkdir(parents=True, exist_ok=True)
        path = voice_dir / f"{msg_id}.wav"
        path.write_bytes(payload)

        self.storage.save_message(
            room_id, sender, "voice", str(path), msg_id, ts, True
        )
        if self.on_voice:
            self.on_voice(room_id, sender, payload, msg_id, ts)

    def _on_disconnect(self, conn: Connection) -> None:
        with self._conn_lock:
            if conn in self._pending:
                self._pending.remove(conn)
            if conn.peer_id and conn.peer_id in self.connections:
                del self.connections[conn.peer_id]
        conn.close()
        if conn.username:
            self._status(f"قطع شد: {conn.username}")
            # notify rooms
            with self._rooms_lock:
                for rid, members in list(self.rooms.items()):
                    if conn.peer_id in members:
                        members.discard(conn.peer_id)
                        if self.on_peer_left:
                            self.on_peer_left(rid, conn.username, conn.peer_id)
        if self.on_connection_change:
            self.on_connection_change(False, conn.username or str(conn.addr))

    # ── High-level API used by UI ─────────────────────────────

    def create_direct_room(self, peer_id: str, peer_username: str) -> str:
        """Create a 1:1 room and invite the peer."""
        room_name = f"{self.username} ↔ {peer_username}"
        room_id = self.storage.create_room(room_name, is_group=False)
        self.storage.add_member(room_id, self.peer_id, self.username)
        self.storage.add_member(room_id, peer_id, peer_username)
        with self._rooms_lock:
            self.rooms.setdefault(room_id, set()).add(peer_id)

        invite = proto.make_room_invite(room_id, room_name, False, self.username)
        self._send_to_peer(peer_id, Protocol.pack_json(invite))
        return room_id

    def create_group_room(self, name: str, peer_ids: List[str]) -> str:
        room_id = self.storage.create_room(name, is_group=True)
        self.storage.add_member(room_id, self.peer_id, self.username)
        with self._rooms_lock:
            self.rooms[room_id] = set()
        for pid in peer_ids:
            contact = self.storage.get_contact(pid)
            uname = contact["username"] if contact else pid[:8]
            self.storage.add_member(room_id, pid, uname)
            with self._rooms_lock:
                self.rooms[room_id].add(pid)
            invite = proto.make_room_invite(room_id, name, True, self.username)
            self._send_to_peer(pid, Protocol.pack_json(invite))
        return room_id

    def send_text(self, room_id: str, text: str) -> Optional[str]:
        msg_id = str(uuid.uuid4())
        ts = time.time()
        self.storage.save_message(room_id, self.username, "text", text, msg_id, ts)
        payload = Protocol.pack_json(
            proto.make_text(room_id, self.username, text, msg_id, ts)
        )
        self._broadcast_room(room_id, payload)
        return msg_id

    def send_voice(self, room_id: str, wav_bytes: bytes, duration: float = 0.0) -> Optional[str]:
        msg_id = str(uuid.uuid4())
        ts = time.time()
        # Save locally
        voice_dir = Path_home_voice()
        voice_dir.mkdir(parents=True, exist_ok=True)
        path = voice_dir / f"{msg_id}.wav"
        path.write_bytes(wav_bytes)
        self.storage.save_message(
            room_id, self.username, "voice", str(path), msg_id, ts
        )

        meta = proto.make_voice_meta(
            room_id,
            self.username,
            msg_id,
            ts,
            duration,
            16000,
            1,
        )
        self._broadcast_room(room_id, Protocol.pack_json(meta))
        self._broadcast_room(room_id, Protocol.pack_voice(wav_bytes))
        return msg_id

    def _send_to_peer(self, peer_id: str, data: bytes) -> bool:
        with self._conn_lock:
            conn = self.connections.get(peer_id)
        if conn:
            return conn.send(data)
        return False

    def _broadcast_room(self, room_id: str, data: bytes) -> None:
        with self._rooms_lock:
            members = list(self.rooms.get(room_id, set()))
        for pid in members:
            self._send_to_peer(pid, data)

    def get_connected_peers(self) -> List[Dict[str, str]]:
        with self._conn_lock:
            return [
                {
                    "peer_id": pid,
                    "username": c.username,
                    "addr": f"{c.addr[0]}:{c.addr[1]}",
                }
                for pid, c in self.connections.items()
                if c.alive
            ]


def Path_home_voice():
    from pathlib import Path
    p = Path.home() / ".p2p_chat" / "voice"
    return p
