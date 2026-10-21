#!/bin/sh
# Name: Gaffer remote stop
# Author: Gaffer
# DontUseFBInk
#
# Closes the Gaffer remote and lets the Kindle sleep again, if the power button did not.

STATE_DIR="${GAFFER_STATE_DIR:-/tmp}"
UPSTART_DIR="${GAFFER_UPSTART_DIR:-/etc/upstart}"
PIDFILE="$STATE_DIR/gaffer_remote.pid"

# The remote is still running: ask it to close, which also brings the Kindle's screens back.
if [ -s "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    kill -TERM "$(cat "$PIDFILE")"
    exit 0
fi

# The remote is gone but left the Kindle in its state: undo that by hand.
killall kindle_browser 2>/dev/null
lipc-set-prop com.lab126.powerd preventScreenSaver 0
eips -c >/dev/null 2>&1
rm -f "$PIDFILE" "$STATE_DIR/gaffer_remote.pressed"
if [ -d "$UPSTART_DIR" ]; then
    cd / && start lab126_gui
else
    cd / && /etc/init.d/framework start
fi
