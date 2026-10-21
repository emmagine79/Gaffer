#!/bin/bash
# Name: Gaffer remote
# Author: Gaffer
# DontUseFBInk
#
# Opens Gaffer's Kindle remote full screen on a jailbroken Kindle (firmware 5.16.4 or later, which
# ships the Chromium browser at /usr/bin/chromium) and keeps the screen awake while it is open.
# Copy this file and gaffer_remote_stop.sh into the Kindle's documents/ folder. Both then show in
# the library as scriptlets. Set GAFFER_URL below first.
#
# The browser flags are the ones kindle-shortcut-browser (github.com/mitchellurgero/kindle-shortcut-browser)
# found to work with the Kindle's Chromium; the script itself is written for Gaffer.
#
# To leave: press the power button once. The Kindle's own screens come back.
# If the screen ever stops answering, hold the power button for 20 seconds to restart the Kindle.

## Set this to the Wi-Fi address the Mac's Gaffer window shows under Phone, with /kindle on the end.
GAFFER_URL="http://192.168.100.134:54342/kindle"

## 2 makes the page 536 points wide on a Paperwhite (1072 pixels). Use 1 on a 600-pixel Kindle.
SCALE=2
## The power button's input device. event1 on the Kindles this has been checked on.
POWER_DEVICE="/dev/input/event1"

BROWSER="/usr/bin/chromium/bin/kindle_browser"

if [ ! -x "$BROWSER" ]; then
    eips 1 1 "Gaffer remote needs firmware 5.16.4 or later"
    sleep 5
    exit 1
fi

clear_screen() {
    eips -c >/dev/null 2>&1
    eips -c >/dev/null 2>&1
}

stop_gui() {
    if [ -d /etc/upstart ]; then
        trap "" TERM
        stop lab126_gui
        usleep 1250000
        trap - TERM
    else
        /etc/init.d/framework stop
    fi
}

start_gui() {
    if [ -d /etc/upstart ]; then
        cd / && start lab126_gui
    else
        cd / && /etc/init.d/framework start
    fi
}

finish() {
    [ -n "$browser_pid" ] && kill "$browser_pid" 2>/dev/null
    killall kindle_browser 2>/dev/null
    lipc-set-prop com.lab126.powerd preventScreenSaver 0
    clear_screen
    start_gui
    exit 0
}

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
    --enable-grayscale-mode --enable-low-end-device-mode --enable-low-res-tiling \
    --disable-site-isolation-trials >/dev/null 2>&1 &
browser_pid=$!
unset LD_LIBRARY_PATH

trap finish INT TERM

# Wait for one press of the power button (key 116, EV_KEY, pressed), then put the Kindle back.
while true; do
    event=$(dd if="$POWER_DEVICE" bs=16 count=1 2>/dev/null | hexdump -v -e '16/1 "%02X"')
    if [ "${event:16:4}" = "0100" ] && [ "${event:20:4}" = "7400" ] && [ "${event:24:8}" = "01000000" ]; then
        finish
    fi
    # The browser closed by itself: give the Kindle back rather than leave a blank screen.
    kill -0 "$browser_pid" 2>/dev/null || finish
done
