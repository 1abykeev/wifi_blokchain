# Blockchain WiFi Network — University Final Project

A blockchain-based WiFi network simulation where phones and laptops are clients that connect, chat, and have every network event immutably recorded on a custom blockchain. Built with Python/Flask. Runs on Linux (tested in VirtualBox Ubuntu on Windows 10).

---

## What This System Does

Simulates a WiFi router/switch backed by a blockchain ledger. Every device connection, disconnection, chat message, and admin action (block/allow) gets hashed into a block via proof-of-work and stored permanently. The admin watches a real-time dashboard; clients open a mobile-friendly chat UI. Two modes: simulation (API-only, no real WiFi hardware) and real (Scapy packet sniffer + hostapd access point).

---

## Tech Stack

- **Python 3.10+** — Flask 2.3+, Flask-SocketIO 5.3+
- **Frontend** — Bootstrap 5.3.2, vanilla JS, Socket.IO 4.6.1
- **Blockchain** — custom pure-Python SHA256 PoW, difficulty = 2 leading zeros
- **Persistence** — `data/blockchain.json` (JSON, auto-saved after every mine)
- **Real WiFi (optional)** — Scapy 2.5+, hostapd, dnsmasq, iw, iptables
- **Config** — python-dotenv (`.env` file)

---

## File Structure

```
codebase/
├── run.py               # Entry point — loads env, wires everything, starts server
├── app.py               # Flask app, REST API, SocketIO events, monkey-patch on mine
├── blockchain.py        # Block + Blockchain classes (PoW, hash chain, validation)
├── switch.py            # WiFiSwitch — device registry, routing, optional Scapy sniffer
├── persistence.py       # save_chain() / load_chain() to data/blockchain.json
├── .env                 # Active config (SIMULATION_MODE, PORT, etc.)
├── .env.example         # Config template
├── requirements.txt     # pip dependencies
├── data/
│   └── blockchain.json  # Persisted chain (survives restarts)
├── scripts/
│   ├── setup_ap.sh      # Creates real WiFi AP (hostapd + dnsmasq)
│   └── teardown_ap.sh   # Tears down AP and restores network state
└── templates/
    ├── admin.html       # Admin dashboard (real-time monitoring + block/allow)
    └── client.html      # Client chat UI (mobile-optimized)
```

---

## Configuration (`.env`)

```bash
SIMULATION_MODE=True        # True = API only, no real WiFi hardware needed
WIFI_INTERFACE=wlan0        # Adapter name for real mode (ignored in sim)
FLASK_HOST=0.0.0.0
FLASK_PORT=5000
FLASK_DEBUG=False
AUTO_MINE=True              # Mine a block immediately after each transaction

# Real AP settings (only used when SIMULATION_MODE=False)
AP_SSID=WiFi-Blockchain
AP_PASSPHRASE=blockchain123
AP_CHANNEL=6
AP_IP=192.168.99.1
DHCP_RANGE=192.168.99.10,192.168.99.50,12h
UPSTREAM_IFACE=eth0
```

---

## How to Run

### Simulation Mode (default, no hardware needed)

```bash
cd codebase
pip install -r requirements.txt
python3 run.py
```

Access:
- Admin dashboard: `http://localhost:5000/admin`
- Client chat UI:  `http://localhost:5000/client`
- REST API base:   `http://localhost:5000/api/`

### Real WiFi Mode (Linux, monitor-mode adapter required)

```bash
# Terminal 1 — create access point
sudo ./scripts/setup_ap.sh wlan0 WiFi-Blockchain blockchain123 6

# Terminal 2 — start server in real mode
SIMULATION_MODE=False python3 run.py
```

Phones connect to SSID `WiFi-Blockchain`, then open `http://192.168.99.1:5000/client` in their browser.

### Running in VirtualBox Ubuntu (this project's setup)

