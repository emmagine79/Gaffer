# Gaffer API contract

The HTTP and WebSocket contract between the Gaffer service and its clients (the web UI, the Mac shell).

## Service

Everything in this section is served by the Python service in `service/`. It listens on `127.0.0.1`, and also on the network while phone access is on (see Phone access). Every route and `/ws` need a cookie: the Mac window's session cookie, or a phone's PIN cookie. Errors are `{"error": "<code>", "message": "<plain words>"}` and never carry a path.

### GET /api/models

Every model Gaffer knows, whatever the brand. Godox models come from lumen's table (`service/gaffer/data/models.json`). Every other model comes from a model file. In demo mode the list also holds demo-only stand-ins.

```json
{
  "models": [
    {
      "id": "003A", "radio_id": "003A", "name": "SL60IIBi",
      "kind": "bicolour", "kind_label": "Bi-colour",
      "driver": "godox", "brand": "Godox",
      "match": {"name_prefix": "PL1", "service": "0000fee9-0000-1000-8000-00805f9b34fb"},
      "features": {"white": true, "daylight": false, "colour": false, "channels": false, "tint": false,
                   "gels": "white", "builtin_effects": 0, "fan": false, "battery": false,
                   "smoothness": false, "control_modes": false}
    }
  ],
  "skipped": [{"file": "zhiyun/BAD.json", "reason": "driver does not match the folder"}],
  "drivers": [{"id": "godox"}],
  "drivers_skipped": [{"driver": "somebrand", "reason": "could not be imported"}]
}
```

- `features` is `ModelCaps.features`. Its keys do not change; the Glass UI lays out its controls from it.
- `id` is the model id. `radio_id` is the same value, kept for older clients.
- `match` is `{}` for Godox table rows.
- `skipped` lists model files that could not be used, with a reason in plain words. `file` is `<driver>/<name>.json` and never an absolute path.
- The WebSocket `hello` message keeps its `models` list (id, name, kind, driver, brand) for the model picker. It leaves out demo stand-ins.

### GET /api/lights

Every saved light with its abilities and its current state: the same `lights`, `gel_tables` and `network` that the WebSocket `lights` message carries, without `type`. Read-only. The web tests use it to check what the service holds after a control moves.

```json
{
  "lights": [{"id": "...", "name": "Key light", "model": "ML100R", "caps": {"features": {"white": true, "colour": true}}, "state": {"power": true, "brightness": 40, "mode": "cct"}, "online": true}],
  "gel_tables": {"native:2": [{"...": "..."}]},
  "network": "<mesh network name or null>"
}
```

- Each light is the object `hello` gives, with `online` (reachable or on the mesh). `state` has `power`, `brightness`, `mode` (`cct`, `hsi`, `rgbw`, `gel` or `fx`) and one object per mode. `caps.features` does not change its keys.
- `gel_tables` is keyed by the gel table a light uses (its `gel_key`). `network` is the mesh network name, a string, or `null` when no light is saved or the link is dropped.

### Model files

One file per model: `service/gaffer/models/<driver>/<ID>.json`. The service also reads `<data folder>/models/<driver>/<ID>.json` (on a Mac, `~/Library/Application Support/Gaffer/models/`), so a model can be added with no code change. A file with the same `id` as a table row replaces that row. A later folder replaces an earlier one.

A model file is one row of lumen's `models.json` plus these keys:

| Key | Type | Rule |
| --- | --- | --- |
| `id` | string | Required. Characters from `A-Z a-z 0-9 _ -`, starting with a letter or digit (the id is also a file name, so no separators or dots). Case-insensitive. Must equal the file name without `.json`. `constructor`, `prototype` and similar names are refused. |
| `driver` | string | Required. Must equal the folder name. It should name a folder under `service/gaffer/drivers/`; if it does not, the light is unreachable. |
| `brand` | string | Required. Non-empty text. Shown to people. |
| `name` | string | Required. Non-empty text. |
| `min_kelvin`, `max_kelvin` | integer | Required. Whole numbers from 0 up, `min_kelvin` not above `max_kelvin`. |
| `modes` | list of strings | `cct`, `hsi`, `rgb`, `color_chip`, `effects` and so on. Default empty. |
| `match` | object | Optional. `name_prefix` (non-empty text) and `service` (a Bluetooth UUID, 16, 32 or 128 bit). No other keys. |
| `driver_data` | object | Optional. Whatever the driver needs for this model. Opaque to everything else. |

