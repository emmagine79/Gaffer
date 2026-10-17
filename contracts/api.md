# Mac shell

The Swift shell (`mac/`) and the Python service (`service/`) follow this file.
Change it first, then change both sides. SPEC-016 wrote it; SPEC-010 (looks) and
SPEC-014 (cues) build the routes.

Only the routes the shell calls are listed here. The web page's own routes belong
to the card that adds them.

## Who may call

Same rules as `service/gaffer/session.py` (SPEC-001):

- The service listens on `127.0.0.1` only.
- `Host` must be `127.0.0.1` or `localhost`, any port. Anything else gets `400`.
- Every route needs the cookie `gaffer_session=<secret>`. Without it: `401`
  `{"error":"not_signed_in"}`.
- This includes the WebSocket upgrade: the cookie and Host checks run before the
  upgrade is accepted (SPEC-002 added this).
- The shell made the secret, so it sends the cookie itself. It does not need the
  one-time `/session` link for its own calls. Its web views use that link once.

## Errors

Every refusal is JSON: `{"error": "<code>", "message": "<plain words>"}`. The message
never holds a path, a stack or a raw exception.

## Routes

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

## Page

`GET /?surface=menubar|window|bare` serves the one web UI (SPEC-006). `menubar` is the panel
under the menu-bar icon. `window` is the Mac window. `bare` is a phone or browser.

## WebSocket

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
