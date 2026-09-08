#!/usr/bin/env bash
# Install hidraw access for the BlackShark V3 vendor interface.
set -euo pipefail
RULE_SRC="${1:-}"
if [[ -z $RULE_SRC || ! -f $RULE_SRC ]]; then
  echo "usage: install-udev.sh /path/to/99-razer-blackshark-v3.rules" >&2
  exit 2
fi
install -m644 "$RULE_SRC" /etc/udev/rules.d/99-razer-blackshark-v3.rules
udevadm control --reload-rules
udevadm trigger --subsystem-match=hidraw --action=add
USER_NAME="${SUDO_USER:-${USER:-$(id -un)}}"
for d in /sys/class/hidraw/hidraw*; do
  if grep -q 'HID_ID=0003:00001532:0000057A' "$d/device/uevent" 2>/dev/null; then
    name=$(basename "$d")
    chmod 0660 "/dev/$name" || true
    if getent group input >/dev/null; then
      chgrp input "/dev/$name" || true
    fi
    if command -v setfacl >/dev/null; then
      setfacl -m "u:${USER_NAME}:rw" "/dev/$name" || true
    else
      chmod 0666 "/dev/$name" || true
    fi
  fi
done
echo "installed"
