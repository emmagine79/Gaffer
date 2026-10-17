# MOLUS G200 turbo mode

Research only, 18 Oct 2026. Nothing is built yet. Captain asked for this in [FRICTION.md](../FRICTION.md) item 8.

## What it does

Zhiyun calls it **MAX Extreme** or **Max Mode**. Captain turns it on at the light by holding MODE and CCT together.

- It takes the light from 200 W to a 300 W peak ([Zhiyun product page](https://www.zhiyun-tech.com/en/product/detail/816)).
- Newsshooter measured 69,400 lx with the reflector, against 46,900 lx in normal mode. That is about 48% more. The light drew 320 W ([review](https://www.newsshooter.com/2023/07/19/zhiyun-molus-g200-200w-led-light-review/)).
- The fans get loud. Zhiyun says turbo only lasts a limited time, depending on room temperature, but gives no figure. The review ran it for over an hour at 26°C.
- Switching the light off and on returns it to normal mode.

## The Bluetooth command

The official ZY Vega app has a turbo switch. The evidence below comes from reading the decompiled app, not from code we can copy:

- The app's code has `setMaxMode` and `getMaxMode`.
- Its light config file gives `"maxMode": [0, 1]`, and only the PL109 (the G200) has that key.
- The native library has `PackMaxModeSet`.

The command id is most likely **`0x1009`**:

- `PackMaxModeSet` loads `0x1009` and writes one byte: 1 for on, 0 for off. A read uses the same command.
- The MIT repo `aaditagrawal/zhiyun-light-control` also names `0x1009` `MAX_MODE`, but has no code that sets it.
- Gaffer's `drivers/zhiyun/protocol.py` currently calls `0x1009` `QUERY_BRIGHTNESS`. That name looks wrong.

## What Gaffer would need

1. A `max_mode` flag in `models/zhiyun/PL109.json`, set only for the G200.
2. In the Zhiyun driver:
   - rename `0x1009` to `MAX_MODE`
   - an encoder for on and off
   - a read, so Gaffer can show the light's real state
3. A Turbo switch in Glass, shown only when the model has the flag. Its note says the fans get loud and that turbo ends when the light is switched off.

## How to test it safely

Do this with Captain at the light.

1. Read the turbo state first. This changes nothing.
2. With the light at about 50%, switch turbo on, then read the state back and listen for the fans.
3. Switch turbo off, then switch the light off and on.
4. If the light ignores the command, try op byte `01` and then `33`.

## Open questions

- Is the op byte `01` or `33`? Gaffer's PL109 model file says 1, but the app's PL109 config says `0x33`.
- Does the command need the extra flag the native code sets?
- What does the light send back?
