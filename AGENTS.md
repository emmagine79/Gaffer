# Gaffer: instructions for coding agents

Gaffer is an open-source (MIT) Mac app that controls studio lights from different brands. Read `SPEC.md` and `PRIOR-ART.md` in the parent folder for the contract. They are not in this repo.

## Layout

| Folder | What it holds |
| --- | --- |
| `service/` | Python light service, package `gaffer` (`service/gaffer/`), built on lumen-studio. `service/packages/godox-mesh-bt` is the Godox mesh library, kept unchanged. Tests in `service/tests/` |
| `web/` | Web interface (React and Vite). `npm run build` writes `web/dist`, which the service serves |
| `mac/` | Swift menu-bar shell with a WKWebView, `Info.plist`, icon, and the tests that launch the built app (`mac/tests/`) |
| `contracts/` | The HTTP and WebSocket contract between the service and its clients (`api.md`). Not created yet; a later card adds it |
| `scripts/` | `build_app.sh` builds `dist/Gaffer.app` and the release zip; `sign_app.sh` signs it; `bundle_tool.py` prepares the bundled Python and its licences |
| `backlog/` | Cards for the work. The conductor owns it; builders do not edit it |
| `THIRD-PARTY/`, `NOTICE` | Licences and credits for code taken from other projects |

## Build and test

```sh
cd service && uv run --frozen pytest        # service tests, including lumen-studio's
cd web && npm ci && npm test && npm run build
scripts/build_app.sh --no-install           # needs Xcode command line tools, uv, node
uv run --project service --frozen pytest mac/tests   # launches the built app: see the Bluetooth rule below
python -m gaffer --demo                     # simulated lights, no Bluetooth (run from service/)
```

Run test and build commands through `~/.claude/skills/fleet-conductor/scripts/memguard.py run -- <command>` when you work in the fleet.

## Rules

- Never send a command to a real light unless Captain is present. Use `--demo` for anything live.
- `Gaffer.app` is signed with a fixed self-signed identity (`scripts/sign_app.sh`), so its code requirement is stable and macOS keeps the Bluetooth permission across rebuilds on one Mac. The first launch of an app signed by a new identity still asks. Do not launch a rebuilt app to scan unless Captain is there. Prove a build with `/api/health` and with the bundled Python run in `--demo` mode. `GAFFER_SIGN=adhoc` is for quick local builds only and makes no release zip and never installs. Never make signing fall back to ad hoc by itself: any app signed ad hoc with the same bundle id would inherit the permission.
- Never add the research folders (`apks/`, `vega-xapk/`, `dex/`, `gdex/`, `so/`, `assets/`, `f100/`, `evidence/`) or any `.apk`, `.dex`, `.so`, `.xapk` or `.jar` file. Check with `git ls-files` before you commit.
- Copy code only from MIT-licensed repos, and credit it: add the licence to `THIRD-PARTY/` and a line to `NOTICE`.
- No real keys, addresses or device ids in fixtures. Use invented values.
- Errors that reach the page or an API answer say what went wrong in plain words. They never carry a path on this Mac.

## Coding rules

- Every `FileHandle` `readabilityHandler` sets itself to nil when it reads empty data (EOF). Otherwise it fires again at once, forever, and keeps several cores busy (SPEC-001 retro).
- Only Python opens Bluetooth. The Swift shell never links CoreBluetooth.
- The service listens on `127.0.0.1` only, until the Mac window switches phone access on (`service/gaffer/phone.py`). Once on, phone access stays on across restarts, with the same PIN and port, until it is switched off (Captain, 18 Oct 2026). A save that fails never lets an older setting come back: `phone.json` is removed or overwritten, and the Mac window gets a `notice` (contracts/api.md) whenever a save fails or when phone access could not be reopened at start. Every route and the `/ws` socket need a cookie: the Mac window's session cookie, or a phone's PIN cookie (`service/gaffer/session.py`).