Every other lumen row key (`effects`, `fan_modes`, `rgb_channels`, `battery`, `gm_min`, `gm_max` and so on) is optional and read as in `models.json`.

A file that breaks a rule, cannot be read, or is not a plain file is skipped with a reason. The rest still load. An unreadable file never replaces the row it was meant to override. Gaffer sets no limit on file size, file count or text length. A file that cannot be read or parsed for any reason is skipped with a plain reason.

### Drivers

A driver is a folder under `service/gaffer/drivers/<name>/` that defines a concrete subclass of `gaffer.drivers.base.Driver`. The registry (`gaffer.drivers.build_drivers`) imports every folder and registers its drivers. A folder that fails to import is skipped and reported in `drivers_skipped`.

The contract is in `service/gaffer/drivers/base.py`: `id`, `match(advert)`, `start()`, `stop()`, `connect(light)`, `apply(light, LightState)`, `identify(light)`, `status(light)` returning `{reachable, held}`, `forget_light(light_id)`, and pure `encode_*` functions beside the driver. `forget_light` is async and has a no-op default. When it returns, the driver holds no link to that light and writes nothing more to it. The hub awaits it, and logs and carries on if it raises, before a light's new driver connects, so two drivers never drive one light. `stop()` and `forget_light()` each get the hub's stop budget; a driver that does not return in time is logged and skipped. `apply` is synchronous, never blocks, and the latest state wins.

A light uses the driver its model's `driver` key names. If that driver is not installed, the light shows as unreachable and takes no commands. The same holds for a light whose model is not known and whose id is not shaped like a Godox radio id (four hex digits): it is never commanded as a Godox light. A Godox-shaped unknown id is commanded generically, as lumen does.

### Light fields

The light objects in `hello`, `lights` and `/api/export` gain:

- `channel`: integer or null. The radio channel a light is set to, for brands that need one told to them (Yongnuo). Saved with the light.
- `caps.driver`, `caps.brand`, `caps.match`, `caps.driver_data`.

### Sync groups (WebSocket `/ws`)

A group is `{id, name, members: [light id], props, enabled}`. `props` are any of `power`, `brightness`, `white`, `colour`, `effects`. A light is in one group at a time. `hello` and every change carry the list: `{"type": "groups", "groups": [...]}`.

- `{"type": "group.save", "group": {...}, "leader": "<light id>"}` creates a group (no `id`) or updates one. Answers `{"type": "ack", "of": "group.save", "group": {...}}`. Names are cut to 40 characters.
- `props` with no list at all means every property. An empty list `[]` means the group shares nothing: its lights stay in the group but no `set` moves the others.
- The other members take the `leader` light's shared properties only when a save switches the group on, adds a light, or adds a shared property, and only when `leader` is a member (it defaults to the light this client has selected). A save that only removes a light or a property, renames the group, or names a leader outside the group moves no light.
- `{"type": "group.delete", "id": "<group id>"}` removes the group. Its lights no longer follow each other.
- While a group is enabled with two or more members, any `set` on one member moves the others (only the shared `props`).

### WebSocket command: set.many

One fader over several lights (the lighting desk). `{"type": "set.many", "anchor": "<light id>", "lights": ["<light id>", ...], "brightness": 80}`. Answers `{"type": "ack", "of": "set.many"}`.

