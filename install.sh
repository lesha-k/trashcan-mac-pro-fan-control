#!/bin/bash
# macpro-fan-floor installer. Run as root:  install.sh probe | install | rollback | status
set -euo pipefail

SRC=$(dirname "$(readlink -f "$0")")
SMC=/sys/devices/platform/applesmc.768
BIN=/usr/local/sbin/macpro-fan-floor
UNIT=/etc/systemd/system/macpro-fan-floor.service
STOCK=790

die() { echo "ERROR: $*" >&2; exit 1; }
need_root() { [ "$(id -u)" = 0 ] || die "run with sudo"; }

preflight() {
    [ "$(cat /sys/class/dmi/id/product_name)" = "MacPro6,1" ] || die "not a MacPro6,1"
    for f in fan1_min fan1_max fan1_input fan1_manual; do [ -e "$SMC/$f" ] || die "missing $SMC/$f"; done
    [ "$(cat $SMC/fan1_manual)" = 0 ] || die "fan1_manual is not 0 (SMC not automatic)"
}

probe() {
    preflight
    PROBE_ORIG=$(cat $SMC/fan1_min)   # global: the EXIT trap runs after this function returns
    echo "probe: fan1_min=$PROBE_ORIG fan=$(cat $SMC/fan1_input) rpm; writing 1000"
    trap 'echo "$PROBE_ORIG" > $SMC/fan1_min; echo "probe: restored fan1_min=$(cat $SMC/fan1_min)"' EXIT
    echo 1000 > $SMC/fan1_min
    local rb; rb=$(cat $SMC/fan1_min)
    [ "$rb" -ge 990 ] && [ "$rb" -le 1010 ] || die "SMC readback $rb, expected ~1000"
    local i fan
    for i in $(seq 1 30); do
        fan=$(cat $SMC/fan1_input)
        if [ "$fan" -ge 950 ]; then
            echo "probe: OK, fan reached $fan rpm after ${i}s"
            trap - EXIT
            echo "$PROBE_ORIG" > $SMC/fan1_min
            echo "probe: restored fan1_min=$(cat $SMC/fan1_min)"
            return 0
        fi
        sleep 1
    done
    die "fan stayed at $fan rpm for 30s after fan1_min=1000"
}

install_() {
    systemctl stop macpro-fan-floor.service 2>/dev/null || true
    probe
    echo "$STOCK" > $SMC/fan1_min
    echo "running tests"
    python3 -I "$SRC/test_macpro_fan_floor.py" >/dev/null 2>&1 || die "tests failed (run them manually to see why)"
    install -o root -g root -m 0755 "$SRC/macpro-fan-floor" "$BIN"
    install -o root -g root -m 0644 "$SRC/macpro-fan-floor.service" "$UNIT"
    systemctl daemon-reload
    systemctl enable --now macpro-fan-floor.service
    sleep 5
    systemctl is-active --quiet macpro-fan-floor.service || { journalctl -u macpro-fan-floor -n 20 --no-pager; die "service not active"; }
    echo "installed: fan1_min=$(cat $SMC/fan1_min) fan=$(cat $SMC/fan1_input)"
    journalctl -u macpro-fan-floor -n 5 --no-pager
}

rollback() {
    systemctl disable --now macpro-fan-floor.service 2>/dev/null || true
    rm -f "$UNIT" "$BIN"
    systemctl daemon-reload
    echo "$STOCK" > $SMC/fan1_min
    echo "rolled back: fan1_min=$(cat $SMC/fan1_min) (stock), unit and binary removed"
}

status() {
    systemctl status macpro-fan-floor.service --no-pager 2>&1 | head -12 || true
    echo "fan1_min=$(cat $SMC/fan1_min) fan1_input=$(cat $SMC/fan1_input) fan1_manual=$(cat $SMC/fan1_manual)"
}

case "${1:-}" in
    probe) need_root; probe ;;
    install) need_root; install_ ;;
    rollback) need_root; rollback ;;
    status) status ;;
    *) echo "usage: $0 probe|install|rollback|status"; exit 2 ;;
esac
