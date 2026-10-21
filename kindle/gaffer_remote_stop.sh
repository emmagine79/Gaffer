#!/bin/sh
# Name: Gaffer remote stop
# Author: Gaffer
# DontUseFBInk
#
# Closes the Gaffer remote and lets the Kindle sleep again, if the power button did not.

killall kindle_browser 2>/dev/null
lipc-set-prop com.lab126.powerd preventScreenSaver 0
eips -c >/dev/null 2>&1
if [ -d /etc/upstart ]; then
    cd / && start lab126_gui
else
    cd / && /etc/init.d/framework start
fi
