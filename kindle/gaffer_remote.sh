#!/bin/sh
# Name: Gaffer remote
# Author: Gaffer
# DontUseFBInk
#
# Opens Gaffer's Kindle remote full screen on a jailbroken Kindle and keeps the screen awake while
# it is open. Needs firmware 5.16.4 to 5.18.3, which ships the Chromium browser at /usr/bin/chromium
# and can be jailbroken with Sanctuary. Copy this file, gaffer_remote_stop.sh and
# gaffer_remote_forget.sh into the Kindle's documents/ folder. They then show in the library as
# scriptlets. Nothing needs setting: the script finds the Mac on the Wi-Fi by itself.
#
# Finding the Mac: it asks the last Mac it used (saved in SAVE_FILE). If that does not answer, it
# asks every address on the Kindle's own Wi-Fi network for Gaffer's /api/hello, 32 at a time, and
# keeps the first that answers. While the remote is open it asks again every 30 seconds, so a Mac
# that comes back at a new address (after a restart, say) is found and the remote reopens there.
# The browser always opens http://gaffer.invalid:PORT/kindle, with that name mapped to the address
# found, so the page's origin, and the PIN it saved, stay the same whatever the Mac's address.
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

## The port in the Wi-Fi address the Mac's Gaffer window shows under Phone (the number after the colon).
PORT=54342

## Leave empty to find the Mac by itself. To always use one Mac, put its Wi-Fi address here, for
## example MAC="192.168.1.20". Useful only when more than one Mac on the Wi-Fi runs Gaffer.
MAC=""

## yes: the browser calls the Mac gaffer.invalid whatever its address, so the saved PIN survives a
## new address. Set to no if the remote shows a "can't be reached" page for gaffer.invalid; it then
## opens the Mac's address itself, and asks for the PIN again whenever that address changes.
STABLE_NAME=yes

## 2 makes the page 536 points wide on a Paperwhite (1072 pixels). Use 1 on a 600-pixel Kindle.
SCALE=2

# The tests (service/tests/test_kindle_launcher.py) point these at stand-ins.
BROWSER="${GAFFER_BROWSER:-/usr/bin/chromium/bin/kindle_browser}"
INPUT_DEVICES="${GAFFER_INPUT_DEVICES:-/proc/bus/input/devices}"
INPUT_DIR="${GAFFER_INPUT_DIR:-/dev/input}"
UPSTART_DIR="${GAFFER_UPSTART_DIR:-/etc/upstart}"
STATE_DIR="${GAFFER_STATE_DIR:-/tmp}"
SAVE_FILE="${GAFFER_SAVE_FILE:-/mnt/us/system/gaffer_mac}"
WIFI="${GAFFER_WIFI:-wlan0}"
RECHECK="${GAFFER_RECHECK:-30}"  # seconds between checks that the Mac is still where it was
PIDFILE="$STATE_DIR/gaffer_remote.pid"
PRESSED="$STATE_DIR/gaffer_remote.pressed"
FOUND="$STATE_DIR/gaffer_remote.found"
# The name the browser uses for the Mac. Gaffer accepts it (service/gaffer/phone.py, KINDLE_NAME).
NAME="gaffer.invalid"

say() {
    eips 1 1 "$1" >/dev/null 2>&1
    sleep 5
}

# Whether Gaffer answers at this address. /api/hello needs no PIN and says only that it is Gaffer.
hello() {
    wget -q -T 2 -O - "http://$1:$PORT/api/hello" 2>/dev/null | grep -q '"app":"gaffer"'
}

# The first three parts of the Kindle's own Wi-Fi address, as 192.168.100 for 192.168.100.27.
wifi_network() {
    ifconfig "$WIFI" 2>/dev/null | sed -n 's/.*inet addr:\([0-9]*\.[0-9]*\.[0-9]*\)\.[0-9]*.*/\1/p' | head -n 1
}

