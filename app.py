"""
Flask + SocketIO application for the WiFi Blockchain switch.

REST endpoints
--------------
GET  /                          → redirect to /admin
GET  /admin                     → admin dashboard
GET  /client                    → phone chat UI

POST /api/device/connect        body: {mac, metadata?}
POST /api/device/disconnect     body: {mac}
POST /api/device/block          body: {mac}
POST /api/device/allow          body: {mac}
POST /api/message/send          body: {sender, receiver, payload, metadata?}
POST /api/file/send             body: {sender, receiver, filename, content}
POST /api/file/verify           body: {content}

GET  /api/devices               list connected devices
GET  /api/blocked-devices       list blocked MACs
GET  /api/blockchain            full chain dump
GET  /api/blockchain/validate   integrity check
GET  /api/status                overall status

SocketIO events (server → client)
----------------------------------
new_block      broadcast   — fired after every mine
device_update  broadcast   — fired on connect/disconnect/block/allow
new_message    room emit   — fired to receiver's MAC room + 'admin' room
new_file       room emit   — fired to receiver's, sender's, and 'admin' rooms

SocketIO events (client → server)
----------------------------------
join   {mac, role?}  — client joins their MAC room; role='admin' joins admin room
"""

import os
import time
import hashlib
import logging
from flask import Flask, request, jsonify, redirect, render_template, url_for
from flask_socketio import SocketIO, join_room, emit

from switch import switch, SIMULATION_MODE
from persistence import save_chain, load_chain

logger = logging.getLogger("app")

# ------------------------------------------------------------------
# App + SocketIO setup
# ------------------------------------------------------------------

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "wifi-blockchain-dev-secret")

socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# ------------------------------------------------------------------
# Startup: load persisted chain, then monkey-patch mine so every
# future block is auto-saved and broadcast — without touching switch.py
# or blockchain.py.
# ------------------------------------------------------------------

load_chain(switch.blockchain)

_orig_mine = switch.blockchain.mine_pending_transactions


def _mine_save_emit():
    block = _orig_mine()
    save_chain(switch.blockchain)
    socketio.emit("new_block", block.to_dict(), namespace="/")
    return block


switch.blockchain.mine_pending_transactions = _mine_save_emit

# ------------------------------------------------------------------
# Application state (not persisted — resets on restart by design)
# ------------------------------------------------------------------

blocked_devices: set = set()
_start_time: float = time.time()

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _bad(msg: str, code: int = 400):
    return jsonify({"error": msg}), code


def _ok(data, code: int = 200):
    return jsonify(data), code


def _emit_device_update(action: str, mac: str):
    """Broadcast a device-list snapshot plus the blocked set."""
    socketio.emit(
        "device_update",
        {
            "action": action,
            "mac": mac,
            "devices": list(switch.connected_devices.values()),
            "blocked": list(blocked_devices),
        },
        namespace="/",
    )


# ------------------------------------------------------------------
# Template routes
# ------------------------------------------------------------------


@app.route("/")
def index():
    return redirect(url_for("admin_dashboard"))


@app.route("/admin")
def admin_dashboard():
    return render_template("admin.html")


@app.route("/client")
def client_ui():
    return render_template("client.html")


# ------------------------------------------------------------------
# Device endpoints
# ------------------------------------------------------------------


@app.route("/api/device/connect", methods=["POST"])
def device_connect():
    body = request.get_json(silent=True) or {}
    mac = body.get("mac", "").strip()
    if not mac:
        return _bad("'mac' is required")

    info = switch.connect_device(mac, metadata=body.get("metadata"))
    _emit_device_update("connect", mac)
    return _ok({"message": "Device connected", "device": info}, 201)


@app.route("/api/device/disconnect", methods=["POST"])
def device_disconnect():
    body = request.get_json(silent=True) or {}
    mac = body.get("mac", "").strip()
    if not mac:
        return _bad("'mac' is required")

    removed = switch.disconnect_device(mac)
    if not removed:
        return _bad(f"Device '{mac}' not found", 404)

    _emit_device_update("disconnect", mac)
    return _ok({"message": f"Device '{mac}' disconnected"})


@app.route("/api/device/block", methods=["POST"])
def device_block():
    body = request.get_json(silent=True) or {}
    mac = body.get("mac", "").strip()
    if not mac:
        return _bad("'mac' is required")

    blocked_devices.add(mac)

    # Log to blockchain
    switch.blockchain.add_transaction_and_mine(
        {"type": "device_block", "mac": mac}
    )

    _emit_device_update("block", mac)
    logger.info("Device blocked: %s", mac)
    return _ok({"message": f"Device '{mac}' blocked"})


@app.route("/api/device/allow", methods=["POST"])
def device_allow():
    body = request.get_json(silent=True) or {}
    mac = body.get("mac", "").strip()
    if not mac:
        return _bad("'mac' is required")

    blocked_devices.discard(mac)

    switch.blockchain.add_transaction_and_mine(
        {"type": "device_allow", "mac": mac}
    )

    _emit_device_update("allow", mac)
    logger.info("Device allowed: %s", mac)
    return _ok({"message": f"Device '{mac}' allowed"})


# ------------------------------------------------------------------
# Message endpoint
# ------------------------------------------------------------------


