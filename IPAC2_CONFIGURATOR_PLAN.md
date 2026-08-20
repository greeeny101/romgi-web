# Linux configurator for the Ultimarc I-PAC 2

## Context

The arcade cabinet's PC moved from Windows to Batocera Linux. The I-PAC 2 keyboard
encoder is still carrying its Windows-era configuration, and Ultimarc's own
configurator (WinIPAC v2) is Windows-only. Batocera ships no Ultimarc tooling at all,
and its root filesystem is read-only, so anything needing `pip install` is painful
there.

The goal: a self-contained configurator that runs **on the Batocera box**, talks to the
board over USB, and reprograms it — specifically into **game controller mode**, so
Batocera sees two real joysticks instead of one keyboard. The board stores its config in
flash, so this is a one-time write that survives reboots and OS reinstalls.

### Board confirmed — and it needs a firmware upgrade for gamepad mode

`lsusb` on the cabinet reports `ID d209:0420 Ultimarc Ultimarc IPAC 2`, `bcdDevice 0.44`,
`bNumInterfaces 3` (interfaces 0, 1, 2). Reading that off:

- **2015+ hardware.** Gamepad mode is possible on this board, and firmware upgrades are
  safe (the bricking warning applies only to pre-2015 `d208:0310` boards).
- **Firmware 1.44 = "Keyboard WITHOUT Gamepad (Single Mode)".** There is no gamepad
  device in this firmware, so **the `Start1+P1SW2` mode hotkey will not work** and
  `GAMEPAD n` codes are meaningless until the firmware is upgraded. Confirmed by the
  descriptor itself: three interfaces (keyboard, mouse, config) and no game controller.
- **Config interface is 2**, matching the `bcdDevice` rule (`0x44` falls in
  `[0x40, 0x56)`), and interface 3 does not exist on this board. Multi-mode firmware is
  `0x50`–`0x55`, still inside that range, so the interface stays 2 after an upgrade.

**Decision required before build order step 4.** Two routes to a working Batocera setup:

| | Route A: upgrade firmware | Route B: leave firmware alone |
|---|---|---|
| Gamepad support | Real dual gamepads from the board | Virtual pads via Batocera `keyboardToPads` (v41+) or `xarcade2jstick` (v40−) |
| Needs Windows | Yes, once | No |
| Risk | Low on 2015+ hardware, but it is a flash | None |

Either way this configurator is worth building: on 1.44 it already does key remapping,
shift/alternate actions and macros over the 256-byte protocol described below, and
Route B needs sane keycodes on the board anyway.

**If taking Route A**, the host is an **Ubuntu 24.04 x86_64 box** with the board plugged
into it (the cabinet's Windows install is gone, and the Mac is Apple Silicon — no x86
virtualization there):

