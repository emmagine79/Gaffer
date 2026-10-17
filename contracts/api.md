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

- Each light is the object `hello` gives, with `online` (reachable or on the mesh) and `held` (true while another controller, such as the brand's own phone app, holds the light's one connection; from the light's driver `status`). The Glass footer reads `held` and `caps.brand` to say, for example, "Wand is held by the Yongnuo app". Only a driver that can tell reports it: Yongnuo does (a refused connection), the demo stand-in does on `demo.held`, and Zhiyun always reports `false` until a live check shows how a held Zhiyun light behaves. The WebSocket `stats` message carries a `held` map (light id to boolean) beside `reachable`, so the page learns of a change within a second. `state` has `power`, `brightness`, `mode` (`cct`, `hsi`, `rgbw`, `gel` or `fx`) and one object per mode. `caps.features` does not change its keys. Beside `held`, each light has `max_mode`: `true` or `false` for a model whose `caps.max_mode` is `true` (the switch exists), and `null` for every other model. The WebSocket `stats` message carries a `max_mode` map (light id to `true`, `false` or `null`) beside `held`, so a reset at power-off reaches the page within a second.
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

### Effects in Glass

Glass reads two lists and adds no route.

- Built-in effects: `caps.effects` of the selected light, from its model file. Glass shows a "Built into the light" group only when the list is not empty. Running one is `set` with `{"mode": "fx", "fx": {"symbol": ..., "speed": ..., "params": {...}}}`.
- Gaffer's own effects: lumen's registry (`hello.effects`), started with `engine.start` and stopped with `engine.stop`. They work on any light, because the engine fits each frame to what the light can show. Glass offers three: Breathe (`breathe`), Flicker (`candle`) and Colour cycle (`rainbow`, played as warmth on a light with white only). On a fixed-daylight light only those whose brightness moves are offered.
- These run from the Mac: they stop if the Mac sleeps and may stutter over Bluetooth. Glass says so beside them.

### Light fields

The light objects in `hello`, `lights` and `/api/export` gain:

- `channel`: integer or null. The radio channel a light is set to, for brands that need one told to them (Yongnuo). Saved with the light.
- `caps.driver`, `caps.brand`, `caps.match`, `caps.driver_data`.

### Adding a light

Drivers add two optional methods to the contract: `needs_channel(caps)` (true for a model whose lights must be told a radio channel when added; Yongnuo) and `check_channel(channel)` (the channel as the driver sends it, or a plain-words `ValueError`).

WebSocket commands (the page sends them; each takes `rid` and is answered by an `ack` or an `error` with the same `rid`):

- `lights.scan` listens for lights of every brand. Godox adverts are read as before; any other advert is offered to each driver's `match`, and the first model it names is listed by that model's name. A light is listed again only when its name or model changes, not on every advert. The `nearby` list (in the `ack`, the `nearby` message and `hello`) gains `driver`, `brand` and `needs_channel` (true only for a `new` light whose driver needs a channel; it turns false once the light is saved), and `relation` gains `new`: a light of a brand with nothing to pair, found by the scan and not yet saved. A `new` light that is already saved shows as `saved`.
- `lights.add {address, name?, channel?}` saves a `new` light the last scan found. It answers `{type: "ack", of: "lights.add", light: <id>}`. It is refused, and nothing is saved, when the address is not a `new` light from the last scan, or when the model's driver needs a channel and `channel` is missing or not valid for that driver (Yongnuo: a whole number from 0 to 255). A second request for an address already added is refused. A Godox light is not added this way; it pairs with `lights.pair`.
- `lights.rename {light, name}` renames a saved light. The name is trimmed and cut to 60 characters; an empty name is refused. Every client gets the new name in the next `lights` message. Glass renames a light when its name is clicked.
- `lights.identify {light}` flashes the light through its own driver (a brightness pulse, then the light is put back) and answers `{type: "ack", of: "lights.identify", light, driver}` when the pulse ends. It is long-running (the socket stays usable). The running effect on the light ends first, and the light goes back to the state the studio holds for it. A second request for a light already flashing returns at once. A driver that has not finished in 30 seconds is stopped, with an `error` that says the light did not answer.
- `light.max_mode {light?, on}` switches Max Mode (turbo) on or off for a light whose model file has `"max_mode": true` (today the Zhiyun MOLUS G200, `PL109`; it lifts the peak from 200 W to 300 W, and the fans get loud). `light` defaults to the light this client has selected; `on` must be `true` or `false`. It answers `{type: "ack", of: "light.max_mode", light, on}` once the light's driver has written it. It is long-running (the socket stays usable while a slow light answers). It is refused with an `error` in plain words when `on` is not a boolean, when the model has no Max Mode ("<name> has no Max Mode."), when the light is off ("Switch the light on first."), or when the write fails. The light ends Max Mode when it is switched off, so a power-off (or a dropped link) resets the value to `false`. The light jumps to 100% and to its model's `max_mode_kelvin` (`caps.max_mode_kelvin`; 4300 K on the G200) by itself when Max Mode comes on, and keeps both when it goes off. So Max Mode coming on sets the light's brightness to 100. Switched on from Gaffer, Gaffer then sends its own colour temperature straight back, so the light keeps the kelvin Gaffer shows; picked up from a press on the light, Gaffer shows the light's kelvin. Switching Max Mode off from Gaffer puts the brightness it had before back, and the colour temperature too when Max Mode came on at the light; a colour temperature the user sets while Max Mode is on (a `set` with `cct.kelvin`, or a scene or look that moves it) stays, even when it is the same value Max Mode showed. A group, an effect or a reading from the light does not count as the user's choice. The light never reports a press of its own buttons, so while a Max Mode light is on and linked the hub asks it every `sync_interval` seconds; Max Mode switched on at the light also sets the light's brightness to 100 and its colour temperature to the model's `max_mode_kelvin`, as the light does. The reading, on or off, is taken only when no newer setting arrived while the light was answering; otherwise the hub shows nothing, sends no "Picked up a change" toast, and asks again at the next interval. The hub does not ask a light for `SETTLE_SECONDS` after Gaffer last commanded it, for every brand. The light does not answer a brightness read, so its own knob is not picked up. Every client gets the new value in the next `lights` message.
- `demo.held {light, held}` is for `--demo` only: it makes the demo stand-in driver report the light as held (or not). Outside the demo it is refused.

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
| `GET /api/looks` | Every look in slot order. Slot 1 is the first entry. Empty list is valid. Shape and errors: "Looks (SPEC-010)" below. | SPEC-010 |
| `POST /api/looks/{id}/apply` | Applies the look. No request body. `{id}` is percent-encoded. Shape and errors: "Looks (SPEC-010)" below. | SPEC-010 |
| `POST /api/all-off` | Turns every light off. Shape: "Looks (SPEC-010)" below. | SPEC-010 |
| `POST /api/cues/active/go` | `200 {"ok":true,"look":{"id":"...","name":"..."}}` after stepping to the next look. No active cue list: `409 {"error":"no_active_cue"}`. | SPEC-014. Same route as `POST /api/cues/{id}/go` below, with the id `active`. |

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

Off until the Mac window switches it on. Once on, it stays on with the same PIN after Gaffer restarts, until it is switched off (Captain, 18 Oct 2026): the service keeps the setting, the PIN and the port in `phone.json` in its data folder, readable by the Mac user only, and takes the same port again at start so phones keep their address (any free port if it is taken on `127.0.0.1` or on all network addresses, `0.0.0.0` and `::`). Quitting only closes the listener and signs phones out. If phone access cannot be switched back on at start, Gaffer starts with phone access off and the status carries a `restore_failed` notice (see `notice` below). A change that cannot be saved never lets the older setting come back at the next start: switching off, New PIN or switching on removes `phone.json`, or when the folder cannot be written overwrites it in place with an "off" setting. Whenever a save fails, the status carries a `not_saved` notice. While it is on, the service also listens on all network addresses at the same port, and a phone gets in with a PIN. Two kinds of caller: the **Mac window** (peer address is loopback, `Host` is `127.0.0.1` or `localhost`, and the request carries no forwarding header; needs the launch secret cookie, no PIN) and a **phone** (a connection from a private network or Tailscale; needs the PIN cookie).

What is guaranteed:

* A loopback connection is the Mac window only, and it still needs the launch secret cookie. It is never a phone: a loopback connection with another `Host`, or with an `X-Forwarded-*`, `Forwarded` or `Tailscale-*` header, is refused.
* The service takes the peer address from the TCP connection only, never from `X-Forwarded-For`.
* A proxy on the Mac that sends no forwarding header we list (for example `X-Real-IP`, `X-Client-IP` or `Cf-Connecting-Ip`) and rewrites `Host` to `127.0.0.1` is handled as a Mac window request without the cookie, so it is refused with `401 not_signed_in`. The launch secret cookie is the safety net here, not the header check.
* `tailscale serve` and Funnel are not a supported way in; neither is `ssh -L` or a dev proxy. A phone uses the Wi-Fi or Tailscale address shown in the Mac window's phone access panel.
* The supported Tailscale setup is Tailscale.app (the network extension), which delivers a tailnet peer's connection with its own `100.x` or `fd7a:` address. Userspace-networking `tailscaled`, which delivers tailnet connections from loopback, is not supported: its phone gets `403 network_not_allowed`.

A phone's request is refused when:

| Case | Answer |
| --- | --- |
| Phone access is off | `403 phone_access_off` (socket closed with code 4403) |
| A loopback connection carries an `X-Forwarded-*`, `Forwarded` or `Tailscale-*` header, whatever its `Host` and cookie | `403 network_not_allowed` (socket 4403) |
| The connection does not come from a private IPv4 (RFC 1918), link-local (RFC 3927, RFC 4291), unique local IPv6 (RFC 4193) or Tailscale (100.64.0.0/10, fd7a:115c:a1e0::/48) address. That includes a public address and, since SPEC-024, loopback with a `Host` other than `127.0.0.1` or `localhost` (while phone access is off, that case is `400 Invalid host header`, as before). An IPv4-mapped IPv6 address counts as its IPv4 address. Checked before the Host and the PIN | `403 network_not_allowed` (socket 4403) |
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
  "enabled": true, "pin": "042917", "locked": false, "checking": false, "tailscale": true, "notice": null,
  "targets": [
    {"kind": "wifi", "label": "Same Wi-Fi", "url": "http://192.168.1.20:8787/", "qr": "data:image/svg+xml;..."},
    {"kind": "tailscale", "label": "Away, over Tailscale", "url": "http://studio-mac.tail1234.ts.net:8787/", "qr": "data:image/svg+xml;..."}
  ]
}
```

- `POST /api/phone` with `{"enabled": true|false}` switches phone access on or off and answers with the status. Switching on makes a new PIN and opens the network port; `503 phone_unavailable` if the port cannot be opened. Switching off closes the port, signs every phone out and closes their sockets.
- `POST /api/phone/pin` makes a new PIN, clears the wrong-guess count, signs every phone out and closes their sockets.
- `notice` is `null`, or `{"code": "restore_failed" | "not_saved", "message": "<plain words>"}`, for the Mac window to show. `restore_failed`: phone access was on when Gaffer last closed and could not be switched back on at start (it is off now; the message says to turn it on again). `not_saved`: the last switch on, switch off or New PIN could not be saved. The old file is removed or overwritten so an older setting does not come back, and the message says what a restart will do: for a switch on, that it will not last through a restart; for a switch off or New PIN, that phone access will be off after a restart. If the old file could not be cleared either, the message says phone access and the old PIN may come back after a restart. The next switch on, switch off or New PIN clears it. It never carries a path.
- When off, `pin` is `null`, `targets` is empty and `tailscale` is `null`. `tailscale` is `false` when the `tailscale` tool is missing or not running; then there is no second target.
- Nothing waits for the `tailscale` tool. Switching on answers at once with `checking: true`, `tailscale: null` and the Wi-Fi target only; the Tailscale target joins when the tool answers. Switching off, or the service stopping, ends the check and kills the tool. `GET /api/phone` also starts a new check (so opening the panel looks again), ending one that is still running. The last good Tailscale answer, and its names in the allowed Host set, stay in use when a check fails, hangs or is replaced, and also across switching access off and on. Only an answer from the tool that Tailscale is not running (or no tool at all) replaces it. `GET /api/phone?wait=1` does not start one; it answers when no check is running, however long that takes.
- `GET /api/export` is Mac window only (it holds the lights' keys): a phone gets `403 mac_only`. `GET /api/health` carries no folder path.
- A phone that is signed out (New PIN, or access switched off) has its socket closed with code 4401. The page then asks `GET /api/session` again and shows the PIN screen (or "Phone access is off").
- The network listener takes IPv6 and IPv4 together (`::`, dual-stack), and falls back to IPv4 alone on a Mac with no IPv6.
- Tailscale addresses come from `tailscale status --json` (`Self.TailscaleIPs`, `Self.DNSName`), found on `PATH` or in `/Applications/Tailscale.app`.

## Looks (SPEC-010)

A look is `{"id", "name", "fade_seconds", "lights": {"<light id>": <state patch>}}`. It is saved in the `looks` collection, so it is also in `hello.store.looks` and in `store` messages. The order of the list is the slot order: slot 1 is the first look, and keys 1 to 9 and the Mac shortcuts use it. `lights` holds one state patch per light, in the same shape `set` takes, so a look made on one model is fitted to the light it is applied to.

Applying a look runs every light in it. A fade of `0` sets each light at once. Any other fade starts a transition of that many seconds on each light, ending on the look's values. The service works out every light's values first and starts the lights only after that, so a look is never half applied. A light the look names that is no longer saved, is not on the network the service is connected to, or cannot take its patch is left alone and named in `skipped`; the others still move.

| Method and path | Answer |
| --- | --- |
| `GET /api/looks` | `200 {"looks":[{"id","name","fade_seconds","lights"}, ...]}` in slot order. |
| `POST /api/looks` | Body `{"name", "fade_seconds"?, "lights"?, "id"?, "capture"?}`. `200 {"ok":true,"look":{...}}`. A new look with no `lights` saves what every light is doing now. An `id` that exists replaces that look; leaving out `lights` then keeps its lights, and `"capture": true` replaces them with what the lights do now. Without an `id` one is made from the name. Refused with `400 {"error":"look_not_valid"}` (no name, a name over 80 characters or with control characters, a fade outside 0 to 60 seconds, an id with other characters than `A-Z a-z 0-9 _ -`, a light that is not saved, a patch the light cannot take) or `400 {"error":"body_not_json"}`. A refused save changes nothing. |
| `POST /api/looks/{id}/apply` | `200 {"ok":true,"look":{"id","name"},"skipped":[<light ids>]}`. Unknown id: `404 {"error":"look_not_found"}`. None of its lights could move (saved, on the network and able to take their patch): `409 {"error":"look_has_no_lights"}`. |
| `POST /api/all-off` | `200 {"ok":true,"skipped":[<light ids>]}`. Every light off at once. `skipped` names the lights that are not on the network: they are left as they were. No look is current afterwards, unless a skipped light is on: then the current look stays, because not every light is off. |

The Mac shell calls the first, third and fourth (`ServiceClient.swift`, SPEC-016). It reads `id` and `name` of each look and sends the id percent-encoded as one path segment.

WebSocket messages from the page:

- `{"type":"looks.apply","id"}`: apply. Answers `{"type":"ack","of":"looks.apply","id","name","skipped"}`.
- `{"type":"looks.save","look":{...}}`: the same body as `POST /api/looks`. Answers `{"type":"ack","of":"looks.save","look":{...}}`.
- `{"type":"looks.delete","id"}`: delete. Deleting the current look makes no look current.
- `{"type":"all.off"}`: all off.
- `store.upsert`, `store.delete` refuse the `looks` collection; use the messages above.

WebSocket messages to every client:

- `{"type":"look","id","name"}`: the current look. `id` and `name` are `null` when no look is on (the start, after All off, after the current look is deleted). It is sent once as the socket opens, straight after `hello`, and again each time the current look changes, including when it is renamed. The Mac shell ignores `hello` and reads this message.
- `hello` carries `look` (the name or `null`) and `look_id`.
- `{"type":"store","collection":"looks","items":[...]}` after every save or delete.

The current look is the one last applied. It is held in memory: after a restart no look is current until one is applied.

`GET /?surface=menubar|window|bare` is the page for each surface. The service serves the same page for all three; the page reads `surface` itself (`web/src/app/surface.ts`). Only `window` shows the look editor.

Every HTTP request that is not a GET, HEAD or OPTIONS is refused with `403 {"error":"origin_not_allowed"}` when it carries an `Origin` header that is not the service's own origin (same check as `/ws`), because `SameSite` does not separate localhost ports. A request with no `Origin` (the Mac shell) is allowed. `POST /api/looks` also needs `Content-Type: application/json` (`415 json_required` otherwise).

## Cues (SPEC-014)

A cue is `{"id", "name", "steps": [{"look_id", "fade_seconds"}]}`, saved in the `cues` collection (also in `hello.store.cues` and `store` messages). A step applies its look through `looks.apply`; a step's `fade_seconds` replaces the look's own fade, and `null` keeps the look's. A cue has at least one step, a name of up to 80 characters, each step fade from 0 to 60 seconds, and each step names a saved look. The number of steps is not capped by Gaffer; a save is one WebSocket message, which uvicorn's `ws_max_size` (16 MiB by default) already bounds. Cue ids follow the look id rule (letters, digits, `-` and `_`, at most 80 characters, not `__proto__`, `constructor` or `prototype`), and a cue cannot be called `active`. An id made from a name is checked by the same code as a look's and never takes the id of an entry in `cues.json` that cannot be read. At Go, a step whose look was deleted, or whose lights are all no longer saved, is passed over. If the look's lights are saved but none can be reached on the network, Go fails with `409 {"error":"lights_unreachable"}` and the cue stays where it was.

The service holds one active cue and how many of its steps have run (`step`: 0 is the top, `steps` is the end). It is in memory: after a restart no cue is active. A Go that fails changes nothing: it does not move the position, and `POST /api/cues/{id}/go` with another cue's id makes that cue active only after its first step has run. Saving the active cue keeps `step` when the steps that have run (the first `step` steps, compared by look and fade) are unchanged, so renaming it or editing the steps still to come does not move it. If any step that has run was changed, removed or has another step put in front of it, the cue goes back to the top (`step` 0) and the next Go runs its first step. Start makes a cue active at the top and applies nothing. Go applies the next step. Go never waits, so two Go presses at once run two steps, never the same one twice.

| Method and path | Answer |
| --- | --- |
| `POST /api/cues/{id}/go` | Runs the next step. `200 {"ok":true,"look":{"id","name"},"skipped":[<light ids>],"cue":{"id","name","step","steps","next"}}`. An id other than the active cue starts that cue first, then runs its first step. The id `active` is the running cue (the Mac shell's Next cue shortcut). No cue running: `409 {"error":"no_active_cue"}`. Last step already run: `409 {"error":"cue_finished"}` and nothing changes. Unknown id: `404 {"error":"cue_not_found"}`. No look in the cue can be applied: `409 {"error":"cue_steps_gone"}`. Lights of the next look not reachable: `409 {"error":"lights_unreachable"}`. |

WebSocket messages from the page:

- `{"type":"cue.start","id"}`: make the cue active at the top. Answers `{"type":"ack","of":"cue.start","cue":{...}}`.
- `{"type":"cue.go"}`: the same as the route with `active`. Answers `{"type":"ack","of":"cue.go","look","skipped","cue"}`.
- `{"type":"cue.back"}`: apply the step before the one that ran last. At the first runnable step (every earlier step is gone, or there is none): an `error` message, "Already at the first step."
- `{"type":"cue.skip"}`: move past the next runnable step without applying it, for a step whose lights are out of reach. Answers `{"type":"ack","of":"cue.skip","cue":{...}}`. At the end: `cue_finished`. Go and Space never skip by themselves: they retry the step and fail again while its lights are out of reach, and only Skip (the button the bar shows with `blocked`) moves past it. The message names the lights.
- `{"type":"cues.save","cue":{...}}` and `{"type":"cues.delete","id"}`: save (the `id` may be left out for a new cue, and cannot be `active`) and delete. Deleting the active cue makes no cue active. `store.upsert` and `store.delete` refuse the `cues` collection.

WebSocket message to every client: `{"type":"cue","id","name","step","steps","next","blocked"}`. `next` is `{"id","name"}` of the look the next Go will run (steps whose look is gone are already passed over), or `null` at the end of the cue or when no remaining step can run. `blocked` is the sentence the last Go failed with when the lights of the next look were out of reach (`lights_unreachable`), or `null`; the next successful Go, Back, Skip, Start or save clears it. All six are `null` when no cue is active. It is sent again when a look is saved or deleted, or a light is added or removed, while a cue is active, so `next` stays right. It is sent once as the socket opens, straight after the `look` message, and again each time the cue, its step or its saved steps change.

The page shows Go and Back under Glass and under the desk while a cue is active. When `next` is `null` (the end, or no remaining step can run) it shows "Start again" instead of Go. The Go button names `next`. The Space key does Go only when `next` is not `null`, the surface is `window` (the menu-bar panel and the phone have no Space shortcut), no sheet or command palette is open, no control (button, field, fader, switch, link) has keyboard focus, and the last pointer press was not on a control. The last rule is needed because a drag or tap on a fader or switch hands focus back to the page: Space stays off after a press on a control until the next pointer press that lands outside every control, or on the cue bar. There is no time window. Only the `window` surface shows the cue editor. The non-GET Origin check (above) covers the Go route.

## Schedules (SPEC-013)

A schedule is `{"id", "name", "enabled", "at": "HH:MM", "days": [0-6], "action": "look" | "off", "target"}`. It is saved in the `schedules` collection, so it is also in `hello.store.schedules` and in `store` messages. `at` is 24-hour local time on the Mac. `days` counts from Monday = 0 and holds at least one day. `target` is a look id and is needed for `look` only. When the minute comes on one of its days the service applies the look (as `looks.apply`) or turns every light off (as `all.off`), once. Schedules run only while Gaffer is open and the Mac is awake. A schedule whose look has been deleted does nothing.

WebSocket messages from the page:

- `{"type":"schedules.save","schedule":{...}}`: add one, or replace the one with the same `id`. Answers `{"type":"ack","of":"schedules.save","schedule":{...}}`. Refused with `{"type":"error","text":...}` and nothing stored: no name, a name over 80 characters or with control characters, a time that is not `HH:MM`, no days or a day outside 0 to 6, an action other than `look` or `off`, a `look` with no target or a look that does not exist.
- `{"type":"schedules.delete","id"}`: delete.
- `store.upsert`, `store.delete` refuse the `schedules` collection; use the messages above.
- `{"type":"store","collection":"schedules","items":[...]}` goes to every client after a save or delete.

Only the `window` surface shows the schedule editor.
