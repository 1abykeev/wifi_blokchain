#!/usr/bin/env bash
# =============================================================================
#  setup_ap.sh — Create a WiFi access point with hostapd + dnsmasq
#
#  Usage:
#    sudo ./scripts/setup_ap.sh [INTERFACE] [SSID] [PASSPHRASE] [CHANNEL]
#
#  Defaults (can also be set in ../.env):
#    INTERFACE  = wlan0
#    SSID       = WiFi-Blockchain
#    PASSPHRASE = blockchain123
#    CHANNEL    = 6
#    AP_IP      = 192.168.99.1
#    DHCP_RANGE = 192.168.99.10,192.168.99.50,12h
#    UPSTREAM   = eth0   (interface with internet access, for NAT)
#
#  Requirements:
#    sudo apt install hostapd dnsmasq iptables iproute2
# =============================================================================
set -euo pipefail

# ── Load .env if present ─────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/../.env"
[[ -f "$ENV_FILE" ]] && set -a && source "$ENV_FILE" && set +a

# ── Parameters (CLI args override env) ───────────────────────────────────────
INTERFACE="${1:-${WIFI_INTERFACE:-wlan0}}"
SSID="${2:-${AP_SSID:-WiFi-Blockchain}}"
PASSPHRASE="${3:-${AP_PASSPHRASE:-blockchain123}}"
CHANNEL="${4:-${AP_CHANNEL:-6}}"
AP_IP="${AP_IP:-192.168.99.1}"
DHCP_RANGE="${DHCP_RANGE:-192.168.99.10,192.168.99.50,12h}"
UPSTREAM="${UPSTREAM_IFACE:-eth0}"

HOSTAPD_CONF="/tmp/wifi_blockchain_hostapd.conf"
DNSMASQ_CONF="/tmp/wifi_blockchain_dnsmasq.conf"

echo "============================================"
echo " WiFi Blockchain — Access Point Setup"
echo "============================================"
echo " Interface : $INTERFACE"
echo " SSID      : $SSID"
echo " Channel   : $CHANNEL"
echo " AP IP     : $AP_IP"
echo " Upstream  : $UPSTREAM"
echo "============================================"

# ── Preflight checks ─────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
  echo "ERROR: This script must be run as root (sudo)." >&2
  exit 1
fi

for cmd in hostapd dnsmasq ip iptables iw; do
  if ! command -v "$cmd" &>/dev/null; then
    echo "ERROR: '$cmd' not found. Install with: sudo apt install hostapd dnsmasq iproute2 iptables" >&2
    exit 1
  fi
done

if ! iw phy | grep -q "AP"; then
  echo "WARNING: Interface may not support AP mode — proceeding anyway."
fi

# ── Stop conflicting services ────────────────────────────────────────────────
echo "[1/6] Stopping conflicting services…"
systemctl stop hostapd dnsmasq NetworkManager 2>/dev/null || true
rfkill unblock wifi 2>/dev/null || true

# ── Configure interface ───────────────────────────────────────────────────────
echo "[2/6] Configuring $INTERFACE…"
ip link set "$INTERFACE" down
iw dev "$INTERFACE" set type __ap 2>/dev/null || true
ip addr flush dev "$INTERFACE"
ip addr add "${AP_IP}/24" dev "$INTERFACE"
ip link set "$INTERFACE" up

# ── Write hostapd config ──────────────────────────────────────────────────────
echo "[3/6] Writing hostapd config → $HOSTAPD_CONF"
cat > "$HOSTAPD_CONF" <<HOSTAPD
interface=$INTERFACE
driver=nl80211
ssid=$SSID
hw_mode=g
channel=$CHANNEL
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase=$PASSPHRASE
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
HOSTAPD

# ── Write dnsmasq config ──────────────────────────────────────────────────────
echo "[4/6] Writing dnsmasq config → $DNSMASQ_CONF"
cat > "$DNSMASQ_CONF" <<DNSMASQ
interface=$INTERFACE
dhcp-range=$DHCP_RANGE
dhcp-option=3,${AP_IP}
dhcp-option=6,${AP_IP}
server=8.8.8.8
log-queries
log-dhcp
DNSMASQ

# ── Enable IP forwarding + NAT ────────────────────────────────────────────────
echo "[5/6] Enabling IP forwarding and NAT…"
echo 1 > /proc/sys/net/ipv4/ip_forward
iptables -t nat -A POSTROUTING -o "$UPSTREAM" -j MASQUERADE
iptables -A FORWARD -i "$INTERFACE" -o "$UPSTREAM" -j ACCEPT
iptables -A FORWARD -i "$UPSTREAM" -o "$INTERFACE" -m state --state RELATED,ESTABLISHED -j ACCEPT

# ── Start services ────────────────────────────────────────────────────────────
echo "[6/6] Starting hostapd and dnsmasq…"
dnsmasq -C "$DNSMASQ_CONF" --pid-file=/tmp/wifi_blockchain_dnsmasq.pid
hostapd "$HOSTAPD_CONF" &
HOSTAPD_PID=$!
echo "$HOSTAPD_PID" > /tmp/wifi_blockchain_hostapd.pid

echo ""
echo "✅  Access point '$SSID' is UP on $INTERFACE ($AP_IP)"
echo "    Clients will receive IPs in range: $DHCP_RANGE"
echo "    hostapd PID  : $HOSTAPD_PID"
echo ""
echo "    To stop: sudo ./scripts/teardown_ap.sh"
echo ""

# Keep hostapd in foreground so Ctrl+C tears it down cleanly
wait "$HOSTAPD_PID"