- `anchor` is the light being dragged. It must be one of `lights`. `brightness` is its new level, 0 to 100.
- The service reads each light's current level itself (a fade's destination, not its middle) and moves the others by the same ratio: 40, 25 and 60 with the first dragged to 80 become 80, 50 and 100. If the anchor was at 0 it has no ratio, so the others take the same absolute step. Levels are held between 0 and 100. The rule is `service/gaffer/levels.py`.
- Only brightness changes. Power, colour and mode stay as they were. Each light's effect stops, as for `set`.
- `start_levels` (optional) is an object of light id to level, 0 to 100, for every id in `lights`, as they were when the drag began. The desk sends it on every message of one drag. The service then takes the ratio from those levels instead of the current ones, so dragging the anchor to 0 or past a limit and back gives the original balance again. Without it the service uses the current levels.
- `lights` may not hold more ids than the studio has lights. An unknown or empty id, a level that is not a number, a `start_levels` that does not cover exactly `lights`, or a light that cannot take the level is refused with an `error` reply and no light moves.

## Mac shell

The Swift shell (`mac/`) and the Python service (`service/`) follow this file.
Change it first, then change both sides. SPEC-016 wrote it; SPEC-010 (looks) and
SPEC-014 (cues) build the routes.

Only the routes the shell calls are listed here. The web page's own routes belong
to the card that adds them.

### Who may call

Same rules as `service/gaffer/session.py` (SPEC-001):

- The service listens on `127.0.0.1` only.
- `Host` must be `127.0.0.1` or `localhost`, any port. Anything else gets `400`.
- Every route needs the cookie `gaffer_session=<secret>`. Without it: `401`
  `{"error":"not_signed_in"}`.
- This includes the WebSocket upgrade: the cookie and Host checks run before the
  upgrade is accepted (SPEC-002 added this).
- The shell made the secret, so it sends the cookie itself. It does not need the
  one-time `/session` link for its own calls. Its web views use that link once.

### Errors

Every refusal is JSON: `{"error": "<code>", "message": "<plain words>"}`. The message
never holds a path, a stack or a raw exception.

### Routes

| Method and path | Answer | Built by |
|---|---|---|
| `GET /api/looks` | `200 {"looks":[{"id":"talking-head","name":"Talking head"}, ...]}` in slot order. Slot 1 is the first entry. Empty list is valid. | SPEC-010 |
| `POST /api/looks/{id}/apply` | `200 {"ok":true,"look":{"id":"...","name":"..."}}`. Unknown id: `404 {"error":"look_not_found"}`. No request body. `{id}` is percent-encoded. | SPEC-010 |
| `POST /api/all-off` | `200 {"ok":true}`. Turns every light off. | No card yet. SPEC-010 puts All off on the page but does not name this route. |
| `POST /api/cues/active/go` | `200 {"ok":true,"look":{"id":"...","name":"..."}}` after stepping to the next look. No active cue list: `409 {"error":"no_active_cue"}`. | SPEC-014. Its card names `POST /api/cues/{id}/go`, so that route must also accept the id `active`. |

If a route answers with an error, a shortcut press beeps once and the shell shows the
service's `message` (or a plain one of its own) in the right-click menu. It never retries.

Applying a look, all off and a cue step each change the current look. The service
tells every WebSocket client (below). The shell never decides the look itself.

### Page

`GET /?surface=menubar|window|bare` serves the one web UI (SPEC-006). `menubar` is the panel
under the menu-bar icon. `window` is the Mac window. `bare` is a phone or browser.

### WebSocket

`GET /ws`, upgraded. Text frames, one JSON object each.

Service to shell:

```json
{"type":"look","name":"Talking head"}
```

- `name` is the current look's name, or `null` when no look is active (for example
  after All off).
- The service sends this once as soon as the socket opens, then again every time
  the current look changes. SPEC-010 builds it. The current `hello` frame does not carry
  it, and the shell ignores `hello`, so SPEC-010 must send a separate `look` frame.
- The shell ignores any other `type`, so the service may add messages.

The shell sends nothing. If the socket closes, the shell shows no look name and
reconnects with back-off until the service process ends.

## Phone access

Off at every launch. The Mac window switches it on; then the service also listens on all network addresses at the same port, and a phone gets in with a PIN. Two kinds of caller: the **Mac window** (peer address is loopback and `Host` is `127.0.0.1` or `localhost`; needs the launch secret cookie, no PIN) and a **phone** (anything else; needs the PIN cookie).

A phone's request is refused when:

| Case | Answer |
| --- | --- |
| Phone access is off | `403 phone_access_off` (socket closed with code 4403) |
| The connection comes from a public address: not loopback, private IPv4 (RFC 1918), link-local (RFC 3927, RFC 4291), unique local IPv6 (RFC 4193) or Tailscale (100.64.0.0/10, fd7a:115c:a1e0::/48). An IPv4-mapped IPv6 address counts as its IPv4 address. Checked before the Host and the PIN | `403 network_not_allowed` (socket 4403) |
| `Host` is not an address phone access listed (the Wi-Fi address, the Tailscale addresses and MagicDNS name) | `400 Invalid host header` (socket 4403) |
| No valid PIN cookie, and the route is not one of the open ones below | `401 pin_required` (socket closed with code 4401 before it opens) |

Open to a phone without the cookie: `GET /` (answered with status 401, so the page can show the PIN screen), `GET /assets/*`, `GET /favicon.svg`, `GET /api/session` and `POST /api/session`. A signed-in phone reaches everything except the Mac-only routes.

### GET /api/session

`200 {"signed_in": true, "local": <bool>}` when this browser may use the studio. `401 {"error": "pin_required"}` when it is a phone that has not entered the PIN. The page asks this first and shows the PIN screen on 401.

### POST /api/session

Body `{"pin": "123456"}`, at most 64 bytes. Answers:

- `200 {"ok": true}` and `Set-Cookie: gaffer_phone=<random token>; HttpOnly; SameSite=Strict; Path=/` (a session cookie, as the Mac window's).
- `401 wrong_pin`. `403 pin_locked` after 100 wrong PINs on one PIN (NIST SP 800-63B section 5.2.2 allows at most 100 consecutive failures); the right PIN is refused too until New PIN. `403 phone_access_off`. `400 bad_pin` for a body that is not six ASCII digits (not counted as a guess).

The PIN is six digits from a CSPRNG, kept in memory only, compared in constant time.

### GET /api/phone, POST /api/phone, POST /api/phone/pin

Mac window only: a phone, even one with the PIN, gets `403 mac_only`. A request whose `Origin` is another site is `403 wrong_origin`.

```json
{
  "enabled": true, "pin": "042917", "locked": false, "checking": false, "tailscale": true,
  "targets": [
    {"kind": "wifi", "label": "Same Wi-Fi", "url": "http://192.168.1.20:8787/", "qr": "data:image/svg+xml;..."},
    {"kind": "tailscale", "label": "Away, over Tailscale", "url": "http://studio-mac.tail1234.ts.net:8787/", "qr": "data:image/svg+xml;..."}
  ]
}
```

- `POST /api/phone` with `{"enabled": true|false}` switches phone access on or off and answers with the status. Switching on makes a new PIN and opens the network port; `503 phone_unavailable` if the port cannot be opened. Switching off closes the port, signs every phone out and closes their sockets.
- `POST /api/phone/pin` makes a new PIN, clears the wrong-guess count, signs every phone out and closes their sockets.
- When off, `pin` is `null`, `targets` is empty and `tailscale` is `null`. `tailscale` is `false` when the `tailscale` tool is missing or not running; then there is no second target.
- Nothing waits for the `tailscale` tool. Switching on answers at once with `checking: true`, `tailscale: null` and the Wi-Fi target only; the Tailscale target joins when the tool answers. Switching off, or the service stopping, ends the check and kills the tool. `GET /api/phone` also starts a new check (so opening the panel looks again), unless one is running. `GET /api/phone?wait=1` does not start one; it answers when no check is running, however long that takes.
- `GET /api/export` is Mac window only (it holds the lights' keys): a phone gets `403 mac_only`. `GET /api/health` carries no folder path.
- A phone that is signed out (New PIN, or access switched off) has its socket closed with code 4401. The page then asks `GET /api/session` again and shows the PIN screen (or "Phone access is off").
- The network listener takes IPv6 and IPv4 together (`::`, dual-stack), and falls back to IPv4 alone on a Mac with no IPv6.
- Tailscale addresses come from `tailscale status --json` (`Self.TailscaleIPs`, `Self.DNSName`), found on `PATH` or in `/Applications/Tailscale.app`.
