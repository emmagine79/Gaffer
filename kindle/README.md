# Kindle remote

A jailbroken Kindle can show Gaffer as a black-and-white remote that stays on. The Mac still does all the Bluetooth. The Kindle only shows a web page that Gaffer serves at `/kindle`.

The remote has:

- all on and all off
- a button for each saved look
- Go and Back while a cue list is running
- one card per light, with on and off, brightness and colour temperature, and Max next to On on a light that has Max Mode (the MOLUS G200)
- tap + or − to move brightness 1% (colour temperature 100 K); hold it to keep going, faster the longer you hold

It signs itself back in after Gaffer, the Mac or the Kindle restarts, even when the Mac comes back at a new Wi-Fi address. It asks for the PIN again only after New PIN on the Mac, or after too many wrong PINs.

## What you need

- a jailbroken Kindle on firmware 5.16.4 to 5.18.3. Those versions can use the [Sanctuary jailbreak](https://kindlemodding.org/jailbreaking/Sanctuary/)
- the Kindle on the same Wi-Fi as the Mac
- phone access switched on in Gaffer (the Phone button in the Mac window)

## Set it up

1. In Gaffer on the Mac, open Phone and switch on phone access. Note the PIN, and the port: the number after the colon in the Wi-Fi address.
2. If the port is not 54342, open `gaffer_remote.sh` in a text editor and set `PORT` to it.
3. Connect the Kindle to the Mac by USB. Copy `gaffer_remote.sh`, `gaffer_remote_stop.sh` and `gaffer_remote_forget.sh` into the Kindle's `documents` folder. Eject the Kindle.
4. On the Kindle, open the library. Tap Gaffer remote. It shows "Looking for Gaffer on this Wi-Fi", then the remote.
5. Enter the PIN on the remote's number pad. The lights appear.

You don't need the Mac's Wi-Fi address. The remote finds the Mac on the Wi-Fi by itself, and finds it again when the Mac gets a new address, for example after a restart. If Gaffer isn't running, it says so and keeps looking until it is.

To move the remote to another Mac, tap Gaffer remote forget Mac in the library, then Gaffer remote. If the other Mac has a different PIN, the remote asks for it.

To leave the remote, tap Exit at the top right, or press the power button once. The power button also works while the remote is still looking for the Mac. The Kindle stays awake only while the remote is open; once you leave, it sleeps as usual. If the screen ever stops answering, tap Gaffer remote stop in the library, or hold the power button until the Restart option appears.

You can also open `/kindle` in the Kindle's own browser without a jailbreak. It works the same, but the address bar stays on screen, the Kindle still goes to sleep, and you type the Mac's address yourself.

## How it works

`gaffer_remote.sh` stops the Kindle's reading interface, finds the Mac, opens the Kindle's own Chromium browser full screen on Gaffer's `/kindle` page, and tells the power manager not to start the screensaver (`lipc-set-prop com.lab126.powerd preventScreenSaver 1`).

Finding the Mac: the script asks the last Mac it used (kept in `/mnt/us/system/gaffer_mac`) for `GET /api/hello`, which Gaffer answers without a PIN and which says only that it is Gaffer. If that Mac doesn't answer, it asks every address on the Kindle's Wi-Fi network, 32 at a time, and keeps the first that answers. On a home network that takes up to about half a minute. While the remote is open, it checks every 30 seconds that the Mac is still there, and looks again if it isn't.

The browser always opens `http://gaffer.invalid:PORT/kindle`, with `--host-resolver-rules` mapping that name to the address it found. Gaffer accepts that name. Because the page's name never changes, the PIN the page saved is still there when the Mac's address changes. `.invalid` never resolves in real DNS, so no web page can borrow it. If your Kindle's browser ignores the mapping and shows a "can't be reached" page, set `STABLE_NAME=no` in the script: it then opens the Mac's address itself, and asks for the PIN again each time that address changes.

A press of the power button closes the browser, lets the Kindle sleep again and brings the reading interface back. The script reads the power button's input device from `/proc/bus/input/devices`, so it works whichever device number the button has. If the browser closes on its own, as after Exit, the script brings the reading interface back too. If no power button can be read, the script exits and leaves the reading interface running.

The page is plain ES5 with no build step, so the Kindle's browser runs it as it is. It draws only what changed, which keeps e-ink redraws down.

## Credits

The browser flags in `gaffer_remote.sh` follow [kindle-shortcut-browser](https://github.com/mitchellurgero/kindle-shortcut-browser), which found the set that works with the Kindle's Chromium. No code is copied from it.