1. Start the Ubuntu VM in VirtualBox on the Windows 10 host.
2. Open a terminal in the VM and navigate to the shared/cloned codebase directory.
3. Run `python3 run.py` inside the VM.
4. Access the UI from the VM's browser at `http://localhost:5000/admin` or `http://localhost:5000/client`.
5. For multi-device testing in simulation mode, open multiple browser tabs — each tab is a "device" with a unique MAC/ID.

---

## Blockchain Architecture

### Block Structure

```json
{
  "index": 3,
  "timestamp": 1776199769.96,
  "transactions": [
    {
      "type": "message",
      "sender": "AA:BB:CC:DD:EE:01",
      "receiver": "AA:BB:CC:DD:EE:02",
      "payload": "Hello!",
      "metadata": {},
      "timestamp": 1776199769.96
    }
  ],
  "previous_hash": "0074d40a...",
  "nonce": 4,
  "hash": "00d9cad9..."
}
```

### Transaction Types

| Type | Fields |
|------|--------|
| `genesis` | `data` |
| `device_connect` | `mac`, `metadata` |
| `device_disconnect` | `mac` |
| `message` | `sender`, `receiver`, `payload`, `metadata` |
| `device_block` | `mac` |
| `device_allow` | `mac` |

### Proof of Work

- SHA256 hash of block dict (excluding the `hash` field itself)
- Increments `nonce` until hash starts with `"00"` (2 leading zeros)
- Difficulty is intentionally low — mines instantly on any modern machine
- Validates entire chain: hash continuity + self-hash check on each block

### Auto-Save Hook

`app.py` monkey-patches `blockchain.mine_pending_transactions` at startup. After every mine: chain is saved to disk AND a `new_block` SocketIO event is broadcast to all clients. No explicit save calls needed anywhere else.

---

## REST API Reference

### Device Management

| Method | Endpoint | Body | Description |
|--------|----------|------|-------------|
| POST | `/api/device/connect` | `{mac, metadata?}` | Register device, mine connect block |
| POST | `/api/device/disconnect` | `{mac}` | Unregister device, mine disconnect block |
| POST | `/api/device/block` | `{mac}` | Add to blocked set, mine block txn |
| POST | `/api/device/allow` | `{mac}` | Remove from blocked set, mine allow txn |

### Messaging

| Method | Endpoint | Body | Description |
|--------|----------|------|-------------|
| POST | `/api/message/send` | `{sender, receiver, payload, metadata?}` | Route message, returns 403 if sender is blocked |

