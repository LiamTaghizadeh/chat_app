#!/usr/bin/env python3
"""
P2P Chat — Professional Peer-to-Peer Messenger
Each user is both server and client.
Supports text, voice messages, direct rooms and groups.
Works on localhost and over the internet with port forwarding.
"""

import sys
from pathlib import Path

# Ensure project root is on path
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main():
    try:
        from ui.app import ChatApp
    except ImportError as e:
        print("خطا در بارگذاری رابط کاربری:", e)
        print("مطمئن شوید داخل پوشه p2p_chat هستید و وابستگی‌ها نصب‌اند.")
        sys.exit(1)

    app = ChatApp()
    app.run()


if __name__ == "__main__":
    main()
