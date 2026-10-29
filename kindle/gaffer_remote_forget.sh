#!/bin/sh
# Name: Gaffer remote forget Mac
# Author: Gaffer
# DontUseFBInk
#
# Forgets the Mac the Gaffer remote last used, so the next Gaffer remote looks for Gaffer on the
# Wi-Fi again. Use it to move the remote to another Mac. The PIN is asked for again only if the
# other Mac's PIN is different.

rm -f "${GAFFER_SAVE_FILE:-/mnt/us/system/gaffer_mac}"
eips 1 1 "Gaffer remote: Mac forgotten" >/dev/null 2>&1
sleep 3
eips -c >/dev/null 2>&1
exit 0
