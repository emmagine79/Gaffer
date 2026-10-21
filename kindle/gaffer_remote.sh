#!/bin/sh
# Name: Gaffer remote
# Author: Gaffer
# DontUseFBInk
#
# Opens Gaffer's Kindle remote full screen on a jailbroken Kindle and keeps the screen awake while
# it is open. Needs firmware 5.16.4 to 5.18.3, which ships the Chromium browser at /usr/bin/chromium
# and can be jailbroken with Sanctuary. Copy this file and gaffer_remote_stop.sh into the Kindle's
# documents/ folder. Both then show in the library as scriptlets. Set GAFFER_URL below first.
#
# The browser flags and the way the Kindle's interface is stopped and started follow
# kindle-shortcut-browser (github.com/mitchellurgero/kindle-shortcut-browser), which found what
# works with the Kindle's Chromium. The script itself is written for Gaffer.
#
# To leave: press the power button once. The Kindle's own screens come back.
# If the screen ever stops answering, tap Gaffer remote stop in the library, or hold the power
# button until the Restart option appears.
#
# Plain POSIX sh, so it runs under the Kindle's BusyBox shell as well as bash.

## Set this to the Wi-Fi address the Mac's Gaffer window shows under Phone, with /kindle on the end.
GAFFER_URL="http://192.168.1.20:54342/kindle"

## 2 makes the page 536 points wide on a Paperwhite (1072 pixels). Use 1 on a 600-pixel Kindle.
SCALE=2

# The tests (service/tests/test_kindle_launcher.py) point these at stand-ins.
BROWSER="${GAFFER_BROWSER:-/usr/bin/chromium/bin/kindle_browser}"
INPUT_DEVICES="${GAFFER_INPUT_DEVICES:-/proc/bus/input/devices}"
INPUT_DIR="${GAFFER_INPUT_DIR:-/dev/input}"
UPSTART_DIR="${GAFFER_UPSTART_DIR:-/etc/upstart}"
STATE_DIR="${GAFFER_STATE_DIR:-/tmp}"
PIDFILE="$STATE_DIR/gaffer_remote.pid"
PRESSED="$STATE_DIR/gaffer_remote.pressed"

say() {
    eips 1 1 "$1" >/dev/null 2>&1
    sleep 5
}

if [ ! -x "$BROWSER" ]; then
    say "Gaffer remote needs firmware 5.16.4 to 5.18.3"
    exit 1
fi

# The power button's input devices: every device whose name says power (bd71827-power and
# snvs-powerkey on a Paperwhite 4). event1 when the list can't be read.
power_devices() {
    found=$(awk -v dir="$INPUT_DIR" '
        /^N: / { power = (tolower($0) ~ /power/) }
        /^H: / && power {
            line = $0; sub(/.*Handlers=/, "", line)
            n = split(line, part, " ")
            for (i = 1; i <= n; i++) if (part[i] ~ /^event[0-9]+$/) print dir "/" part[i]
        }' "$INPUT_DEVICES" 2>/dev/null)
    [ -n "$found" ] || found="$INPUT_DIR/event1"
    for dev in $found; do
        [ -r "$dev" ] && echo "$dev"
    done
}

DEVICES=$(power_devices)
if [ -z "$DEVICES" ]; then
    # With no power button to listen to there would be no way out, so never stop the interface.
    say "Gaffer remote can't read the power button"
    exit 1
fi

clear_screen() {
    eips -c >/dev/null 2>&1
    eips -c >/dev/null 2>&1
}

stop_gui() {
    if [ -d "$UPSTART_DIR" ]; then
        # Stopping the interface sends TERM to what it started, this script included.
        trap "" TERM
        stop lab126_gui
        usleep 1250000
        trap finish TERM
        clear_screen
        usleep 5000000
        start kb
    else
        /etc/init.d/framework stop
    fi
}

start_gui() {
    if [ -d "$UPSTART_DIR" ]; then
        cd / && start lab126_gui
        usleep 1250000
    else
        cd / && /etc/init.d/framework start
    fi
}

readers=""
browser_pid=""
finished=""

finish() {
    [ -n "$finished" ] && exit 0
    finished=1
    trap "" INT TERM
    [ -n "$browser_pid" ] && kill "$browser_pid" 2>/dev/null
    killall kindle_browser 2>/dev/null
    for pid in $readers; do kill "$pid" 2>/dev/null; done
    lipc-set-prop com.lab126.powerd preventScreenSaver 0
    clear_screen
    start_gui
    rm -f "$PIDFILE" "$PRESSED"
    exit 0
}

# Wait for one press of the power button on one device. An input_event on the Kindle's 32-bit
# kernel is 16 bytes: time (8), then type EV_KEY 0001, code KEY_POWER 0074, value pressed
# 00000001, little-endian. Characters 17 to 32 of the hex are those last 8 bytes.
listen() {
    while :; do
        event=$(dd if="$1" bs=16 count=1 2>/dev/null | hexdump -v -e '16/1 "%02X"')
        if [ -z "$event" ]; then
            sleep 1
            continue
        fi
        if [ "$(echo "$event" | cut -c17-32)" = "0100740001000000" ]; then
            : > "$PRESSED"
            exit 0
        fi
    done
}

echo $$ > "$PIDFILE"
rm -f "$PRESSED"
trap finish INT TERM

# Keep the screen on: no sleep and no screensaver while the remote is open.
lipc-set-prop com.lab126.powerd preventScreenSaver 1

clear_screen
stop_gui
clear_screen

export XDG_CONFIG_HOME="/mnt/us/system/browser/"
export LD_LIBRARY_PATH="/usr/bin/chromium/lib:/usr/bin/chromium/usr/lib:/usr/lib/"

"$BROWSER" "$GAFFER_URL" --no-zygote --no-sandbox --single-process \
    --disable-gpu --in-process-gpu --disable-gpu-sandbox --disable-gpu-compositing \
    --skia-resource-cache-limit-mb=64 --force-gpu-mem-available-mb=32 \
    --force-device-scale-factor="$SCALE" --js-flags=jitless --content-shell-hide-toolbar \
    --content-shell-host-window-cord=0,215 \
    --enable-grayscale-mode --enable-low-end-device-mode --enable-low-res-tiling \
    --disable-site-isolation-trials >/dev/null 2>&1 &
browser_pid=$!
unset LD_LIBRARY_PATH

for dev in $DEVICES; do
    listen "$dev" &
    readers="$readers $!"
done

# Check once a second, so a press, a closed browser or a TERM is handled within a second.
while :; do
    [ -e "$PRESSED" ] && finish
    # The browser closed by itself: give the Kindle back rather than leave a blank screen.
    kill -0 "$browser_pid" 2>/dev/null || finish
    sleep 1
done
