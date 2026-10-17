# Gaffer

Gaffer is a free, open-source app that controls studio lights from different brands in one place. It lives in the Mac menu bar, opens into a full Mac window, and works on any phone in a browser.

Version 1 supports:

- Godox Bluetooth mesh lights (186 models, including the Litemons LA150Bi)
- Zhiyun ZY Vega lights (including the MOLUS G200)
- Yongnuo Bluetooth lights (including the YN150Li)

Gaffer is being built. Today it scans for nearby lights and shows them by brand. It never sends anything to a light yet.

## Open Gaffer

Double-click `Gaffer.app` in your Applications folder (`~/Applications/Gaffer.app` after a build). It appears in the menu bar as a light bulb and opens a window listing nearby lights.

The first time it scans, macOS asks: "Gaffer" would like to use Bluetooth. Click Allow. If you click Don't Allow, turn it on later in System Settings, Privacy & Security, Bluetooth.

To quit, choose Quit Gaffer from the menu-bar icon. The light service stops with it.

## Build the app

You need the Xcode command line tools and [uv](https://docs.astral.sh/uv/).

```sh
scripts/build_app.sh               # builds dist/Gaffer.app and copies it to ~/Applications
scripts/build_app.sh --no-install  # builds dist/Gaffer.app only
```

The app carries its own Python 3.14 ([python-build-standalone](https://github.com/astral-sh/python-build-standalone), installed by uv), so it never uses a system or Homebrew Python. The build is ad-hoc signed. Each new build has a new signature, so macOS asks for Bluetooth permission again after every rebuild.

## How it is put together

| Folder | What it is |
| --- | --- |
| `mac/` | Swift shell: menu-bar item and a window with a web view (`mac/Sources`), `Info.plist`, icon drawing (`mac/Icon`), app tests (`mac/tests`) |
| `service/` | Python light service (FastAPI and bleak): Bluetooth scan, brand tagging, HTTP API and the web page |
| `scripts/build_app.sh` | Builds `dist/Gaffer.app` |

The Swift shell starts the bundled Python service as its child process on `127.0.0.1` and shows its page. Because Gaffer starts the service, macOS treats Gaffer as the responsible app and asks for Bluetooth in Gaffer's name. The same Python started from Terminal is checked against Terminal instead. The service reads its stdin from a pipe only Gaffer holds, and exits when that pipe closes, so it stops however Gaffer ends, even if Gaffer crashes. Service logs go to `~/Library/Logs/Gaffer/service.log`.

### Who can use the service

The service listens on `127.0.0.1` only and refuses any Host header other than `127.0.0.1` or `localhost`, so a web page can't reach it by DNS rebinding. Gaffer makes a random secret at each launch and passes it to the service on stdin. Gaffer's window signs in once with `/session?key=<secret>`, which sets an HttpOnly, SameSite=Strict cookie; every other route answers 401 without it. Local tools can find the port and secret in `~/Library/Application Support/Gaffer/run/service-<pid>.json` (readable only by you, removed when the service stops). Phone access with a PIN comes later.

### Service API

All routes need the session cookie.

| Route | What it returns |
| --- | --- |
| `GET /api/health` | `{"ok": true}` when the service is running |
| `GET /api/bluetooth` | Bluetooth permission: `not_determined`, `allowed`, `denied` or `restricted` |
| `GET /api/scan?seconds=6` | Nearby devices with name, signal, brand family and the advert data that matched. Scans 2 to 20 seconds |

## Tests

```sh
cd service && uv run --frozen pytest                         # brand tagging
scripts/build_app.sh --no-install
uv run --project service --frozen pytest mac/tests           # launches the built app
```

The app tests launch Gaffer from a folder with a space in its path, and need Bluetooth permission already granted for the scan test.

## Credits

Gaffer builds on these MIT-licensed projects:

- [Rkcr7/lumen-studio](https://github.com/Rkcr7/lumen-studio): Godox driver, model table, effects, scenes, schedules and cues. Gaffer's Godox advert reader comes from it (`service/src/gaffer_service/godox_advert.py`)
- [didim99/HA-Zhiyun-Light](https://github.com/didim99/HA-Zhiyun-Light): Zhiyun protocol, and the Zhiyun light name prefixes used by the scan
- [aaditagrawal/zhiyun-light-control](https://github.com/aaditagrawal/zhiyun-light-control): Zhiyun protocol
- [asidjwiaijd/yongnuo-light-control](https://github.com/asidjwiaijd/yongnuo-light-control): Yongnuo protocol, and the Yongnuo name rule used by the scan

Each one's licence is kept with the code taken from it, in `service/third_party/`.

## Licence

MIT. See [LICENSE](LICENSE).