### Read-Only

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/devices` | List connected devices |
| GET | `/api/blocked-devices` | List blocked MACs |
| GET | `/api/blockchain` | Full chain dump |
| GET | `/api/blockchain/validate` | Chain integrity check |
| GET | `/api/status` | Overall status snapshot |

### UI Routes

| Route | Description |
|-------|-------------|
| `GET /` | Redirects to `/admin` |
| `GET /admin` | Admin dashboard |
| `GET /client` | Client chat UI |

---

## SocketIO Events

### Server → Client

| Event | Payload | When |
|-------|---------|------|
| `snapshot` | `{devices, blocked, chain_length, ...}` | On join |
| `new_block` | Block dict | After every mine |
| `device_update` | `{action, mac, devices, blocked}` | Connect/disconnect/block/allow |
| `new_message` | `{sender, receiver, payload, timestamp, block_index}` | New message mined |

### Client → Server

| Event | Payload | Effect |
|-------|---------|--------|
| `join` | `{mac, role?}` | Adds socket to MAC room; `role="admin"` also joins admin room |

---

## WiFiSwitch (`switch.py`)

Singleton `switch` exported from module. Thread-safe via `RLock`.

**Simulation mode:** devices managed purely via API calls.

**Real mode:** background thread runs Scapy sniffer on `WIFI_INTERFACE`, auto-detects `Dot11ProbeReq` and `Dot11AssoReq` frames, logs new MACs to blockchain automatically.

Key methods:
- `switch.connect_device(mac, metadata)` — register + blockchain log
- `switch.disconnect_device(mac)` — unregister + blockchain log
- `switch.route_message(sender, receiver, payload, metadata)` — record message on blockchain
- `switch.start()` — called by `run.py`, spawns sniffer if real mode
- `switch.stop()` — called on shutdown, joins sniffer thread

---

## UI Interfaces

### Admin Dashboard (`/admin`)

- Status bar: block count, device count, uptime, chain validity, mode (SIM/LIVE)
- Stat cards for totals
- Connected devices table with block/allow buttons per device
- Live event feed (capped at 200 entries, color-coded by type)
- Full blockchain viewer with expandable block JSON
- "Verify Chain" button for integrity check
- Synced uptime counter (server base time + local elapsed)

### Client Chat UI (`/client`)

- Join screen: enter device ID (MAC or any custom name) + optional hostname
- Chat screen with message bubbles (sent = blue right, received = gray left)
- Each message shows block index where it was permanently recorded
- Receiver dropdown populated from live `/api/devices` fetch
- Blocked banner + disabled send when admin blocks the device
- System messages for join/block/unblock events
- Mobile-optimized layout (viewport, safe area insets for notch)
- Auto-reconnects and re-joins room on socket reconnect

---

## Access Point Scripts

### `scripts/setup_ap.sh [INTERFACE] [SSID] [PASSPHRASE] [CHANNEL]`

Creates a real WPA2 WiFi AP:
1. Stops hostapd, dnsmasq, NetworkManager
2. Sets interface to AP mode via `iw`
3. Assigns static IP `192.168.99.1/24`
4. Generates hostapd and dnsmasq configs
5. Enables IP forwarding + NAT via iptables
6. Starts hostapd in foreground (Ctrl+C kills it)

Devices that join get DHCP leases from `192.168.99.10–192.168.99.50`.

### `scripts/teardown_ap.sh`

Reverses everything: kills processes, removes iptables rules, sets interface back to managed mode, disables IP forwarding, cleans temp configs.

---

## Data Flow: End-to-End

### Device Connect
```
Client browser → POST /api/device/connect {mac}
  → switch.connect_device()
    → blockchain.add_transaction_and_mine()
      → PoW (nonce until hash starts with "00")
      → monkey-patch saves chain to disk
      → broadcasts new_block + device_update via SocketIO
  → API returns device info
```

### Message Send
```
Client browser → POST /api/message/send {sender, receiver, payload}
  → check blocked_devices set (403 if blocked)
  → switch.route_message()
    → blockchain.add_transaction_and_mine()
      → PoW → save → broadcast new_block
    → socketio.emit("new_message") to receiver's room + admin room
  → receiver's browser tab renders message bubble with block index
```

### Admin Block
```
Admin clicks Block → POST /api/device/block {mac}
  → add mac to blocked_devices set (in-memory)
  → blockchain.add_transaction_and_mine() logs device_block txn
  → broadcast device_update {action: "block"}
  → blocked device's browser shows blocked banner, send disabled
  → all subsequent send attempts by that device → 403
```

---

## Known Limitations (by design — simulation/university scope)

- No authentication: any caller can connect or send as any device
- No HTTPS: messages in plaintext
- No digital signatures: identity is just a name/MAC string
- No consensus: single node, no distributed validation
- `blocked_devices` set is in-memory only — resets on server restart
- CORS is wide open (`*`)
- Real mode requires root + monitor-mode WiFi adapter (not typical in VirtualBox)

---

## Persistence

- **Blockchain:** Persists to `data/blockchain.json` after every mine. Loaded at startup.
- **Blocked devices:** In-memory only. Lost on restart.
- **Genesis block:** Created fresh if no chain file found on disk.

---

## Dependencies (`requirements.txt`)

```
flask>=2.3.0
flask-socketio>=5.3.0
python-dotenv>=1.0.0
scapy>=2.5.0   # optional, only needed for SIMULATION_MODE=False
```

---

## Git History

```
a34213e  blokchain logs   ← latest
69a5f2a  First try
aab01f7  Init commit
```
