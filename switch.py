"""
WiFi Switch — monitors device connections and message traffic.

Two modes controlled by SIMULATION_MODE in .env:

  SIMULATION_MODE=True  — No real WiFi adapter needed.
                          Devices connect/disconnect via the Flask API.
                          Messages are routed through /api/message/send.
                          Everything is still written to the blockchain.

  SIMULATION_MODE=False — Uses Scapy to sniff live 802.11 frames on the
                          interface specified by WIFI_INTERFACE in .env.
                          Requires a monitor-mode capable adapter and root
                          privileges.
"""

import os
import time
import threading
import logging
from typing import Dict, Any, Optional

from dotenv import load_dotenv
from blockchain import Blockchain

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("switch")

SIMULATION_MODE: bool = os.getenv("SIMULATION_MODE", "True").strip().lower() in (
    "true", "1", "yes"
)
WIFI_INTERFACE: str = os.getenv("WIFI_INTERFACE", "wlan0")
AUTO_MINE: bool = os.getenv("AUTO_MINE", "True").strip().lower() in (
    "true", "1", "yes"
)


class WiFiSwitch:
    """
    Central switch object shared between the sniffer thread and the Flask app.
    Thread-safe via a simple RLock.
    """

    def __init__(self):
        self.blockchain = Blockchain()
        self.connected_devices: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._sniffer_thread: Optional[threading.Thread] = None
        self._running = False

    # ------------------------------------------------------------------
    # Device management (used by both modes)
    # ------------------------------------------------------------------

    def connect_device(self, mac: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Register a device as connected and log it to the blockchain."""
        with self._lock:
            info = {
                "mac": mac,
                "connected_at": time.time(),
                **(metadata or {}),
            }
            self.connected_devices[mac] = info
            logger.info("Device connected: %s", mac)

            tx = {
                "type": "device_connect",
                "mac": mac,
                "metadata": metadata or {},
            }
            block = self.blockchain.add_transaction_and_mine(tx)
            logger.info("Mined block #%d for device_connect", block.index)
            return info

    def disconnect_device(self, mac: str) -> bool:
        """Deregister a device and log it to the blockchain."""
        with self._lock:
            if mac not in self.connected_devices:
                return False
            del self.connected_devices[mac]
            logger.info("Device disconnected: %s", mac)

            tx = {
                "type": "device_disconnect",
                "mac": mac,
            }
            block = self.blockchain.add_transaction_and_mine(tx)
            logger.info("Mined block #%d for device_disconnect", block.index)
            return True

    def route_message(
        self,
        sender_mac: str,
        receiver_mac: str,
        payload: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Route a message between devices and record it on the blockchain."""
        with self._lock:
            tx = {
                "type": "message",
                "sender": sender_mac,
                "receiver": receiver_mac,
                "payload": payload,
                "metadata": metadata or {},
            }
            block = self.blockchain.add_transaction_and_mine(tx)
            logger.info(
                "Message routed %s -> %s (block #%d)", sender_mac, receiver_mac, block.index
            )
            return {
                "block_index": block.index,
                "block_hash": block.hash,
                "transaction": tx,
            }

    def route_file(
        self,
        sender: str,
        receiver: str,
        filename: str,
        content: str,
        content_hash: str,
        size: int,
    ) -> Dict[str, Any]:
        """Route a .txt file between devices and record it on the blockchain."""
        with self._lock:
            tx = {
                "type": "file_transfer",
                "sender": sender,
                "receiver": receiver,
                "filename": filename,
                "content": content,
                "content_hash": content_hash,
                "size": size,
                "timestamp": time.time(),
            }
            block = self.blockchain.add_transaction_and_mine(tx)
            logger.info(
                "File routed %s -> %s '%s' (block #%d)", sender, receiver, filename, block.index
            )
            return {
                "block_index": block.index,
                "block_hash": block.hash,
                "transaction": tx,
            }

    def route_file_delete(
        self,
        sender: str,
        file_block_index: int,
        filename: str,
    ) -> Dict[str, Any]:
        """Record a file deletion on the blockchain. The original file_transfer
        block remains untouched; this adds a separate file_delete transaction
        referencing it."""
        with self._lock:
            tx = {
                "type": "file_delete",
                "sender": sender,
                "file_block_index": file_block_index,
                "filename": filename,
                "timestamp": time.time(),
            }
            block = self.blockchain.add_transaction_and_mine(tx)
            logger.info(
                "File delete recorded by %s for block #%d (delete block #%d)",
                sender, file_block_index, block.index,
            )
            return {
                "block_index": block.index,
                "block_hash": block.hash,
                "transaction": tx,
            }

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "simulation_mode": SIMULATION_MODE,
                "chain_length": len(self.blockchain.chain),
                "chain_valid": self.blockchain.is_chain_valid(),
                "connected_devices": list(self.connected_devices.values()),
                "pending_transactions": len(self.blockchain.pending_transactions),
            }

    # ------------------------------------------------------------------
    # Real mode — Scapy packet sniffer
    # ------------------------------------------------------------------

    def _handle_packet(self, packet):
        """Scapy callback: parse 802.11 frames and log device events."""
        try:
            # Import here so the file is importable without Scapy installed
            from scapy.layers.dot11 import Dot11, Dot11ProbeReq, Dot11AssoReq

            if packet.haslayer(Dot11):
                dot11 = packet.getlayer(Dot11)
                src_mac = dot11.addr2

                if src_mac and src_mac != "ff:ff:ff:ff:ff:ff":
                    with self._lock:
                        if src_mac not in self.connected_devices:
                            # New device spotted
                            frame_type = "unknown"
                            if packet.haslayer(Dot11ProbeReq):
                                frame_type = "probe_request"
                            elif packet.haslayer(Dot11AssoReq):
                                frame_type = "association_request"

                            self.connect_device(src_mac, {"frame_type": frame_type})
        except Exception as exc:
            logger.warning("Packet handler error: %s", exc)

    def _start_sniffing(self):
        """Run in a background thread; sniffs until _running is False."""
        try:
            from scapy.all import sniff
            logger.info("Starting Scapy sniffer on interface '%s'", WIFI_INTERFACE)
            sniff(
                iface=WIFI_INTERFACE,
                prn=self._handle_packet,
                store=False,
                stop_filter=lambda _: not self._running,
            )
        except PermissionError:
            logger.error(
                "Permission denied — run with sudo for live sniffing, "
                "or set SIMULATION_MODE=True in .env"
            )
        except Exception as exc:
            logger.error("Sniffer error: %s", exc)
        finally:
            logger.info("Scapy sniffer stopped")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        self._running = True
        if SIMULATION_MODE:
            logger.info(
                "=== SIMULATION MODE ACTIVE ===  "
                "No real WiFi adapter needed. "
                "Use the Flask API to connect devices and send messages."
            )
        else:
            logger.info("Starting in REAL mode on interface '%s'", WIFI_INTERFACE)
            self._sniffer_thread = threading.Thread(
                target=self._start_sniffing, daemon=True
            )
            self._sniffer_thread.start()

    def stop(self):
        self._running = False
        if self._sniffer_thread and self._sniffer_thread.is_alive():
            self._sniffer_thread.join(timeout=3)
        logger.info("WiFiSwitch stopped")


# Module-level singleton used by app.py
switch = WiFiSwitch()


if __name__ == "__main__":
    switch.start()
    logger.info("Switch running. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        switch.stop()
