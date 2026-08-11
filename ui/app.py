"""
Professional Tkinter GUI for P2P Chat.
Dark modern theme, RTL-friendly for Persian users.
"""

from __future__ import annotations

import socket
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, simpledialog, ttk
from typing import Optional

from core.peer import PeerNode
from core.storage import Storage
from core.voice import VoiceEngine


# ── Color palette (dark neo style) ────────────────────────────
BG = "#0f0f12"
BG2 = "#1a1a22"
BG3 = "#242430"
ACCENT = "#6c5ce7"
ACCENT2 = "#a29bfe"
GREEN = "#00b894"
RED = "#ff6b6b"
TEXT = "#f5f6fa"
TEXT_DIM = "#b2bec3"
BORDER = "#2d2d3a"
ME_BUBBLE = "#6c5ce7"
OTHER_BUBBLE = "#2d3436"


class ChatApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("P2P Chat — حرفه‌ای")
        self.root.geometry("1100x700")
        self.root.minsize(900, 550)
        self.root.configure(bg=BG)

        self.storage = Storage()
        saved_name = self.storage.get_setting("username", "")
        self.username = saved_name or self._ask_username()
        if not self.username:
            self.root.destroy()
            return

        self.listen_port = int(self.storage.get_setting("listen_port", "5050") or "5050")
        self.node = PeerNode(self.username, self.listen_port, self.storage)
        self.voice = VoiceEngine()

        self.current_room_id: Optional[str] = None
        self._recording = False

        # Wire callbacks (thread-safe via root.after)
        self.node.on_text = self._on_text
        self.node.on_voice = self._on_voice
        self.node.on_peer_joined = self._on_peer_joined
        self.node.on_peer_left = self._on_peer_left
        self.node.on_status = self._on_status
        self.node.on_connection_change = self._on_conn_change

        self._build_ui()
        self.node.start()
        self._refresh_rooms()
        self._refresh_peers()
        self._set_status(f"آماده | پورت {self.listen_port} | کاربر: {self.username}")

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _ask_username(self) -> str:
        name = simpledialog.askstring(
            "نام کاربری",
            "نام کاربری خود را وارد کنید:",
            parent=self.root,
        )
        return (name or "").strip() or "User"

    # ── UI Construction ───────────────────────────────────────

    def _build_ui(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure(
            "TButton",
            background=ACCENT,
            foreground=TEXT,
            borderwidth=0,
            focuscolor=ACCENT,
            padding=6,
        )
        style.map("TButton", background=[("active", ACCENT2)])
        style.configure(
            "Treeview",
            background=BG2,
            foreground=TEXT,
            fieldbackground=BG2,
            borderwidth=0,
            rowheight=28,
        )
        style.configure(
            "Treeview.Heading",
            background=BG3,
            foreground=TEXT_DIM,
            borderwidth=0,
        )
        style.map("Treeview", background=[("selected", ACCENT)])

        # Main layout: left sidebar | chat area | right peers
        main = tk.Frame(self.root, bg=BG)
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # ── Left: Rooms ───────────────────────────────────────
        left = tk.Frame(main, bg=BG2, width=220)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 6))
        left.pack_propagate(False)

        tk.Label(
            left, text="روم‌ها", bg=BG2, fg=TEXT, font=("Segoe UI", 12, "bold")
        ).pack(anchor="w", padx=12, pady=(12, 4))

        btn_frame = tk.Frame(left, bg=BG2)
        btn_frame.pack(fill=tk.X, padx=8, pady=4)
        tk.Button(
            btn_frame,
            text="+ روم مستقیم",
            command=self._new_direct_room,
            bg=ACCENT,
            fg=TEXT,
            relief=tk.FLAT,
            font=("Segoe UI", 9),
            cursor="hand2",
        ).pack(fill=tk.X, pady=2)
        tk.Button(
            btn_frame,
            text="+ گروه جدید",
            command=self._new_group_room,
            bg=BG3,
            fg=TEXT,
            relief=tk.FLAT,
            font=("Segoe UI", 9),
            cursor="hand2",
        ).pack(fill=tk.X, pady=2)

        self.room_list = tk.Listbox(
            left,
            bg=BG2,
            fg=TEXT,
            selectbackground=ACCENT,
            selectforeground=TEXT,
            relief=tk.FLAT,
            highlightthickness=0,
            font=("Segoe UI", 10),
            activestyle="none",
        )
        self.room_list.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.room_list.bind("<<ListboxSelect>>", self._on_room_select)

        # ── Center: Chat ──────────────────────────────────────
        center = tk.Frame(main, bg=BG)
        center.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.chat_title = tk.Label(
            center,
            text="یک روم انتخاب کنید",
            bg=BG,
            fg=TEXT,
            font=("Segoe UI", 13, "bold"),
            anchor="w",
        )
        self.chat_title.pack(fill=tk.X, padx=4, pady=(0, 4))

        # Messages area with scrollbar
        chat_frame = tk.Frame(center, bg=BG2)
        chat_frame.pack(fill=tk.BOTH, expand=True)

        self.chat_canvas = tk.Canvas(chat_frame, bg=BG2, highlightthickness=0)
        scrollbar = ttk.Scrollbar(chat_frame, orient="vertical", command=self.chat_canvas.yview)
        self.messages_frame = tk.Frame(self.chat_canvas, bg=BG2)

        self.messages_frame.bind(
            "<Configure>",
            lambda e: self.chat_canvas.configure(scrollregion=self.chat_canvas.bbox("all")),
        )
        self._chat_window = self.chat_canvas.create_window(
            (0, 0), window=self.messages_frame, anchor="nw"
        )
        self.chat_canvas.configure(yscrollcommand=scrollbar.set)
        self.chat_canvas.bind(
            "<Configure>",
            lambda e: self.chat_canvas.itemconfig(self._chat_window, width=e.width),
        )

        self.chat_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Input bar
        input_bar = tk.Frame(center, bg=BG3, pady=6)
        input_bar.pack(fill=tk.X, pady=(6, 0))

        self.entry = tk.Entry(
            input_bar,
            bg=BG2,
            fg=TEXT,
            insertbackground=TEXT,
            relief=tk.FLAT,
            font=("Segoe UI", 11),
        )
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 4), ipady=8)
        self.entry.bind("<Return>", lambda e: self._send_text())

        self.btn_voice = tk.Button(
            input_bar,
            text="🎙",
            command=self._toggle_record,
            bg=BG2,
            fg=TEXT,
            relief=tk.FLAT,
            font=("Segoe UI", 14),
            width=3,
            cursor="hand2",
        )
        self.btn_voice.pack(side=tk.LEFT, padx=2)

        tk.Button(
            input_bar,
            text="ارسال",
            command=self._send_text,
            bg=ACCENT,
            fg=TEXT,
            relief=tk.FLAT,
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
            padx=12,
        ).pack(side=tk.LEFT, padx=(2, 8))

        # ── Right: Peers + Connect ─────────────────────────────
        right = tk.Frame(main, bg=BG2, width=240)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(6, 0))
        right.pack_propagate(False)

        tk.Label(
            right, text="همتاها (متصل)", bg=BG2, fg=TEXT, font=("Segoe UI", 12, "bold")
        ).pack(anchor="w", padx=12, pady=(12, 4))

        self.peer_list = tk.Listbox(
            right,
            bg=BG2,
            fg=TEXT,
            selectbackground=ACCENT,
            relief=tk.FLAT,
            highlightthickness=0,
            font=("Segoe UI", 9),
            height=8,
            activestyle="none",
        )
        self.peer_list.pack(fill=tk.X, padx=8, pady=4)

        # Connect form
        conn_frame = tk.LabelFrame(
            right, text="اتصال مستقیم", bg=BG2, fg=TEXT_DIM, font=("Segoe UI", 9)
        )
        conn_frame.pack(fill=tk.X, padx=8, pady=10)

        tk.Label(conn_frame, text="IP / Host:", bg=BG2, fg=TEXT_DIM, font=("Segoe UI", 8)).pack(
            anchor="w", padx=6
        )
        self.host_entry = tk.Entry(
            conn_frame, bg=BG3, fg=TEXT, insertbackground=TEXT, relief=tk.FLAT
        )
        self.host_entry.insert(0, "127.0.0.1")
        self.host_entry.pack(fill=tk.X, padx=6, pady=2, ipady=3)

        tk.Label(conn_frame, text="Port:", bg=BG2, fg=TEXT_DIM, font=("Segoe UI", 8)).pack(
            anchor="w", padx=6
        )
        self.port_entry = tk.Entry(
            conn_frame, bg=BG3, fg=TEXT, insertbackground=TEXT, relief=tk.FLAT
        )
        self.port_entry.insert(0, "5050")
        self.port_entry.pack(fill=tk.X, padx=6, pady=2, ipady=3)

        tk.Button(
            conn_frame,
            text="اتصال",
            command=self._do_connect,
            bg=GREEN,
            fg=TEXT,
            relief=tk.FLAT,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
        ).pack(fill=tk.X, padx=6, pady=8)

        # Local info
        info = tk.LabelFrame(
            right, text="اطلاعات من", bg=BG2, fg=TEXT_DIM, font=("Segoe UI", 9)
        )
        info.pack(fill=tk.X, padx=8, pady=4)
        self.my_info = tk.Label(
            info,
            text=f"نام: {self.username}\nپورت: {self.listen_port}\nIP محلی: {self._local_ip()}",
            bg=BG2,
            fg=TEXT,
            font=("Consolas", 9),
            justify=tk.LEFT,
        )
        self.my_info.pack(anchor="w", padx=8, pady=6)

        tk.Button(
            right,
            text="تغییر پورت",
            command=self._change_port,
            bg=BG3,
            fg=TEXT,
            relief=tk.FLAT,
            font=("Segoe UI", 8),
            cursor="hand2",
        ).pack(fill=tk.X, padx=8, pady=4)

        # Status bar
        self.status_var = tk.StringVar(value="آماده")
        status = tk.Label(
            self.root,
            textvariable=self.status_var,
            bg=BG3,
            fg=TEXT_DIM,
            font=("Segoe UI", 8),
            anchor="w",
            padx=10,
        )
        status.pack(side=tk.BOTTOM, fill=tk.X)

        if not self.voice.enabled:
            self.btn_voice.configure(state=tk.DISABLED)
            self._set_status("ویس غیرفعال (pyaudio نصب نیست) — فقط متن")

    # ── Helpers ───────────────────────────────────────────────

    def _local_ip(self) -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def _set_status(self, msg: str) -> None:
        self.status_var.set(msg)

    def _ts_fmt(self, ts: float) -> str:
        return datetime.fromtimestamp(ts).strftime("%H:%M")

    # ── Rooms ─────────────────────────────────────────────────

    def _refresh_rooms(self) -> None:
        self.room_list.delete(0, tk.END)
        self._room_ids = []
        for r in self.storage.list_rooms():
            flag = "👥" if r["is_group"] else "💬"
            self.room_list.insert(tk.END, f" {flag}  {r['name']}")
            self._room_ids.append(r["room_id"])

    def _on_room_select(self, event=None) -> None:
        sel = self.room_list.curselection()
        if not sel:
            return
        idx = sel[0]
        self.current_room_id = self._room_ids[idx]
        room = self.storage.get_room(self.current_room_id)
        if room:
            self.chat_title.configure(text=room["name"])
        self._load_history()

    def _load_history(self) -> None:
        for w in self.messages_frame.winfo_children():
            w.destroy()
        if not self.current_room_id:
            return
        msgs = self.storage.get_messages(self.current_room_id, limit=150)
        for m in msgs:
            self._append_bubble(
                m["sender"],
                m["content"],
                m["msg_type"],
                m["timestamp"],
                is_me=(m["sender"] == self.username),
            )
        self.root.after(50, lambda: self.chat_canvas.yview_moveto(1.0))

    def _append_bubble(
        self,
        sender: str,
        content: str,
        msg_type: str,
        ts: float,
        is_me: bool = False,
    ) -> None:
        row = tk.Frame(self.messages_frame, bg=BG2)
        row.pack(fill=tk.X, padx=10, pady=3)

        bubble_bg = ME_BUBBLE if is_me else OTHER_BUBBLE
        anchor = "e" if is_me else "w"

        bubble = tk.Frame(row, bg=bubble_bg, padx=10, pady=6)
        bubble.pack(anchor=anchor)

        if not is_me:
            tk.Label(
                bubble,
                text=sender,
                bg=bubble_bg,
                fg=ACCENT2,
                font=("Segoe UI", 8, "bold"),
            ).pack(anchor="w")

        if msg_type == "voice":
            def play(path=content):
                self.voice.play_file(path)

            btn = tk.Button(
                bubble,
                text="▶ پخش ویس",
                command=play,
                bg=bubble_bg,
                fg=TEXT,
                relief=tk.FLAT,
                font=("Segoe UI", 9),
                cursor="hand2",
            )
            btn.pack(anchor="w")
        else:
            tk.Label(
                bubble,
                text=content,
                bg=bubble_bg,
                fg=TEXT,
                font=("Segoe UI", 10),
                wraplength=420,
                justify=tk.LEFT if not is_me else tk.RIGHT,
            ).pack(anchor="w")

        tk.Label(
            bubble,
            text=self._ts_fmt(ts),
            bg=bubble_bg,
            fg=TEXT_DIM,
            font=("Segoe UI", 7),
        ).pack(anchor="e")

    # ── Send ──────────────────────────────────────────────────

    def _send_text(self) -> None:
        text = self.entry.get().strip()
        if not text or not self.current_room_id:
            return
        self.entry.delete(0, tk.END)
        self.node.send_text(self.current_room_id, text)
        self._append_bubble(self.username, text, "text", time.time(), is_me=True)
        self.chat_canvas.yview_moveto(1.0)

    def _toggle_record(self) -> None:
        if not self.voice.enabled:
            messagebox.showinfo("ویس", "برای ویس باید pyaudio نصب باشد.\npip install pyaudio")
            return
        if not self.current_room_id:
            messagebox.showwarning("روم", "اول یک روم انتخاب کنید")
            return

        if not self._recording:
            ok = self.voice.start_recording()
            if ok:
                self._recording = True
                self.btn_voice.configure(text="⏹", bg=RED)
                self._set_status("در حال ضبط ویس… دوباره کلیک کنید تا بفرستید")
        else:
            self._recording = False
            self.btn_voice.configure(text="🎙", bg=BG2)
            wav = self.voice.stop_recording()
            if wav:
                self.node.send_voice(self.current_room_id, wav)
                # Save path already done inside send_voice; show bubble
                # We need the path – re-fetch last message or just show generic
                self._append_bubble(
                    self.username, "(ویس شما)", "text", time.time(), is_me=True
                )
                self._set_status("ویس ارسال شد")
            else:
                self._set_status("ضبط ویس ناموفق بود")

    # ── Connect & Rooms creation ──────────────────────────────

    def _do_connect(self) -> None:
        host = self.host_entry.get().strip()
        try:
            port = int(self.port_entry.get().strip())
        except ValueError:
            messagebox.showerror("خطا", "پورت نامعتبر")
            return
        self._set_status(f"در حال اتصال به {host}:{port}…")

        def work():
            ok = self.node.connect_to(host, port)
            self.root.after(0, lambda: self._after_connect(ok, host, port))

        threading.Thread(target=work, daemon=True).start()

    def _after_connect(self, ok: bool, host: str, port: int) -> None:
        if ok:
            self._set_status(f"متصل به {host}:{port}")
            self.root.after(500, self._refresh_peers)
        else:
            messagebox.showerror("اتصال", f"نتوانست به {host}:{port} وصل شود")

    def _refresh_peers(self) -> None:
        self.peer_list.delete(0, tk.END)
        self._peer_ids = []
        for p in self.node.get_connected_peers():
            self.peer_list.insert(tk.END, f" 🟢 {p['username']}  ({p['addr']})")
            self._peer_ids.append(p["peer_id"])
        # also show known contacts offline
        online_ids = set(self._peer_ids)
        for c in self.storage.list_contacts():
            if c["peer_id"] not in online_ids:
                self.peer_list.insert(
                    tk.END, f" ⚪ {c['username']}  (آفلاین)"
                )
                self._peer_ids.append(c["peer_id"])

    def _new_direct_room(self) -> None:
        peers = self.node.get_connected_peers()
        if not peers:
            messagebox.showinfo(
                "روم مستقیم",
                "ابتدا به یک همتا متصل شوید (از پنل سمت راست).",
            )
            return
        # Simple: pick first selected peer or ask
        sel = self.peer_list.curselection()
        if not sel:
            messagebox.showinfo("انتخاب", "از لیست همتاها یکی را انتخاب کنید")
            return
        idx = sel[0]
        if idx >= len(self._peer_ids):
            return
        pid = self._peer_ids[idx]
        # find username
        peers_map = {p["peer_id"]: p["username"] for p in peers}
        uname = peers_map.get(pid)
        if not uname:
            contact = self.storage.get_contact(pid)
            uname = contact["username"] if contact else "Peer"
            messagebox.showwarning("آفلاین", "این همتا الان آنلاین نیست")
            return

        room_id = self.node.create_direct_room(pid, uname)
        self._refresh_rooms()
        # select it
        for i, rid in enumerate(self._room_ids):
            if rid == room_id:
                self.room_list.selection_clear(0, tk.END)
                self.room_list.selection_set(i)
                self.room_list.event_generate("<<ListboxSelect>>")
                break
        self._set_status(f"روم مستقیم با {uname} ساخته شد")

    def _new_group_room(self) -> None:
        name = simpledialog.askstring("گروه جدید", "نام گروه:", parent=self.root)
        if not name:
            return
        peers = self.node.get_connected_peers()
        if not peers:
            messagebox.showinfo("گروه", "حداقل به یک همتا متصل باشید")
            return
        pids = [p["peer_id"] for p in peers]
        room_id = self.node.create_group_room(name.strip(), pids)
        self._refresh_rooms()
        self._set_status(f"گروه «{name}» ساخته شد و دعوت ارسال شد")

    def _change_port(self) -> None:
        val = simpledialog.askinteger(
            "پورت",
            "پورت گوش‌دادن جدید (نیاز به ری‌استارت):",
            initialvalue=self.listen_port,
            minvalue=1024,
            maxvalue=65535,
            parent=self.root,
        )
        if val:
            self.storage.set_setting("listen_port", str(val))
            messagebox.showinfo(
                "پورت",
                f"پورت به {val} تغییر کرد.\nبرنامه را ببندید و دوباره باز کنید.",
            )

    # ── Network callbacks (marshalled to UI thread) ───────────

    def _on_text(self, room_id, sender, text, msg_id, ts):
        def ui():
            if room_id == self.current_room_id:
                self._append_bubble(sender, text, "text", ts, is_me=False)
                self.chat_canvas.yview_moveto(1.0)
            self._refresh_rooms()
        self.root.after(0, ui)

    def _on_voice(self, room_id, sender, wav_bytes, msg_id, ts):
        def ui():
            # content path is already saved by peer
            path = str(
                __import__("pathlib").Path.home()
                / ".p2p_chat"
                / "voice"
                / f"{msg_id}.wav"
            )
            if room_id == self.current_room_id:
                self._append_bubble(sender, path, "voice", ts, is_me=False)
                self.chat_canvas.yview_moveto(1.0)
            self._refresh_rooms()
        self.root.after(0, ui)

    def _on_peer_joined(self, room_id, username, peer_id):
        def ui():
            self._set_status(f"{username} به روم پیوست")
            self._refresh_peers()
            self._refresh_rooms()
        self.root.after(0, ui)

    def _on_peer_left(self, room_id, username, peer_id):
        def ui():
            self._set_status(f"{username} روم را ترک کرد")
            self._refresh_peers()
        self.root.after(0, ui)

    def _on_status(self, msg):
        self.root.after(0, lambda: self._set_status(msg))

    def _on_conn_change(self, connected, info):
        def ui():
            self._refresh_peers()
            if connected:
                self._set_status(f"متصل: {info}")
            else:
                self._set_status(f"قطع شد: {info}")
        self.root.after(0, ui)

    # ── Close ─────────────────────────────────────────────────

    def _on_close(self) -> None:
        self.node.stop()
        self.voice.close()
        self.storage.close()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()
