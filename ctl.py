#!/usr/bin/env python3
"""Userspace HID control for Razer BlackShark V3 (1532:057A).

Talks the vendor report on hidraw (interface 5, report 0x02, 64 bytes).
Packet layout and command classes follow OpenRazer PR #2794
(razerkraken_driver.c / docs/v3_pro_protocol.md), V3 wireless variant.

Do not poll battery (class 0x21) more often than every few minutes — a ~2s
poll drops the 2.4 GHz link.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import argparse
import fcntl
import json
import os
import select
import time
from pathlib import Path

VID = 0x1532
PID = 0x057A
REPORT_LEN = 64
REPORT_ID = 0x02
DIR_WIRELESS = 0x80

PLUGIN_DIR = Path(__file__).resolve().parent
STATE_DIR = Path.home() / ".local" / "state" / "omarchy" / "blackshark"
STATE_PATH = STATE_DIR / "state.json"
LOCK_PATH = STATE_DIR / "ctl.lock"
DEBUG_LOG = STATE_DIR / "hid.log"
UDEV_RULE = PLUGIN_DIR / "99-razer-blackshark-v3.rules"

EQ_FREQS = ["31", "63", "125", "250", "500", "1k", "2k", "4k", "8k", "16k"]
EQ_PRESETS = ["Default", "Game", "Movie", "Music", "Esports"]
MIC_EQ_PRESETS = ["Default", "Esports", "Broadcast", "Mic Boost"]
FN_MODES = ["Game/Chat", "Sidetone", "Footsteps", "BT volume"]
LED_MODES = ["Connection", "Battery", "Battery warning"]
POWER_SAVE = [0, 15, 30, 45, 60]

# Factory headphone EQ, 10 bands at EQ_FREQS, dB in -6..+6 (Synapse tables).
FACTORY_EQ = {
    0: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    1: [2, 2, 5, 5, 1, -1, 2, 3, 3, 3],
    2: [3, 3, 3, -1, -4, -4, 2, 3, 3, 3],
    3: [2, 2, 0, 0, 1, -1, -1, 3, 3, 3],
    4: [1, 1, -1, 0, 2, 0, 4, 4, 4, -3],
}

# 0xe0 apply bytes [14], [17], [18] per factory slot.
EQ_APPLY = {
    0: (0x00, 0x00, 0x01),
    1: (0x01, 0x01, 0x01),
    2: (0x03, 0x03, 0x01),
    3: (0x02, 0x02, 0x01),
    4: (0x04, 0x0A, 0x00),
}

CLS_INIT = 0x02
CLS_EQ_BANDS_GET = 0x15
CLS_MIC_EQ_PRESET_GET = 0x16
CLS_MIC_EQ_BANDS_GET = 0x17
CLS_SIDETONE_GET = 0x19
CLS_BATTERY = 0x21
CLS_CHARGE = 0x2A
CLS_POWER_GET = 0x2C
CLS_MIC_MUTE = 0x55
CLS_INCALL_GET = 0x5D
CLS_ULL_GET = 0x5F
CLS_EQ_META_GET = 0x60
CLS_MIX_GET = 0x65
CLS_PROMPTS_GET = 0x66
CLS_FN_GET = 0x6A
CLS_EQ_SET = 0x95
CLS_MIC_EQ_PRESET_SET = 0x96
CLS_MIC_EQ_DATA = 0x97
CLS_SIDETONE_INIT = 0x98
CLS_SIDETONE_SET = 0x99
CLS_THX = 0x9E
CLS_POWER_SET = 0xAC
CLS_MIX_SET = 0xDC
CLS_INCALL_SET = 0xDD
CLS_ULL_SET = 0xDF
CLS_EQ_APPLY = 0xE0
CLS_EQ_BEGIN = 0xE1
CLS_PROMPTS_SET = 0xE5
CLS_LED_SET = 0xE6

CLASS_NAMES = {
    0x00: "serial",
    0x02: "init",
    0x15: "eq-bands",
    0x16: "mic-eq",
    0x17: "mic-bands",
    0x19: "sidetone",
    0x20: "rf-link",
    0x21: "battery",
    0x2A: "charge",
    0x2C: "power",
    0x55: "mic-mute",
    0x5D: "incall",
    0x5F: "ull",
    0x60: "eq-meta",
    0x65: "mix",
    0x66: "prompts",
    0x6A: "fn",
    0x95: "eq-set",
    0x96: "mic-eq-set",
    0x97: "mic-eq-data",
    0x98: "sidetone-on",
    0x99: "sidetone-set",
    0x9E: "thx",
    0xAC: "power-set",
    0xDC: "mix-set",
    0xDD: "incall-set",
    0xDF: "ull-set",
    0xE0: "eq-apply",
    0xE1: "eq-gate",
    0xE5: "prompts-set",
    0xE6: "led",
    0xEA: "fn-set",
    0xEB: "eq-commit",
}
CLS_FN_SET = 0xEA
CLS_EQ_COMMIT = 0xEB

DEFAULT_STATE = {
    "eqPreset": 1,
    "eqBands": list(FACTORY_EQ[1]),
    "sidetone": 0,
    "thx": False,
    "ull": False,
    "mix": 10,
    "micEq": 0,
    "micEqBands": [0] * 10,
    "prompts": True,
    "fn": 0,
    "powerSave": 15,
    "led": 0,
    "incall": 0,
    "battery": None,
    "charging": None,
    "micMuted": None,
    "batteryTs": 0,
    "serial": "",
}


def _ioc(direction: int, type_: str, nr: int, size: int) -> int:
    return (direction << 30) | (size << 16) | (ord(type_) << 8) | nr


def HIDIOCSFEATURE(n: int) -> int:
    return _ioc(3, "H", 0x06, n)


def HIDIOCGFEATURE(n: int) -> int:
    return _ioc(3, "H", 0x07, n)


def HIDIOCSOUTPUT(n: int) -> int:
    return _ioc(3, "H", 0x0B, n)


def HIDIOCGOUTPUT(n: int) -> int:
    return _ioc(3, "H", 0x0C, n)


def HIDIOCGINPUT(n: int) -> int:
    return _ioc(3, "H", 0x0A, n)


def crc_of(buf: bytes | bytearray) -> int:
    c = 0
    for b in buf[:62]:
        c ^= b
    return c


def gain_encode(v: int) -> int:
    v = max(-6, min(6, int(v)))
    return (0x80 | (-v)) if v < 0 else v


def gain_decode(b: int) -> int:
    b &= 0xFF
    return -(b & 0x7F) if b & 0x80 else b


def find_hidraw() -> Path | None:
    root = Path("/sys/class/hidraw")
    if not root.exists():
        return None
    for node in sorted(root.iterdir()):
        uevent = node / "device" / "uevent"
        try:
            text = uevent.read_text()
        except OSError:
            continue
        if "HID_ID=0003:00001532:0000057A" in text:
            return Path("/dev") / node.name
    return None


def load_state() -> dict:
    state = dict(DEFAULT_STATE)
    try:
        raw = json.loads(STATE_PATH.read_text())
        if isinstance(raw, dict):
            state.update(raw)
    except (OSError, json.JSONDecodeError):
        pass
    if not isinstance(state.get("eqBands"), list) or len(state["eqBands"]) != 10:
        state["eqBands"] = list(FACTORY_EQ.get(int(state.get("eqPreset") or 1), FACTORY_EQ[1]))
    return state


def save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    tmp.replace(STATE_PATH)


def empty_report() -> bytearray:
    buf = bytearray(REPORT_LEN)
    buf[0] = REPORT_ID
    buf[2] = 0x60
    return buf


def finish(buf: bytearray) -> bytearray:
    buf[62] = crc_of(buf)
    buf[63] = 0x00
    return buf


def build_cmd(cls: int, args: list[int] | None = None, dir_byte: int = DIR_WIRELESS, sub: int = 0, argc: int | None = None) -> bytearray:
    args = list(args or [])
    if argc is None:
        argc = len(args)
    buf = empty_report()
    buf[6] = 4 + len(args)
    buf[9] = dir_byte
    buf[10] = cls
    buf[11] = sub
    buf[12] = argc
    for i, v in enumerate(args):
        buf[13 + i] = v & 0xFF
    return finish(buf)


def build_get(cls: int, args: list[int] | None = None, dir_byte: int = DIR_WIRELESS) -> bytearray:
    return build_cmd(cls, args, dir_byte=dir_byte)


def build_set_val(cls: int, val: int, dir_byte: int = DIR_WIRELESS) -> bytearray:
    buf = empty_report()
    buf[6] = 0x05
    buf[9] = dir_byte
    buf[10] = cls
    buf[11] = 0x00
    buf[12] = 0x01
    buf[13] = val & 0xFF
    return finish(buf)


def build_eq_cmds(bands: list[int], profile: int) -> list[bytearray]:
    profile = max(0, min(4, int(profile)))
    ap = EQ_APPLY[profile]
    encoded = [gain_encode(b) for b in bands]

    begin = build_set_val(CLS_EQ_BEGIN, 0x01)

    data = empty_report()
    data[6] = 0x0F
    data[9] = DIR_WIRELESS
    data[10] = CLS_EQ_SET
    data[12] = 0x0B
    data[13] = profile
    for i, b in enumerate(encoded):
        data[14 + i] = b
    data = finish(data)

    apply = empty_report()
    apply[6] = 0x0A
    apply[9] = DIR_WIRELESS
    apply[10] = CLS_EQ_APPLY
    apply[12] = 0x06
    apply[13] = profile
    apply[14] = ap[0]
    apply[15] = 0x01
    apply[16] = 0x01
    apply[17] = ap[1]
    apply[18] = ap[2]
    apply = finish(apply)

    end = build_set_val(CLS_EQ_BEGIN, 0x02)

    commit = empty_report()
    commit[6] = 0x0F
    commit[9] = DIR_WIRELESS
    commit[10] = CLS_EQ_COMMIT
    commit[12] = 0x0B
    commit[13] = profile
    commit[16] = 0x01
    commit[17] = 0x01
    commit = finish(commit)

    return [begin, data, apply, end, commit]


class Headset:
    def __init__(self) -> None:
        self.path = find_hidraw()
        self.fd: int | None = None
        self.handshook = False
        self.last_reply: bytes | None = None
        self.error = ""

    @property
    def connected(self) -> bool:
        return self.path is not None and self.path.exists()

    @property
    def permitted(self) -> bool:
        return bool(self.path and os.access(self.path, os.R_OK | os.W_OK))

    def open(self) -> None:
        if self.fd is not None:
            return
        if not self.path:
            raise FileNotFoundError("BlackShark V3 hidraw not found")
        self.fd = os.open(str(self.path), os.O_RDWR | os.O_NONBLOCK)

    def close(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def _ioctl(self, req: int, buf: bytearray) -> bytearray | None:
        assert self.fd is not None
        try:
            fcntl.ioctl(self.fd, req, buf, True)
            return buf
        except OSError:
            return None

    def send(self, buf: bytearray) -> str | None:
        # Output SET_REPORT (HIDIOCSOUTPUT) is what the device actually
        # executes. hidraw write() can return 64 without a SET_REPORT URB
        # when there is no interrupt-OUT endpoint, so it must not go first.
        self.open()
        payload = bytes(buf)
        copy = bytearray(payload)
        if self._ioctl(HIDIOCSOUTPUT(REPORT_LEN), copy) is not None:
            time.sleep(0.003)
            return "output"
        copy = bytearray(payload)
        if self._ioctl(HIDIOCSFEATURE(REPORT_LEN), copy) is not None:
            time.sleep(0.003)
            return "feature"
        try:
            n = os.write(self.fd, payload)  # type: ignore[arg-type]
            time.sleep(0.003)
            return "write" if n == REPORT_LEN else None
        except OSError:
            return None

    @staticmethod
    def is_envelope(data: bytes | None) -> bool:
        return bool(data and len(data) >= 14 and data[0] == REPORT_ID and data[2] == 0x60)

    def drain(self, timeout: float = 0.12) -> None:
        assert self.fd is not None
        first = timeout
        while True:
            r, _, _ = select.select([self.fd], [], [], first)
            if not r:
                break
            try:
                os.read(self.fd, 128)
            except OSError:
                break
            first = 0.04

    def recv_cls(self, cls: int, timeout: float = 0.5) -> bytes | None:
        assert self.fd is not None
        deadline = time.time() + timeout
        while time.time() < deadline:
            r, _, _ = select.select([self.fd], [], [], max(0.0, deadline - time.time()))
            if not r:
                break
            try:
                data = os.read(self.fd, 128)
            except OSError:
                break
            if not self.is_envelope(data):
                continue
            if data[10] == cls:
                self.last_reply = data
                return data
        return None

    def transact(self, buf: bytearray, wait: float = 0.5) -> bytes | None:
        if not self.send(buf):
            return None
        return self.recv_cls(buf[10], wait)

    def handshake(self) -> bool:
        if self.handshook:
            return True
        primers = ((CLS_INIT, 0x00), (CLS_CHARGE, 0x00), (CLS_CHARGE, DIR_WIRELESS))
        ok = True
        for cls, direction in primers:
            pkt = build_cmd(cls, [], dir_byte=direction, argc=0)
            if not self.send(pkt):
                ok = False
            time.sleep(0.002)
        self.drain(0.25)
        self.handshook = ok
        return ok

    def get(self, cls: int, args: list[int] | None = None) -> bytes | None:
        self.handshake()
        return self.transact(build_get(cls, args), wait=0.5)

    def parse_reply(self, data: bytes | None, cls: int) -> list[int] | None:
        if not self.is_envelope(data) or data[10] != cls:
            return None
        argc = data[12]
        return list(data[13 : 13 + max(1, min(16, argc or 1))])


def with_lock(fn):
    def wrapped(*args, **kwargs):
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOCK_PATH, "a+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            return fn(*args, **kwargs)

    return wrapped


def snapshot(hs: Headset, state: dict, live: dict, error: str = "") -> dict:
    preset = int(state.get("eqPreset") or 0)
    mic = int(state.get("micEq") or 0)
    fn = int(state.get("fn") or 0)
    led = int(state.get("led") or 0)
    out = {
        "ok": True,
        "connected": hs.connected,
        "permission": hs.permitted,
        "hidraw": str(hs.path) if hs.path else "",
        "live": bool(live.get("any")),
        "handshake": hs.handshook,
        "eqPreset": preset,
        "eqPresetName": EQ_PRESETS[preset] if 0 <= preset < len(EQ_PRESETS) else "Custom",
        "eqBands": [int(x) for x in state.get("eqBands") or FACTORY_EQ[1]],
        "eqFreqs": EQ_FREQS,
        "sidetone": int(state.get("sidetone") or 0),
        "thx": bool(state.get("thx")),
        "ull": bool(state.get("ull")),
        "mix": int(state.get("mix") if state.get("mix") is not None else 10),
        "micEq": mic,
        "micEqName": MIC_EQ_PRESETS[mic] if 0 <= mic < len(MIC_EQ_PRESETS) else "Default",
        "micEqBands": [int(x) for x in state.get("micEqBands") or [0] * 10],
        "prompts": bool(state.get("prompts")),
        "fn": fn,
        "fnName": FN_MODES[fn] if 0 <= fn < len(FN_MODES) else FN_MODES[0],
        "powerSave": int(state.get("powerSave") or 0),
        "led": led,
        "ledName": LED_MODES[led] if 0 <= led < len(LED_MODES) else LED_MODES[0],
        "incall": int(state.get("incall") or 0),
        "battery": state.get("battery"),
        "charging": state.get("charging"),
        "micMuted": state.get("micMuted"),
        "serial": state.get("serial") or "",
        "error": error or hs.error,
        "needsUdev": hs.connected and not hs.permitted,
        "factoryEq": {str(k): v for k, v in FACTORY_EQ.items()},
        "liveFields": sorted(k for k, v in live.items() if v and k != "any"),
    }
    return out


def refresh_reads(hs: Headset, state: dict, want_battery: bool) -> dict:
    live: dict = {"any": False}
    if not hs.permitted:
        return live
    try:
        hs.open()
        hs.handshake()
    except OSError as exc:
        hs.error = str(exc)
        return live

    now = time.time()
    last = float(state.get("batteryTs") or 0)
    if want_battery and now - last >= 300:
        data = hs.get(CLS_BATTERY)
        args = hs.parse_reply(data, CLS_BATTERY)
        # 0xFF = dongle "not ready" (GET channel gated until Windows-sized
        # first config descriptor). Never store 255 as a percent.
        if args and 0 <= args[0] <= 100:
            state["battery"] = args[0]
            live["battery"] = True
            live["any"] = True
        state["batteryTs"] = now
        charge = hs.get(CLS_CHARGE)
        cargs = hs.parse_reply(charge, CLS_CHARGE)
        if cargs and cargs[0] in (0, 1):
            state["charging"] = bool(cargs[0])
            live["charging"] = True
            live["any"] = True
    return live


@with_lock
def cmd_status(want_battery: bool) -> dict:
    hs = Headset()
    state = load_state()
    error = ""
    live: dict = {"any": False}
    if not hs.connected:
        error = "Headset not connected"
    elif not hs.permitted:
        error = "Need hidraw access — click Grant HID access"
    elif want_battery:
        try:
            live = refresh_reads(hs, state, True)
            save_state(state)
        except OSError as exc:
            error = str(exc)
        finally:
            hs.close()
    return snapshot(hs, state, live, error)


@with_lock
def cmd_set(kind: str, value) -> dict:
    hs = Headset()
    state = load_state()
    if not hs.connected:
        return snapshot(hs, state, {}, "Headset not connected")
    if not hs.permitted:
        return snapshot(hs, state, {}, "Need hidraw access — click Grant HID access")

    error = ""
    try:
        hs.open()
        packets: list[bytearray] = []

        if kind == "eq":
            preset = max(0, min(4, int(value)))
            bands = list(FACTORY_EQ[preset])
            packets = build_eq_cmds(bands, preset)
            state["eqPreset"] = preset
            state["eqBands"] = bands
        elif kind == "eq-bands":
            bands = [max(-6, min(6, int(x))) for x in value]
            if len(bands) != 10:
                raise ValueError("eq-bands needs 10 values")
            preset = int(state.get("eqPreset") or 1)
            if preset == 0:
                preset = 1
            packets = build_eq_cmds(bands, preset)
            state["eqPreset"] = preset
            state["eqBands"] = bands
        elif kind == "sidetone":
            # V3 captures (OpenRazer razer_attr_write_sidetone): 0x98 argc=1
            # arg=0x01, then 0x99 argc=1 arg=level. Early V3 Pro notes used
            # [0x01, 0x01] on 0x98; that extra byte is a no-op on this dongle.
            level = max(0, min(15, int(value)))
            packets = [
                build_set_val(CLS_SIDETONE_INIT, 0x01),
                build_set_val(CLS_SIDETONE_SET, level),
                build_get(CLS_SIDETONE_GET),
            ]
            state["sidetone"] = level
        elif kind == "thx":
            on = 1 if bool(value) else 0
            packets = [build_set_val(CLS_THX, on)]
            state["thx"] = bool(on)
        elif kind == "ull":
            on = 1 if bool(value) else 0
            packets = [build_set_val(CLS_ULL_SET, on)]
            state["ull"] = bool(on)
        elif kind == "mix":
            bal = max(0, min(20, int(value)))
            packets = [
                build_cmd(CLS_MIX_SET, [bal, 0x00], argc=0x01),
                build_cmd(0xE5, [bal], sub=0x01, argc=0x01),
            ]
            state["mix"] = bal
        elif kind == "mic-eq":
            idx = max(0, min(3, int(value)))
            packets = [build_set_val(CLS_MIC_EQ_PRESET_SET, 0x20 + idx)]
            state["micEq"] = idx
        elif kind == "mic-eq-bands":
            bands = [max(-6, min(6, int(x))) for x in value]
            if len(bands) != 10:
                raise ValueError("mic-eq-bands needs 10 values")
            pkt = empty_report()
            pkt[6] = 0x0E
            pkt[9] = DIR_WIRELESS
            pkt[10] = CLS_MIC_EQ_DATA
            pkt[12] = 0x0A
            for i, b in enumerate(bands):
                pkt[13 + i] = gain_encode(b)
            packets = [finish(pkt)]
            state["micEqBands"] = bands
        elif kind == "prompts":
            on = 1 if bool(value) else 0
            packets = [build_cmd(CLS_PROMPTS_SET, [0x00, on, 0x00], argc=0x02)]
            state["prompts"] = bool(on)
        elif kind == "fn":
            mode = max(0, min(3, int(value)))
            packets = [build_set_val(CLS_FN_SET, mode)]
            state["fn"] = mode
        elif kind == "power-save":
            minutes = int(value)
            if minutes not in POWER_SAVE:
                minutes = min(POWER_SAVE[1:], key=lambda x: abs(x - minutes))
            packets = [build_set_val(CLS_POWER_SET, minutes)]
            state["powerSave"] = minutes
        elif kind == "led":
            mode = max(0, min(2, int(value)))
            packets = [build_set_val(CLS_LED_SET, mode)]
            state["led"] = mode
        elif kind == "incall":
            mode = max(0, min(2, int(value)))
            packets = [build_cmd(CLS_INCALL_SET, [mode, 0x00], argc=0x01)]
            state["incall"] = mode
        else:
            raise ValueError(f"unknown set kind {kind}")

        debug_events = []
        for pkt in packets:
            via = hs.send(pkt)
            if not via:
                error = f"HID write failed for {kind}"
                debug_events.append({"type": "hid", "dir": "out", "name": "send-fail", "cls": pkt[10], "args": [], "hex": bytes(pkt)[:24].hex()})
                break
            ev = packet_event(pkt, "out")
            ev["via"] = via
            debug_events.append(ev)
            emit_debug(ev)
            ack = hs.recv_cls(pkt[10], 0.4)
            if ack:
                aev = packet_event(ack, "in")
                debug_events.append(aev)
                emit_debug(aev)
                if pkt[10] == CLS_SIDETONE_GET:
                    args = hs.parse_reply(ack, CLS_SIDETONE_GET)
                    if args and 0 <= args[0] <= 15:
                        state["sidetone"] = args[0]
            else:
                miss = {"type": "hid", "dir": "in", "name": "no-ack", "cls": pkt[10], "args": [], "hex": ""}
                debug_events.append(miss)
                emit_debug(miss)
        save_state(state)
    except Exception as exc:
        error = str(exc)
        debug_events = []
    finally:
        hs.close()
    snap = snapshot(hs, state, {"any": not error, kind: not error}, error)
    snap["debug"] = debug_events
    return snap


def cmd_install_udev() -> dict:
    return {
        "ok": True,
        "rule": str(UDEV_RULE),
        "command": [
            "pkexec",
            str(PLUGIN_DIR / "install-udev.sh"),
            str(UDEV_RULE),
        ],
    }


def emit_debug(ev: dict) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(DEBUG_LOG, "a") as handle:
            handle.write(json.dumps(ev) + "\n")
    except OSError:
        pass


def packet_event(data: bytes, direction: str) -> dict:
    if not data:
        return {"type": "hid", "dir": direction, "name": "empty", "hex": ""}
    envelope = Headset.is_envelope(data)
    cls = data[10] if len(data) > 10 else None
    name = CLASS_NAMES.get(cls, f"{cls:02x}") if cls is not None and envelope else "raw"
    argc = data[12] if envelope and len(data) > 12 else 0
    args = list(data[13 : 13 + max(0, min(8, argc or 0))]) if envelope and len(data) > 13 else []
    sub = data[11] if envelope and len(data) > 11 else None
    kind = None
    if direction == "in" and sub == 0x01:
        kind = "ack"
    elif direction == "in" and sub == 0x02:
        kind = "push"
    return {
        "type": "hid",
        "dir": direction,
        "report": data[0],
        "cls": cls,
        "name": name,
        "sub": sub,
        "kind": kind,
        "argc": argc,
        "args": args,
        "hex": data[: min(24, len(data))].hex(),
    }


def apply_push(state: dict, data: bytes) -> bool:
    if not Headset.is_envelope(data):
        return False
    cls = data[10]
    args = list(data[13 : 13 + max(1, min(16, data[12] or 1))])
    if not args:
        return False
    val = args[0]
    changed = False
    if cls in (CLS_MIX_GET, CLS_MIX_SET) and 0 <= val <= 20:
        state["mix"] = val
        changed = True
    elif cls == CLS_BATTERY and 0 <= val <= 100:
        state["battery"] = val
        state["batteryTs"] = time.time()
        changed = True
    elif cls == CLS_CHARGE and val in (0, 1):
        state["charging"] = bool(val)
        changed = True
    elif cls in (CLS_SIDETONE_GET, CLS_SIDETONE_SET) and 0 <= val <= 15:
        state["sidetone"] = val
        changed = True
    elif cls == CLS_MIC_MUTE and val in (0, 1):
        state["micMuted"] = bool(val)
        changed = True
    elif cls == CLS_THX and val in (0, 1):
        state["thx"] = bool(val)
        changed = True
    elif cls == CLS_ULL_GET and val in (0, 1):
        state["ull"] = bool(val)
        changed = True
    return changed


def cmd_monitor(poll_mix: bool, debug: bool) -> int:
    hs = Headset()
    state = load_state()
    if not hs.connected or not hs.permitted:
        print(json.dumps(snapshot(hs, state, {}, "Headset not connected" if not hs.connected else "Need hidraw access")), flush=True)
        return 1
    hs.open()
    hs.handshake()
    if debug:
        try:
            DEBUG_LOG.write_text("")
        except OSError:
            pass
        boot = {"type": "hid", "dir": "out", "name": "monitor", "args": [], "hex": "", "via": "start"}
        print(json.dumps(boot), flush=True)
        emit_debug(boot)
    print(json.dumps(snapshot(hs, state, {"any": True})), flush=True)
    last_mix_poll = 0.0
    last_batt_poll = float(state.get("batteryTs") or 0)
    try:
        while True:
            timeout = 0.4 if poll_mix else 1.0
            r, _, _ = select.select([hs.fd], [], [], timeout)
            now = time.time()
            changed = False
            if r:
                try:
                    data = os.read(hs.fd, 128)
                except OSError:
                    data = None
                if data:
                    pushed = apply_push(state, data)
                    if pushed:
                        changed = True
                    if debug:
                        ev = packet_event(data, "in")
                        # Mix GET replies fire ~2/s from --poll-mix; skip
                        # unchanged ones so the feed stays readable.
                        if not (ev.get("cls") == CLS_MIX_GET and not pushed):
                            print(json.dumps(ev), flush=True)
                            emit_debug(ev)
            if poll_mix and now - last_mix_poll >= 0.45:
                last_mix_poll = now
                with open(LOCK_PATH, "a+") as handle:
                    try:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        reply = None
                    else:
                        reply = hs.get(CLS_MIX_GET)
                args = hs.parse_reply(reply, CLS_MIX_GET) if reply else None
                if args and 0 <= args[0] <= 20 and args[0] != state.get("mix"):
                    state["mix"] = args[0]
                    changed = True
            if now - last_batt_poll >= 300:
                last_batt_poll = now
                with open(LOCK_PATH, "a+") as handle:
                    try:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        reply = None
                        charge = None
                    else:
                        reply = hs.get(CLS_BATTERY)
                        charge = hs.get(CLS_CHARGE)
                args = hs.parse_reply(reply, CLS_BATTERY) if reply else None
                if args and 0 <= args[0] <= 100:
                    state["battery"] = args[0]
                    state["batteryTs"] = now
                    changed = True
                cargs = hs.parse_reply(charge, CLS_CHARGE) if charge else None
                if cargs and cargs[0] in (0, 1):
                    state["charging"] = bool(cargs[0])
                    changed = True
            if changed:
                save_state(state)
                print(json.dumps(snapshot(hs, state, {"any": True})), flush=True)
    except KeyboardInterrupt:
        return 0
    finally:
        hs.close()
    return 0


def parse_bool(value: str) -> bool:
    return str(value).lower() in ("1", "on", "true", "yes")


def main() -> int:
    parser = argparse.ArgumentParser(prog="blackshark-ctl")
    sub = parser.add_subparsers(dest="cmd", required=True)

    st = sub.add_parser("status")
    st.add_argument("--battery", action="store_true")

    s = sub.add_parser("set")
    s.add_argument("kind")
    s.add_argument("values", nargs="+")

    sub.add_parser("install-udev")
    sub.add_parser("find")
    mon = sub.add_parser("monitor")
    mon.add_argument("--poll-mix", action="store_true")
    mon.add_argument("--debug", action="store_true")

    args = parser.parse_args()
    if args.cmd == "status":
        print(json.dumps(cmd_status(args.battery)))
        return 0
    if args.cmd == "find":
        path = find_hidraw()
        print(json.dumps({"hidraw": str(path) if path else None, "access": bool(path and os.access(path, os.R_OK | os.W_OK))}))
        return 0
    if args.cmd == "install-udev":
        print(json.dumps(cmd_install_udev()))
        return 0
    if args.cmd == "monitor":
        return cmd_monitor(args.poll_mix, args.debug)
    if args.cmd == "set":
        kind = args.kind
        values = args.values
        if kind in ("eq-bands", "mic-eq-bands"):
            payload = values
        elif kind in ("thx", "ull", "prompts"):
            payload = parse_bool(values[0])
        else:
            payload = values[0]
        print(json.dumps(cmd_set(kind, payload)))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
