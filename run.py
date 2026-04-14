"""
Entry point — use this instead of running app.py directly.

    python3 run.py

Uses socketio.run() so WebSocket upgrades work correctly.
"""

import os
from dotenv import load_dotenv

load_dotenv()

from app import app, socketio          # noqa: E402 — must load .env first
from switch import switch              # noqa: E402

if __name__ == "__main__":
    host = os.getenv("FLASK_HOST", "0.0.0.0")
    port = int(os.getenv("FLASK_PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "False").strip().lower() in ("true", "1", "yes")

    switch.start()

    print(f"\n  WiFi Blockchain running")
    print(f"  Admin dashboard : http://{host}:{port}/admin")
    print(f"  Phone chat UI   : http://{host}:{port}/client")
    print(f"  API base        : http://{host}:{port}/api\n")

    try:
        socketio.run(app, host=host, port=port, debug=debug, allow_unsafe_werkzeug=True)
    finally:
        switch.stop()
