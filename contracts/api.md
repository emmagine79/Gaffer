# Gaffer API contract

The HTTP and WebSocket contract between the Gaffer service and its clients (the web UI, the Mac shell).

## Service

Everything in this section is served by the Python service in `service/`. It listens on `127.0.0.1` only. Every route and `/ws` need the session cookie. Errors are `{"error": "<code>", "message": "<plain words>"}` and never carry a path.

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

- Each light is the object `hello` gives, with `online` (reachable or on the mesh) and `held` (true while another controller, such as the brand's own phone app, holds the light's one connection; from the light's driver `status`). The Glass footer reads `held` and `caps.brand` to say "Key is held by the Zhiyun app". The WebSocket `stats` message carries a `held` map (light id to boolean) beside `reachable`, so the page learns of a change within a second. `state` has `power`, `brightness`, `mode` (`cct`, `hsi`, `rgbw`, `gel` or `fx`) and one object per mode. `caps.features` does not change its keys.
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

### Adding a light

Drivers add two optional methods to the contract: `needs_channel(caps)` (true for a model whose lights must be told a radio channel when added; Yongnuo) and `check_channel(channel)` (the channel as the driver sends it, or a plain-words `ValueError`).

WebSocket commands (the page sends them; each takes `rid` and is answered by an `ack` or an `error` with the same `rid`):

- `lights.scan` listens for lights of every brand. Godox adverts are read as before; any other advert is offered to each driver's `match`, and the first model it names is listed by that model's name. The `nearby` list (in the `ack`, the `nearby` message and `hello`) gains `driver`, `brand` and `needs_channel` (true only for a `new` light whose driver needs a channel), and `relation` gains `new`: a light of a brand with nothing to pair, found by the scan and not yet saved. A `new` light that is already saved shows as `saved`.
- `lights.add {address, name?, channel?}` saves a `new` light the last scan found. It answers `{type: "ack", of: "lights.add", light: <id>}`. It is refused, and nothing is saved, when the address is not a `new` light from the last scan, or when the model's driver needs a channel and `channel` is missing or not valid for that driver (Yongnuo: a whole number from 0 to 255). A second request for an address already added is refused. A Godox light is not added this way; it pairs with `lights.pair`.
- `lights.identify {light}` flashes the light through its own driver (a brightness pulse, then the light is put back) and answers `{type: "ack", of: "lights.identify", light, driver}` when the pulse ends. It is long-running (the socket stays usable). A second request for a light already flashing returns at once. A driver that has not finished in 30 seconds is stopped, with an `error` that says the light did not answer.
- `demo.held {light, held}` is for `--demo` only: it makes the demo stand-in driver report the light as held (or not). Outside the demo it is refused.