- **Windows**: Windows 11 Enterprise 90-day evaluation, free and no product key, from the
  [Microsoft Evaluation Center](https://www.microsoft.com/en-us/evalcenter/evaluate-windows-11-enterprise).
  Take the **x64 ISO** — the host is x86, so WinIPAC runs natively with no emulation
  anywhere in the chain.
- **Hypervisor**: QEMU/KVM with virt-manager, all from apt:
  `sudo apt install qemu-kvm libvirt-daemon-system virt-manager ovmf swtpm`.
  Windows 11 setup demands TPM 2.0 and Secure Boot, so give the VM **UEFI/OVMF firmware**
  and add a **TPM 2.0 (swtpm) device** when creating it — otherwise setup refuses to
  install.
- Pass the board through with *Add Hardware → USB Host Device*, selecting
  `d209:0420 Ultimarc`.

**The one snag to expect**: entering upgrade mode makes the board re-enumerate under
different USB IDs, and libvirt's passthrough is bound to the old ones — the flasher then
reports "board not detected". Fix: when it disappears, add the newly-appeared bootloader
device as a second USB Host Device in virt-manager. To avoid the dance altogether, pass
the physical *port* rather than the device via QEMU args in the domain XML
(`-device usb-host,hostbus=N,hostport=M`), which follows the port across re-enumeration.

If a flash is interrupted, the bootloader is not itself overwritten, so the board should
remain in bootloader mode for a retry rather than bricking.

### Capture the flash with Wireshark

The flash happens exactly once, and it is the only chance to record the two things that
block a native Linux flasher: **the command that puts the board into bootloader mode**,
and **the wire framing of the `.ufw` records**. Neither is published anywhere. Capture is
passive and cannot disturb the flash.

usbmon works even though the board is passed through to the VM — QEMU's `usb-host` goes
through usbfs on the host, so the kernel still sees every URB.

**Prepare** (on the Ubuntu host, before starting the VM):

```sh
sudo apt install wireshark tshark          # say YES to "allow non-superusers to capture"
sudo usermod -aG wireshark $USER           # then log out and back in
sudo modprobe usbmon
lsusb | grep d209                          # note bus + device, e.g. Bus 001 Device 005
lsusb -v -d d209:0420 > ipac-before.txt    # descriptors in normal mode
```

**Capture** — start this *before* clicking Firmware Upgrade, because the enter-bootloader
command is the part that matters most:

```sh
sudo tshark -i usbmon0 -w ipac-flash.pcapng     # usbmon0 = all buses
```

Use `usbmon0` rather than `usbmon1`: the board re-enumerates mid-flash and changes device
address, and an all-bus capture keeps both identities in one file. In a second terminal,
watch for the bootloader appearing and record what it claims to be — this is the single
most valuable line of the whole exercise:

```sh
udevadm monitor --udev &
lsusb                                      # once it re-enumerates, note the new VID:PID
lsusb -v -d <newvid>:<newpid> > ipac-bootloader.txt
```

Run the flash, wait for the board to come back in normal mode, then stop tshark with
Ctrl-C.

**Analyse afterwards.** `IPAC2_155c.ufw` decodes (it is ASCII hex, two chars per byte)
into 171 records:

| Record | Bytes |
|---|---|
| Start | `ff 38 00 01 02 03 04 05 06 07` |
| Data ×169 | `ff 39` + `00 01 02 03 04 05 06 07` + `00` + block index + 66 payload bytes = 78 bytes |
| End | `ff 3b 00 01 02 03 04 05 06 07` |

Block index runs `0x4f`…`0xf6` consecutively, then `0xff` for the last record. The first
data record starts `ff 39 00 01 02 03 04 05 06 07 00 4f 26 02 fe 7f`. Those byte strings
are the anchors — search the capture for them:

```sh
# every HID SET_REPORT, which is how the enter-bootloader command will be sent
tshark -r ipac-flash.pcapng -Y 'usb.transfer_type==2 && usb.setup.bRequest==0x09' \
  -T fields -e frame.number -e usb.device_address -e usb.setup.wValue \
  -e usb.setup.wIndex -e usb.capdata

# the firmware records themselves
tshark -r ipac-flash.pcapng -Y 'usb.capdata contains ff:39:00:01:02:03:04:05:06:07' \
  -T fields -e frame.number -e usb.capdata | head
```

What to extract:

1. **The enter-bootloader command** — the last SET_REPORT sent to `d209:0420` before it
   disconnects. Its header byte will be neither `0x50` (write config) nor `0x59` (read
   config); whatever it is, that is the missing command.
2. **The bootloader's identity** — if it enumerates as `04d8:003c` it is a stock Microchip
   HID bootloader and existing tooling (`mphidflash`) may flash it directly on Linux.
   If it keeps Ultimarc's VID it is a custom bootloader and the capture is the only spec.
3. **Framing** — whether each 78-byte record goes out whole or is split across 64-byte
   HID reports, and what the device sends back between records (ACK? status?).

Keep `ipac-flash.pcapng`, `ipac-before.txt` and `ipac-bootloader.txt` in the project's
`fixtures/` directory. With those three files a Linux flasher becomes a weekend project
instead of an impossibility — worth having even if it is never written, since it means
the next firmware upgrade need not involve Windows at all.

Steps, once Windows can see the board:

1. In WinIPAC v2, **enable the shift function first** (default: Start1 as shift).
   Mode switching after the upgrade does not work without it.
2. Flash **`IPAC2_155c.ufw`** from
   [`ipac_multimode.zip`](https://www.ultimarc.com/ipac_multimode.zip) — the production
   multi-mode release (the 1.57 in `firmware_157.zip` is beta). Firmware upgrade is
   `File → Firmware Upgrade`; the flasher only sees the board once WinIPAC has put it
   into upgrade mode.
3. If it comes up in Xinput mode afterwards, hold **P1SW1 while plugging in USB** to
   force it back to keyboard mode.
4. Then `Start1+P1SW2` for 10 seconds switches to Dinput — and dumping the config before
   and after that switch gives build order step 1 its reference data.

## Protocol (researched, verified against two independent implementations)

Sources: [Ultimarc-linux](https://github.com/katie-snow/Ultimarc-linux) (C) and
[QtPyUltimarc](https://github.com/katie-snow/QtPyUltimarc) (Python).

| Item | Value |
|---|---|
| USB IDs | 2015+: `d209:0420`. Pre-2015: `d208:0310` (different protocol — detect and refuse) |
| Config interface | `bcdDevice` in `[0x40, 0x56)` → interface **2**; otherwise → interface **3** |
| Transport | HID class SET_REPORT: `bmRequestType 0x21`, `bRequest 0x09`, `wValue 0x0203` (Feature, report ID 3), `wIndex` = interface |
| Message | 5 bytes: `[0x03, b0, b1, b2, b3]` — the config is sent as 4-byte chunks |
| Config size | 256 bytes: 4-byte header + 252 data bytes |
| Write header | `0x50, 0xdd, 0x0f, cfg` where `cfg` bits: paclink = bit 2, debounce = bits 3–4 |
| Read | send header `0x59, 0xdd, 0x0f, 0x00`, then read the interrupt IN endpoint (`0x84`) |
| Key codes | Standard USB HID usage IDs (`A` = `0x04`, `ENTER` = `0x28`, `LEFT` = `0x50`) |
| Game codes | `GAMEPAD 1..32` = `0x90–0xAF`, `ANALOG 0..7` = `0xB0–0xB7`, `HAT 0..3` = `0xBA–0xBD`, mouse = `0x80–0x83` |
| Pin table | 32 pins, each with `(action_index, alt_action_index, shift_index)` into the 252-byte array — full table in [`ipac2.py`](https://github.com/katie-snow/QtPyUltimarc/blob/main/ultimarc/devices/ipac2.py) `PinMapping`; shift-key marker is `0x41` at `shift_index` |

**The one genuine unknown**: the exact bytes WinIPAC writes to select *game controller
mode* globally, and how joystick directions map onto hat/gamepad codes. That is not
publicly documented. Step 1 below resolves it empirically by diffing a keyboard-mode
dump against a game-mode dump, and the read-modify-write design means unknown bytes are
preserved rather than guessed at.

### Why hidraw and not libusb

Writing a Feature report via the `HIDIOCSFEATURE` ioctl on `/dev/hidrawN` is exactly the
same USB transaction as the libusb control transfer above, but it needs no libusb, no
pyusb, no udev rules, and no detaching the kernel HID driver. Batocera ships Python 3
and runs as root, so a stdlib-only script is a straight `scp` away from working.

## Deliverable

New standalone directory `~/AntiGravity/ipac-config/` (the `rom` repo is the romgi ROM
downloader — unrelated). Deployment is copying one file to the cabinet.

```
ipac-config/
  ipacconf.py                     # the whole tool: device + protocol + CLI + web UI
  profiles/
    batocera-gamepad.json         # both sticks + all buttons as gamepad 1 / gamepad 2
    mame-keyboard-default.json    # factory MAME-style keys, as a restore point
  fixtures/                       # recorded board dumps, used by the tests
  test_ipacconf.py                # stdlib unittest, runs on the Mac, no hardware
  README.md
```

`ipacconf.py` is one file on purpose — stdlib only, no build step, `scp ipacconf.py
root@batocera:/userdata/system/` and it runs.

### Internals

1. **Device layer** — enumerate `/sys/class/hidraw/*`, match VID/PID via
   `device/uevent` (`HID_ID`), pick the node whose parent USB interface
   `bInterfaceNumber` matches the firmware rule above, with a probe fallback that tries
   the other interface if a write or readback fails. Read `bcdDevice` from
   `/sys/bus/usb/devices/*` to report firmware version. `fcntl.ioctl` with
   `HIDIOCSFEATURE` = `_IOWR('H', 0x06, len)`; readback via `read()` guarded by
   `select` with a timeout.
2. **Protocol layer** — the 256-byte struct, the 4-byte chunker, the pin table, and the
   full code table (keys + gamepad/hat/analog/mouse). Pure functions over `bytearray`,
   no I/O, so the tests cover it without hardware.
3. **Profile layer** — JSON, deliberately matching QtPyUltimarc's `ipac2.json` schema
   (`pins[]` with `name` / `action` / `alternate_action` / `shift`) so profiles are
   portable to and from that ecosystem.
4. **CLI** — `list`, `dump [-o f]`, `apply <profile> [--dry-run] [--diff]`,
   `restore <backup>`, `serve [--port 8080]`.
5. **Web UI** — `ThreadingHTTPServer` serving one embedded HTML page (no CDN links; the
   cab may be offline). Visual panel of all 32 inputs — P1/P2 stick directions, 8
   buttons each, start/coin/A/B — each a dropdown over the code table, plus shift
   toggle and alternate action. Mode selector (keyboard / gamepad), buttons for Read
   from board, Apply, Backup, Restore, and the presets. Reachable from a laptop or
   phone on the LAN while the cabinet stays on screen. JSON API:
   `GET /api/device`, `GET /api/config`, `POST /api/config`, `GET|POST /api/profiles`.

### Safety rules, baked in

- Every write is **read-modify-write** on the board's current config — never a
  synthesized-from-scratch buffer. Bytes we do not understand survive untouched.
- Auto-backup to `/userdata/system/ipac-backups/<timestamp>.json` before every write.
- `--dry-run` prints a hexdump and a byte-level diff against what is on the board, and
  writes nothing.
- Hard refuse on `d208:0310` (pre-2015) with a clear message: different protocol, and
  flashing 2015 firmware onto those boards bricks them.

## Build order

1. **Read before write.** Build the device layer and `list` + `dump` only, against
   interface 2. Confirm we can pull a 256-byte config off the board on firmware 1.44.
   This works today and is the foundation for everything else. The keyboard-mode dump
   goes straight into `fixtures/`; the game-mode dump that specifies the gamepad bytes
   only becomes available after a Route A firmware upgrade.
2. **Protocol + tests.** Decoder and encoder over the fixtures; assert round-trip
   (`decode(encode(x)) == x`) and that re-encoding an untouched dump is byte-identical
   to the original. This runs on the Mac, no hardware.
3. **CLI apply.** `--dry-run` first, verify the diff is only the bytes intended, then a
   real write of a single harmless pin change and a re-dump to confirm it stuck.
4. **Gamepad profile.** `batocera-gamepad.json` built from what step 1 revealed.
5. **Web UI.** Serve, wire the API to the layers, add a `--fake-device` mode backed by a
   fixture file so the UI can be developed on the Mac.
6. **README** — deploy steps, the pre-2015 warning, recovery from backup.

## Verification

On the Mac:
- `python3 -m unittest test_ipacconf.py` — encode/decode round-trip against fixtures.
- `python3 ipacconf.py serve --fake-device fixtures/keyboard-mode.json` — exercise the
  full UI with no board attached.

On the cabinet (over SSH, `root` / default password `linux`):
- `python3 ipacconf.py list` → prints board, firmware version, config interface.
- `python3 ipacconf.py dump -o /userdata/system/ipac-backups/before.json`.
- `python3 ipacconf.py apply profiles/batocera-gamepad.json --dry-run --diff` → inspect
  the changed bytes, then re-run without `--dry-run`.
- Replug the board, then `ls /dev/input/js*` → two joystick nodes should appear, and
  ES's *Configure a controller* should see them as Ultimarc gamepads. Map them there.
- `python3 ipacconf.py restore before.json` must put the board back exactly as it was —
  test this deliberately, before relying on any of it.

## Risks

- **Game-mode encoding is undocumented.** Mitigated by step 1's diff and by
  read-modify-write. If the 10-second combo turns out not to work (firmware < 50), the
  diff reference is unavailable — in that case fall back to per-pin `GAMEPAD n` codes,
  which are documented, and if the board still enumerates as a keyboard, Batocera v41+
  ships `keyboardToPads` to synthesize virtual gamepads from a keyboard encoder without
  touching the board at all.
- **Interface number varies with firmware.** Handled by the `bcdDevice` rule plus a
  probe fallback across both candidate interfaces.
- **Batocera Python version.** Verify with `python3 -V` on the box in step 1; the code
  targets 3.9+ and stdlib only.
- **I cannot test against the hardware** — I am on the Mac and the board is on the
  cabinet. Everything hardware-facing needs you to run the command and paste the output;
  the plan is sequenced so each hardware step is one short command.

## Aside: firmware flashing on Linux

**Check whether it's even needed first.** `lsusb -d d209:0420 -v | grep bcdDevice` gives
the firmware version. The map (from Ultimarc-linux `README.fw`):

| Version | Behaviour |
|---|---|
| 1.22–1.33 | Keyboard only — gamepad mode requires a flash |
| 1.34–1.39 | Mixed mode: keyboard **and** gamepad simultaneously (config lives on interface 3) |
| 1.44–1.49 | Keyboard, no gamepad — requires a flash |
| 1.50–1.57 | Multi-mode: switch modes by hotkey, **no flash needed** |

New boards ship with multi-mode, so this is likely moot. On 1.50+, hold for 10 seconds:

- `Start1 + P1SW1` → keyboard mode
- `Start1 + P1SW2` → Dinput (dual gamepad) ← what Batocera wants
- `Start1 + P1SW3` → Xinput
- Backdoor recovery if a mode change goes wrong: **hold P1SW1 while plugging in USB**

Mode switching needs the shift function enabled (default: Start1 is the shift control).
Note also that in Xinput mode the config interface is unavailable — WinIPAC can't
reconfigure there, and neither will this tool. Configure in keyboard or Dinput mode.

**If a flash really is needed: use Windows once.** Not because Linux can't, but because
this is the one operation that bricks the board, and no public tool does it.

What the research found: firmware ships as `.ufw` files (`ipac_multimode.zip`), which are
plain ASCII-hex packet scripts — 171 records, `FF38…` start, `FF39…` data (one address
byte + 64-byte block each), `FF3B…` end. Those look like raw HID reports to be replayed
straight at Ultimarc's bootloader, so a Linux flasher is plausible. The missing piece is
the command that puts the board *into* bootloader mode: it is issued by WinIPAC over the
config protocol, is undocumented, and is not implemented in Ultimarc-linux or
QtPyUltimarc. Recovering it means a USB capture on Windows — at which point Windows is
already available, so just use WinIPAC v2 and spend five minutes instead of a weekend.
A Windows VM with USB passthrough is enough. Flashing 2015+ firmware onto a pre-2015
board bricks it permanently.
