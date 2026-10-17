# godox-mesh-bt

The Bluetooth Mesh library underneath Lumen Studio: provisioning, keys,
encryption, segmentation and the Godox vendor protocol for every light in the
Godox mesh range.

**This is not our code at heart.** It is the library from
[`mattharrison/godox-ul60bi-bt`](https://github.com/mattharrison/godox-ul60bi-bt),
taken at version 0.2.8 of Simon Cheng's Home Assistant fork
[`binary-person/ha-godox-mesh`](https://github.com/binary-person/ha-godox-mesh),
which extended it from one light to the whole range. It is MIT licensed; see
[LICENSE](LICENSE). The first commit of this repository holds it exactly as
published, so `git log -- packages/godox-mesh-bt` shows every change made here.

Changes made for Lumen Studio:

* **Lower-transport segmentation.** Access messages longer than 11 bytes (gels,
  sixteen-bit RGB and most newer-generation effect frames) are split into
  segments as the Mesh Profile requires. Before this they went out as single
  oversized packets and the light silently dropped them.

## Use

```bash
uv run godox-mesh --help
```

The wire protocol is documented in [PROTOCOL.md](PROTOCOL.md).
