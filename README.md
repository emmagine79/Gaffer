# Gaffer

Gaffer is a free, open-source app that controls studio lights from different brands in one place. It lives in the Mac menu bar, opens into a full Mac window, and works on any phone in a browser.

Version 1 supports:

- Godox Bluetooth mesh lights (186 models, including the Litemons LA150Bi)
- Zhiyun ZY Vega lights (including the MOLUS G200)
- Yongnuo Bluetooth lights (including the YN150Li)

Gaffer is being built. Today it scans for nearby lights and shows them by brand, and it carries the Godox studio from lumen-studio (colour, white, effects, scenes, schedules). That control has been tested in demo mode and with the library's own tests, not yet on real lights, and Zhiyun and Yongnuo control is not built yet.

## Install Gaffer

Gaffer needs a Mac with Apple silicon and macOS 14 or later. These steps are written for macOS 26 and later.

Gaffer is free and has no Apple Developer ID, so it is not notarised. macOS will not open it with a double-click the first time. You approve it once in System Settings. This is what Gatekeeper, the macOS check on downloaded apps, does with it.

1. Download `Gaffer-<version>-macos-arm64.zip` from the [Releases page](https://github.com/emmagine79/Gaffer/releases). To check the download, run `shasum -a 256 -c Gaffer-<version>-macos-arm64.zip.sha256` in the folder that holds both files.
2. Open the zip (double-click it in Downloads). You get `Gaffer.app`. Drag it into your Applications folder.
3. Double-click `Gaffer.app`. macOS stops and tells you it can't verify the app. Close the message. Do not move the app to the Bin.
4. Open System Settings, click Privacy & Security, scroll down to the Security section and click **Open Anyway** next to the message about Gaffer.
5. The warning comes back. Click **Open**, and enter your password or use Touch ID if macOS asks.
6. Gaffer opens in the menu bar as a light bulb. From now on a double-click opens it like any other app.
7. The first time Gaffer scans for lights, macOS asks: "Gaffer" would like to use Bluetooth. Click **Allow**. If you click Don't Allow, turn it on later in System Settings, Privacy & Security, Bluetooth.

Source: Apple's [Safely open apps on your Mac](https://support.apple.com/en-us/102445) (page dated 27 May 2026). For an app that is not notarised or is from an unidentified developer, it gives these steps: try to open the app, then open System Settings, click Privacy & Security, click Open Anyway, and click Open in the prompt that comes back. Older guides say to control-click the app and choose Open. Apple's current page does not list that step, so this guide does not rely on it. If it still works on your Mac, it does the same job.

Screenshots of each step are being added to [`docs/install/`](docs/install/README.md); they are taken on a fresh macOS 26 account.

### What the signature means

Gaffer is signed with a self-signed certificate called "Gaffer Local Signing". The same certificate signs every release, so macOS remembers your Bluetooth choice when you update Gaffer. The app's code requirement names that certificate, so an app signed with a different certificate does not satisfy it and does not inherit Gaffer's Bluetooth permission.

The trade-off: there is no Developer ID, so Apple has not vouched for who made the certificate, and macOS shows the warning above. Whoever holds the certificate's private key can sign an app that macOS treats as Gaffer. The key lives in a keychain file on the maker's Mac and is not in this repository. To see what an app is signed with, run `codesign -dvv /Applications/Gaffer.app` (look for `Authority=Gaffer Local Signing`) and `codesign -d -r- /Applications/Gaffer.app`.

### Use Gaffer

Gaffer appears in the menu bar as a light bulb and opens a window listing nearby lights. To quit, choose Quit Gaffer from the menu-bar icon. The light service stops with it, so no Python process is left running.

### Use a Kindle as a remote

A jailbroken Kindle can show a black-and-white remote that stays on. See [kindle/README.md](kindle/README.md).

## Build the app

You need the Xcode command line tools, [uv](https://docs.astral.sh/uv/) and [Node](https://nodejs.org/) with npm (the build compiles `web/`).

```sh
scripts/build_app.sh               # builds dist/Gaffer.app and the release zip, and copies the app to ~/Applications
scripts/build_app.sh --no-install  # builds dist/ only
```

`dist/` then holds `Gaffer.app`, `Gaffer-<version>-macos-arm64.zip` (the file for a GitHub Release), its `.sha256`, and `Gaffer-<version>.manifest.txt` (every file in the app and its hash).

The app carries its own Python 3.14 ([python-build-standalone](https://github.com/astral-sh/python-build-standalone), installed by uv) and the packages in `service/uv.lock`, so it never uses a system or Homebrew Python. Python's licence and each package's licence are inside the app, in `Contents/Resources/LICENSES`, and `Contents/Resources/NOTICE` lists them. The build stops if a package has no licence text.

**Signing.** The first build makes the "Gaffer Local Signing" certificate in its own keychain file, `~/Library/Application Support/Gaffer-build/signing.keychain-db` (change the folder with `GAFFER_BUILD_HOME`). It is not added to your login or system keychain, and no trust setting changes. Later builds on this Mac reuse it, so the app's code requirement is the same every time and macOS keeps the Bluetooth permission across rebuilds. A build on another Mac makes its own certificate, so that Mac's builds are separate. Keep the keychain folder private. If the certificate can't be made or used, the build stops; it never falls back to ad-hoc signing by itself.

`GAFFER_SIGN=adhoc scripts/build_app.sh --no-install` is a developer flag for a quick local build. It signs ad hoc, which gives a new signature on every build, so macOS asks for Bluetooth again each time. It never makes a release zip, and it is never installed to `~/Applications` (the flag is implied).

**Reproducible.** Two builds of the same commit give the same files: the manifest matches, and so does the code requirement. Only each signature's signing time differs, so the zip's bytes are not identical. Every file is dated with the commit's date. `mac/tests/test_build.py` builds twice from two clean clones and compares.

## Logs

The service writes `~/Library/Logs/Gaffer/service.log`. Each time Gaffer starts, the last run's log becomes `service.previous.log` (replacing the one before) and a new `service.log` begins. So there are two files at most: this run and the one before. No size figure is set, because no platform or contract sets one.

## How it is put together

| Folder | What it is |
| --- | --- |
| `mac/` | Swift shell: menu-bar item and a window with a web view (`mac/Sources`), `Info.plist`, icon drawing (`mac/Icon`), app tests (`mac/tests`) |
| `service/` | Python light service (FastAPI and bleak), the `gaffer` package: Bluetooth scan and brand tagging, the lights engine (from lumen-studio), HTTP API and WebSocket. `service/packages/godox-mesh-bt` is the Godox mesh library |
| `web/` | The web interface (React and Vite, from lumen-studio). The build puts `web/dist` inside the app and the service serves it |
| `THIRD-PARTY/` | Licences and notices for code taken from other projects |
| `scripts/build_app.sh` | Builds `dist/Gaffer.app` |

The Swift shell starts the bundled Python service as its child process on `127.0.0.1` and shows its page. Because Gaffer starts the service, macOS treats Gaffer as the responsible app and asks for Bluetooth in Gaffer's name. The same Python started from Terminal is checked against Terminal instead. The service reads its stdin from a pipe only Gaffer holds, and exits when that pipe closes, so it stops however Gaffer ends, even if Gaffer crashes. Service logs go to `~/Library/Logs/Gaffer/service.log` (see Logs above).

### Who can use the service

The service listens on `127.0.0.1` only and refuses any Host header other than `127.0.0.1` or `localhost`, so a web page can't reach it by DNS rebinding. Gaffer makes a random secret at each launch and passes it to the service on stdin. Gaffer's window signs in once with `/session?key=<secret>`, which sets an HttpOnly, SameSite=Strict cookie; every other route answers 401 without it. Local tools can find the port and secret in `~/Library/Application Support/Gaffer/run/service-<pid>.json` (readable only by you, removed when the service stops). Phone access with a PIN comes later.

### Service API

All routes need the session cookie.

| Route | What it returns |
| --- | --- |
| `GET /api/health` | `{"ok": true, "service": "gaffer", "demo": false, ...}` when the service is running |
| `GET /api/bluetooth` | Bluetooth permission: `not_determined`, `allowed`, `denied` or `restricted` |
| `GET /api/scan?seconds=6` | Nearby devices with name, signal, brand family and the advert data that matched. Scans 2 to 20 seconds |
| `GET /scan` | A plain page that runs the scan and lists what it hears |
| `GET /` | The web interface |
| `GET /kindle` | The e-ink remote for a Kindle: all on and off, looks, cues, and power, brightness and colour temperature per light. See [kindle/README.md](kindle/README.md) |
| `/ws` | The WebSocket the web interface uses to drive lights. Needs the session cookie and the page's own Origin |

`python -m gaffer --demo` runs simulated lights and starts no Bluetooth scan, for development and tests.

## Tests

```sh
cd service && uv run --frozen pytest                         # the service: lumen-studio's suite and the scan tagging
scripts/build_app.sh --no-install
uv run --project service --frozen pytest mac/tests           # launches the built app
uv run --project service --frozen pytest mac/tests/test_build.py mac/tests/test_quit.py   # build, quit and log checks: no app is opened
```

The app tests launch Gaffer from a folder with a space in its path, and need Bluetooth permission already granted for the scan test.

## Credits

Gaffer builds on these MIT-licensed projects:

- [Rkcr7/lumen-studio](https://github.com/Rkcr7/lumen-studio): Godox driver, model table, effects, scenes, schedules and cues. The service and web interface start from a copy of it (see [NOTICE](NOTICE))
- [didim99/HA-Zhiyun-Light](https://github.com/didim99/HA-Zhiyun-Light): Zhiyun protocol, and the Zhiyun light name prefixes used by the scan
- [aaditagrawal/zhiyun-light-control](https://github.com/aaditagrawal/zhiyun-light-control): Zhiyun protocol
- [asidjwiaijd/yongnuo-light-control](https://github.com/asidjwiaijd/yongnuo-light-control): Yongnuo protocol, and the Yongnuo name rule used by the scan

Each one's licence is kept with the code taken from it, in `THIRD-PARTY/`. [NOTICE](NOTICE) lists the credits, including godox-ul60bi-bt and ha-godox-mesh, which lumen-studio is built on.

## Licence

MIT. See [LICENSE](LICENSE).