# Ask every address on the Wi-Fi network (.1 to .254), 32 at a time, and print the first that is
# Gaffer. Stops early on a power press, so leaving never waits for a whole search.
search() {
    base=$(wifi_network)
    [ -n "$base" ] || return 1
    rm -f "$FOUND"
    first=1
    while [ "$first" -le 254 ]; do
        [ -e "$PRESSED" ] && return 1
        last=$((first + 31))
        [ "$last" -gt 254 ] && last=254
        jobs_here=""
        n=$first
        while [ "$n" -le "$last" ]; do
            ( hello "$base.$n" && echo "$base.$n" >> "$FOUND" ) &
            jobs_here="$jobs_here $!"
            n=$((n + 1))
        done
        # Give the batch up to 3 seconds, then stop what is left: an address with nothing behind it
        # can keep a connection waiting longer than wget's own timeout.
        waited=0
        while [ "$waited" -lt 3 ]; do
            busy=""
            for job in $jobs_here; do kill -0 "$job" 2>/dev/null && busy=1; done
            [ -z "$busy" ] && break
            sleep 1
            waited=$((waited + 1))
        done
        for job in $jobs_here; do kill "$job" 2>/dev/null; done
        if [ -s "$FOUND" ]; then
            head -n 1 "$FOUND"
            return 0
        fi
        first=$((last + 1))
    done
    return 1
}

# The Mac's address: the one set in MAC, else the saved one if it still answers, else a search.
# A Mac found by a search is saved for next time.
find_mac() {
    if [ -n "$MAC" ]; then
        hello "$MAC" && echo "$MAC"
        return
    fi
    saved=$(cat "$SAVE_FILE" 2>/dev/null)
    if [ -n "$saved" ] && hello "$saved"; then
        echo "$saved"
        return 0
    fi
    found=$(search) || return 1
    echo "$found" > "$SAVE_FILE"
    echo "$found"
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
    rm -f "$PIDFILE" "$PRESSED" "$FOUND"
    exit 0
}

# Open the remote for the Mac at $1, closing any browser already open.
open_browser() {
    if [ -n "$browser_pid" ]; then
        kill "$browser_pid" 2>/dev/null
        killall kindle_browser 2>/dev/null
        browser_pid=""
        clear_screen
    fi
    export XDG_CONFIG_HOME="/mnt/us/system/browser/"
    export LD_LIBRARY_PATH="/usr/bin/chromium/lib:/usr/bin/chromium/usr/lib:/usr/lib/"
    if [ "$STABLE_NAME" = yes ]; then
        url="http://$NAME:$PORT/kindle"
        rules="--host-resolver-rules=MAP $NAME $1"
    else
        url="http://$1:$PORT/kindle"
        rules="--no-first-run"
    fi
    "$BROWSER" "$url" "$rules" \
        --no-zygote --no-sandbox --single-process \
        --disable-gpu --in-process-gpu --disable-gpu-sandbox --disable-gpu-compositing \
        --skia-resource-cache-limit-mb=64 --force-gpu-mem-available-mb=32 \
        --force-device-scale-factor="$SCALE" --js-flags=jitless --content-shell-hide-toolbar \
        --content-shell-host-window-cord=0,215 \
        --enable-grayscale-mode --enable-low-end-device-mode --enable-low-res-tiling \
        --disable-site-isolation-trials >/dev/null 2>&1 &
    browser_pid=$!
    unset LD_LIBRARY_PATH
}

# Wait $1 seconds, a second at a time, leaving at once on a power press.
pause() {
    left=$1
    while [ "$left" -gt 0 ]; do
        [ -e "$PRESSED" ] && finish
        sleep 1
        left=$((left - 1))
    done
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

# The power button works from here on, during the search too.
for dev in $DEVICES; do
    listen "$dev" &
    readers="$readers $!"
done

eips 1 1 "Looking for Gaffer on this Wi-Fi" >/dev/null 2>&1
until mac=$(find_mac); do
    [ -e "$PRESSED" ] && finish
    clear_screen
    eips 1 1 "Gaffer not found on this Wi-Fi." >/dev/null 2>&1
    eips 1 3 "Is the Mac on, with Phone switched on" >/dev/null 2>&1
    eips 1 4 "in Gaffer? Still looking." >/dev/null 2>&1
    eips 1 6 "Press the power button to stop." >/dev/null 2>&1
    pause 5
done
clear_screen
open_browser "$mac"

# Check once a second, so a press, a closed browser or a TERM is handled within a second. Every
# RECHECK seconds, check the Mac is still there; if not, look for it, and reopen wherever it is now.
# A Mac that is only restarting at the same address needs nothing: the page reconnects by itself.
ticks=0
while :; do
    [ -e "$PRESSED" ] && finish
    # The browser closed by itself (Exit): give the Kindle back rather than leave a blank screen.
    kill -0 "$browser_pid" 2>/dev/null || finish
    ticks=$((ticks + 1))
    if [ "$ticks" -ge "$RECHECK" ]; then
        ticks=0
        if ! hello "$mac" && moved=$(find_mac) && [ "$moved" != "$mac" ]; then
            mac=$moved
            open_browser "$mac"
        fi
    fi
    sleep 1
done
