#!/usr/bin/env sh

if type python3 1>/dev/null 2>/dev/null; then
    python3 $@;
elif type python 1>/dev/null 2/dev/null; then
    python $@;
else
    echo "[!] No python found on this distro. Can't check for updates." >&2
    exit 1
fi