@app.route("/api/message/send", methods=["POST"])
def message_send():
    body = request.get_json(silent=True) or {}
    sender = body.get("sender", "").strip()
    receiver = body.get("receiver", "").strip()
    payload = body.get("payload", "").strip()

    if not sender:
        return _bad("'sender' is required")
    if not receiver:
        return _bad("'receiver' is required")
    if not payload:
        return _bad("'payload' is required")

    if sender in blocked_devices:
        return _bad(f"Device '{sender}' is blocked", 403)

    result = switch.route_message(
        sender_mac=sender,
        receiver_mac=receiver,
        payload=payload,
        metadata=body.get("metadata"),
    )

    msg_event = {
        "sender": sender,
        "receiver": receiver,
        "payload": payload,
        "timestamp": result["transaction"]["timestamp"],
        "block_index": result["block_index"],
    }
    # Deliver to receiver's room and the admin room
    socketio.emit("new_message", msg_event, room=receiver, namespace="/")
    socketio.emit("new_message", msg_event, room="admin", namespace="/")

    return _ok({"message": "Message routed and recorded", **result}, 201)


# ------------------------------------------------------------------
# File endpoints
# ------------------------------------------------------------------

_MAX_FILE_BYTES = 500 * 1024  # 500 KB


@app.route("/api/file/send", methods=["POST"])
def file_send():
    body = request.get_json(silent=True) or {}
    sender   = body.get("sender",   "").strip()
    receiver = body.get("receiver", "").strip()
    filename = body.get("filename", "").strip()
    content  = body.get("content",  "")

    if not sender:
        return _bad("'sender' is required")
    if not receiver:
        return _bad("'receiver' is required")
    if not filename:
        return _bad("'filename' is required")
    if not isinstance(content, str):
        return _bad("'content' must be a string")
    if not filename.lower().endswith(".txt"):
        return _bad("Only .txt files are supported", 400)
    if len(content.encode("utf-8")) > _MAX_FILE_BYTES:
        return _bad("File exceeds the 500 KB limit", 413)
    if sender not in switch.connected_devices:
        return _bad(f"Sender '{sender}' is not connected", 404)
    if receiver not in switch.connected_devices:
        return _bad(f"Receiver '{receiver}' is not connected", 404)
    if sender in blocked_devices:
        return _bad(f"Device '{sender}' is blocked", 403)

    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    size = len(content.encode("utf-8"))

    result = switch.route_file(
        sender=sender,
        receiver=receiver,
        filename=filename,
        content=content,
        content_hash=content_hash,
        size=size,
    )

    file_event = {
        "sender":       sender,
        "receiver":     receiver,
        "filename":     filename,
        "content":      content,
        "content_hash": content_hash,
        "size":         size,
        "timestamp":    result["transaction"]["timestamp"],
        "block_index":  result["block_index"],
    }
    socketio.emit("new_file", file_event, room=receiver,  namespace="/")
    socketio.emit("new_file", file_event, room=sender,    namespace="/")
    socketio.emit("new_file", file_event, room="admin",   namespace="/")

    return _ok({"message": "File routed and recorded", "block_index": result["block_index"], "content_hash": content_hash}, 201)


@app.route("/api/file/verify", methods=["POST"])
def file_verify():
    body = request.get_json(silent=True) or {}
    content = body.get("content", "")

    if not isinstance(content, str):
        return _bad("'content' must be a string")

    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

    for block in switch.blockchain.chain:
        for tx in block.transactions:
            if tx.get("type") == "file_transfer" and tx.get("content_hash") == content_hash:
                return _ok({
                    "verified":     True,
                    "block_index":  block.index,
                    "filename":     tx.get("filename"),
                    "sender":       tx.get("sender"),
                    "receiver":     tx.get("receiver"),
                    "timestamp":    tx.get("timestamp"),
                    "content_hash": content_hash,
                })

    return _ok({"verified": False, "content_hash": content_hash})


# ------------------------------------------------------------------
# Read-only API
# ------------------------------------------------------------------


@app.route("/api/devices", methods=["GET"])
def devices_list():
    return _ok({"devices": list(switch.connected_devices.values())})


@app.route("/api/blocked-devices", methods=["GET"])
def blocked_devices_list():
    return _ok({"blocked": list(blocked_devices)})


@app.route("/api/blockchain", methods=["GET"])
def blockchain_dump():
    return _ok({"chain": switch.blockchain.get_chain_as_list()})


@app.route("/api/blockchain/validate", methods=["GET"])
def blockchain_validate():
    valid = switch.blockchain.is_chain_valid()
    return _ok({"valid": valid, "chain_length": len(switch.blockchain.chain)})


@app.route("/api/status", methods=["GET"])
def status():
    base = switch.get_status()
    base["uptime_seconds"] = int(time.time() - _start_time)
    base["blocked_devices"] = list(blocked_devices)
    return _ok(base)


# ------------------------------------------------------------------
# SocketIO events
# ------------------------------------------------------------------


@socketio.on("join")
def handle_join(data):
    """
    Client sends: {mac: "AA:BB:...", role: "client"|"admin"}
    Server adds them to their MAC room.
    Admins are also added to the 'admin' room.
    """
    mac = (data or {}).get("mac", "").strip()
    role = (data or {}).get("role", "client")

    if mac:
        join_room(mac)
        logger.info("SocketIO: %s joined room '%s'", request.sid, mac)

    if role == "admin":
        join_room("admin")
        logger.info("SocketIO: %s joined admin room", request.sid)

    # Send current snapshot so the UI can initialize without extra HTTP calls
    emit("snapshot", {
        "devices": list(switch.connected_devices.values()),
        "blocked": list(blocked_devices),
        "chain_length": len(switch.blockchain.chain),
        "chain_valid": switch.blockchain.is_chain_valid(),
        "uptime_seconds": int(time.time() - _start_time),
        "simulation_mode": SIMULATION_MODE,
    })
