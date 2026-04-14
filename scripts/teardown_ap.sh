#!/usr/bin/env bash
# =============================================================================
#  teardown_ap.sh — Stop the WiFi access point and restore network state
#
#  Usage:
#    sudo ./scripts/teardown_ap.sh [INTERFACE]
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/../.env"
[[ -f "$ENV_FILE" ]] && set -a && source "$ENV_FILE" && set +a

INTERFACE="${1:-${WIFI_INTERFACE:-wlan0}}"
UPSTREAM="${UPSTREAM_IFACE:-eth0}"
AP_IP="${AP_IP:-192.168.99.1}"

echo "============================================"
echo " WiFi Blockchain — Access Point Teardown"
echo "============================================"

if [[ $EUID -ne 0 ]]; then
  echo "ERROR: Must be run as root (sudo)." >&2
  exit 1
fi

# ── Kill hostapd ─────────────────────────────────────────────────────────────
echo "[1/5] Stopping hostapd…"
if [[ -f /tmp/wifi_blockchain_hostapd.pid ]]; then
  kill "$(cat /tmp/wifi_blockchain_hostapd.pid)" 2>/dev/null || true
  rm -f /tmp/wifi_blockchain_hostapd.pid
fi
pkill -f "hostapd /tmp/wifi_blockchain_hostapd.conf" 2>/dev/null || true

# ── Kill dnsmasq ──────────────────────────────────────────────────────────────
echo "[2/5] Stopping dnsmasq…"
if [[ -f /tmp/wifi_blockchain_dnsmasq.pid ]]; then
  kill "$(cat /tmp/wifi_blockchain_dnsmasq.pid)" 2>/dev/null || true
  rm -f /tmp/wifi_blockchain_dnsmasq.pid
fi

# ── Remove iptables rules ─────────────────────────────────────────────────────
echo "[3/5] Removing iptables NAT rules…"
iptables -t nat -D POSTROUTING -o "$UPSTREAM" -j MASQUERADE 2>/dev/null || true
iptables -D FORWARD -i "$INTERFACE" -o "$UPSTREAM" -j ACCEPT 2>/dev/null || true
iptables -D FORWARD -i "$UPSTREAM" -o "$INTERFACE" -m state --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || true

# ── Restore interface ─────────────────────────────────────────────────────────
echo "[4/5] Restoring $INTERFACE…"
ip link set "$INTERFACE" down 2>/dev/null || true
ip addr flush dev "$INTERFACE" 2>/dev/null || true
iw dev "$INTERFACE" set type managed 2>/dev/null || true
ip link set "$INTERFACE" up 2>/dev/null || true

# ── Disable IP forwarding ─────────────────────────────────────────────────────
echo "[5/5] Disabling IP forwarding…"
echo 0 > /proc/sys/net/ipv4/ip_forward

# ── Clean up temp files ───────────────────────────────────────────────────────
rm -f /tmp/wifi_blockchain_hostapd.conf /tmp/wifi_blockchain_dnsmasq.conf

echo ""
echo "✅  Access point on $INTERFACE is DOWN."
echo "    You may need to restart NetworkManager:"
echo "    sudo systemctl start NetworkManager"
echo ""
