# Live check (SPEC-019)

This sheet is for Captain, at the live check with his three lights. It settles SPEC AC10: each light turns on, dims and changes colour temperature from the menu bar, the Mac window and the phone.

Work top to bottom. Write what you see in the notes column. Mark a cell Pass only if the light really did it.

## Before you start

1. Add the Porkbun A record `gaffer` pointing to `159.89.203.137` (SPEC-018 is blocked on this). Then the conductor runs `scripts/deploy_site.sh`.
2. Have the three lights charged or plugged in, in reach of the Mac, and switched on at the light:
   - a Godox light (the Litemons LA150Bi, or another Godox)
   - the Zhiyun MOLUS G200
   - the Yongnuo YN150LI
3. Have your phone ready, on the same Wi-Fi as the Mac, with Tailscale installed on both the Mac and the phone.
4. Have the release zip ready. The conductor builds it with `scripts/build_app.sh`. It gives `dist/Gaffer-<version>-macos-arm64.zip` and a `.sha256` file.
5. Close any official light app (Godox, Zhiyun, Yongnuo) on your phone. A light held by its own app can refuse Gaffer.
6. Do not rebuild Gaffer during the check. A rebuild with a different signature makes macOS ask for Bluetooth again.

## Install

This is SPEC AC9. Use a fresh standard user account on the Mac, because Bluetooth permission is per user.

1. Follow "Install Gaffer" in the README, from the zip.
2. Take every shot in the shot list in `docs/install/README.md`. Replace each grey placeholder with the real PNG and keep its name. The list has 11 shots, `01-release-page.png` to `11-control-click-open.png`.
3. Write down exactly what each macOS dialog says. If the README wording is different, fix the README to match.
4. Keep `09-bluetooth-prompt.png` (the "Gaffer would like to use Bluetooth" prompt). AC10 needs it.

| Install check | Pass / Fail | Notes |
| --- | --- | --- |
| Gatekeeper dialog wording matches the README | | |
| Open Anyway, then Open, opens Gaffer | | |
| Menu-bar studio-light icon shows and the window opens | | |
| Bluetooth prompt names Gaffer | | |
| Control-click Open on macOS 26: works, or only Cancel (shot 11) | | |
| Quit Gaffer leaves no Python process (`pgrep -f gaffer`) | | |

## Add each light

Open the Mac window and use Add a light. Pick the light by its model name, tap it, and check that it pulses, then name it.

### Godox

1. Import the keys from the Godox app (SPEC-009), or pair the light if it is factory reset.
2. Record which way you used: import or pairing.
3. Record the model Gaffer picked. If it picked the wrong model, note it (SPEC-022 adds a picker).

### Zhiyun MOLUS G200

1. Add it. Check the model name shows as the G200 (model file `service/gaffer/models/zhiyun/PL109.json`).
2. Try on, dim and colour temperature.
3. If the G200 ignores the commands, the op byte is wrong. In `PL109.json` change `driver_data.control_mode` from `1` (op 0x01) to `51` (op 0x33), restart Gaffer and try again.
4. Record the final op byte in the table below. Commit the model file change.

### Yongnuo YN150LI

1. Add it and set its channel. Record the channel you set.
2. Try on, dim and colour temperature.
3. If the light does nothing, it may not take plain frames. In `service/gaffer/models/yongnuo/YN150.json` change `frame_variant` from `plain` to `decimal`, restart and try again.
4. If colour temperature is wrong or reversed on plain frames, the Kelvin byte order is the guess in the model file note. Record what you saw.
5. If the light ignores the channel, try another channel and record the one that works.

### What to record

| Item | Value | Committed in |
| --- | --- | --- |
| Godox: import or pairing | | light record |
| Zhiyun G200 final op byte (0x01 or 0x33) | | `models/zhiyun/PL109.json` |
| Yongnuo frame variant (plain or decimal) | | `models/yongnuo/YN150.json` |
| Yongnuo channel | | light record |
| Yongnuo Kelvin byte order (plain frame) | | `models/yongnuo/YN150.json` |

## AC10 table

3 lights, 3 surfaces, 3 actions. Test the phone twice: first on Wi-Fi with the PIN, then on Tailscale (switch Wi-Fi off on the phone, or use mobile data).

Phone set-up: in the Mac window, open Phone access and switch it on. Scan the Same Wi-Fi code with the phone and enter the PIN. For Tailscale, scan the Tailscale code.

If the Tailscale phone gets network_not_allowed, check whether Tailscale runs in userspace mode (SPEC-024).

Actions: **On** is turn the light on. **Dim** is move brightness down and see the light get dimmer. **CCT** is change colour temperature and see the colour change.

Surfaces: **Menu bar** is the studio-light icon. **Mac window** is the main window. **Phone, Wi-Fi** is the phone on the same Wi-Fi with the PIN. **Phone, Tailscale** is the phone away from the Wi-Fi.

