# Kindle remote

A jailbroken Kindle can show Gaffer as a black-and-white remote that stays on. The Mac still does all the Bluetooth. The Kindle only shows a web page that Gaffer serves at `/kindle`.

The remote has:

- all on and all off
- a button for each saved look
- Go and Back while a cue list is running
- one card per light, with on and off, brightness and colour temperature

It signs itself back in after Gaffer or the Kindle restarts. It asks for the PIN again only after New PIN on the Mac.

## What you need

- a jailbroken Kindle on firmware 5.16.4 to 5.18.3. Those versions can use the [Sanctuary jailbreak](https://kindlemodding.org/jailbreaking/Sanctuary/)
- the Kindle on the same Wi-Fi as the Mac
- phone access switched on in Gaffer (the Phone button in the Mac window)

## Set it up

1. In Gaffer on the Mac, open Phone and switch on phone access. Note the Wi-Fi address and the PIN.
2. Open `gaffer_remote.sh` in a text editor. Set `GAFFER_URL` to the Wi-Fi address with `/kindle` on the end, for example `http://192.168.1.20:8787/kindle`.
3. Connect the Kindle to the Mac by USB. Copy `gaffer_remote.sh` and `gaffer_remote_stop.sh` into the Kindle's `documents` folder. Eject the Kindle.
4. On the Kindle, open the library. Tap Gaffer remote.
5. Enter the PIN on the remote's number pad. The lights appear.

To leave the remote, press the power button once. The script finds the power button by itself. If the screen ever stops answering, tap Gaffer remote stop in the library, or hold the power button until the Restart option appears.

You can also open `/kindle` in the Kindle's own browser without a jailbreak. It works the same, but the address bar stays on screen and the Kindle still goes to sleep.

## How it works

`gaffer_remote.sh` stops the Kindle's reading interface, opens the Kindle's own Chromium browser full screen at `GAFFER_URL`, and tells the power manager not to start the screensaver (`lipc-set-prop com.lab126.powerd preventScreenSaver 1`). A press of the power button closes the browser, lets the Kindle sleep again and brings the reading interface back. The script reads the power button's input device from `/proc/bus/input/devices`, so it works whichever device number the button has. If the browser closes on its own, the script brings the reading interface back too. If no power button can be read, the script exits and leaves the reading interface running.

The page is plain ES5 with no build step, so the Kindle's browser runs it as it is. It draws only what changed, which keeps e-ink redraws down.

## Credits

The browser flags in `gaffer_remote.sh` follow [kindle-shortcut-browser](https://github.com/mitchellurgero/kindle-shortcut-browser), which found the set that works with the Kindle's Chromium. No code is copied from it.
