#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
HERE="$(pwd)"

echo "== ReacTable install =="

echo "[1/3] installing udev rule (stable /dev/webcam symlink)"
sudo cp "$HERE/99-reactable-webcam.rules" /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger

echo "[2/3] installing systemd user service"
mkdir -p "$HOME/.config/systemd/user"
cp "$HERE/reactable.service" "$HOME/.config/systemd/user/reactable.service"
systemctl --user daemon-reload
systemctl --user enable reactable.service

echo "[3/3] done"
echo
echo "Autostart enabled: the pipeline starts at login (auto-login on boot)."
echo "Manage it with:"
echo "  systemctl --user status   reactable"
echo "  systemctl --user restart  reactable"
echo "  systemctl --user stop     reactable"
echo "  journalctl --user -u reactable -f   (logs)"
echo
if [ "${1:-}" = "--now" ]; then
    systemctl --user start reactable.service
    echo "Started now."
else
    echo "Run './install.sh --now' to start immediately, or reboot."
fi