Every cell must say Pass. Fill the Pass/Fail column and add notes.

### Godox

| Surface | Action | Pass / Fail | Notes |
| --- | --- | --- | --- |
| Menu bar | On | | |
| Menu bar | Dim | | |
| Menu bar | CCT | | |
| Mac window | On | | |
| Mac window | Dim | | |
| Mac window | CCT | | |
| Phone, Wi-Fi with PIN | On | | |
| Phone, Wi-Fi with PIN | Dim | | |
| Phone, Wi-Fi with PIN | CCT | | |
| Phone, Tailscale | On | | |
| Phone, Tailscale | Dim | | |
| Phone, Tailscale | CCT | | |

### Zhiyun MOLUS G200

| Surface | Action | Pass / Fail | Notes |
| --- | --- | --- | --- |
| Menu bar | On | | |
| Menu bar | Dim | | |
| Menu bar | CCT | | |
| Mac window | On | | |
| Mac window | Dim | | |
| Mac window | CCT | | |
| Phone, Wi-Fi with PIN | On | | |
| Phone, Wi-Fi with PIN | Dim | | |
| Phone, Wi-Fi with PIN | CCT | | |
| Phone, Tailscale | On | | |
| Phone, Tailscale | Dim | | |
| Phone, Tailscale | CCT | | |

### Yongnuo YN150LI

| Surface | Action | Pass / Fail | Notes |
| --- | --- | --- | --- |
| Menu bar | On | | |
| Menu bar | Dim | | |
| Menu bar | CCT | | |
| Mac window | On | | |
| Mac window | Dim | | |
| Mac window | CCT | | |
| Phone, Wi-Fi with PIN | On | | |
| Phone, Wi-Fi with PIN | Dim | | |
| Phone, Wi-Fi with PIN | CCT | | |
| Phone, Tailscale | On | | |
| Phone, Tailscale | Dim | | |
| Phone, Tailscale | CCT | | |

## Open items to judge on real hardware

Each item came from a review that ran out of rounds. Judge it, write the answer in the notes, and say fix or accept.

| Item | Card | Judgement (fix / accept) | Notes |
| --- | --- | --- | --- |
| Identify on a Zhiyun light Gaffer has not set restores it to on, 50% and the default colour temperature, because there is no readback. Is that acceptable, or should a readback replace it? | SPEC-004 | | |
| The Zhiyun driver always reports held = false, so the footer never says the Zhiyun app holds the key. Close the Zhiyun app, then open it, and see if Gaffer behaves differently. | SPEC-008 | | |
| Ctrl-Option-0 (all off) on the Mac does not warn when a light stays on. Switch one light off at its own power or move it out of range, press Ctrl-Option-0 and see whether you are told. | SPEC-010 | | |
| Groups, behaviour 1: a light that joins a group while it is the on-screen light pushes its own state onto the existing members, which move. | SPEC-011 | | |
| Groups, behaviour 2: adding a shared property (or a light) copies every shared property from the leader. A member that was out of step on brightness jumps when you add colour. | SPEC-011 | | |
| Groups, behaviour 3: a group save that fails leaves the screen showing a group the service never saved, and a quick third click can drop an earlier change. | SPEC-011 | | |
| PIN lockout: any device on the network can lock phones out with 100 wrong PINs. New PIN fixes it but signs out phones that are signed in. Is that fine at home? | SPEC-015 | | |
| The Same Wi-Fi code comes from a route probe. With a full-tunnel VPN or exit node on the Mac, it can show the VPN address. Test with a VPN on. | SPEC-015 | | |
| A Tailscale check that hangs on the first switch-on keeps the Tailscale names out of the allowed set until the Mac panel is opened again. Switch Phone access on with Tailscale just started or stopped, and see. | SPEC-015 | | |
| Bluetooth permission survives a rebuild. Rebuild with `scripts/build_app.sh`, open the new app, and see whether macOS asks again. | SPEC-017 | | |
| The Gatekeeper dialog wording matches the README (see the install table above). | SPEC-017 | | |
| Tab from the bare page flips the view and does not enter the controls; Shift+Tab is the way in. Keep it, or should Tab move focus and another key flip the view? | SPEC-007 | | |

## If something fails

A failure does not stay as a note. In the same session it becomes either:

- a regression test that reproduces it the way you hit it and fails without the fix, or
- a model-file change (op byte, frame variant, channel or Kelvin order), committed with the result.

Then run the failed cell again and mark it Pass. SPEC-019 closes only when every cell in the AC10 table says Pass and the Bluetooth prompt screenshot is in `docs/install/`.

## Clean up

- Quit Gaffer from the menu-bar icon.
- Switch the lights off.
- Check nothing is left running: `pgrep -f gaffer` prints nothing.
