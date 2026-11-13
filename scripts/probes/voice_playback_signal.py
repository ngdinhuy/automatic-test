#!/usr/bin/env python3
"""Kiểm tra vòng đời player media theo UID trên máy nhận tin thoại."""
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tammi_runner.audio_capture import adb
from tammi_runner.common import Blocked, save_private_json
from tammi_runner.ringback_signals import snapshot, stopped


def main(payload):
    role = "B"
    serial = payload["devices"][role]
    config = {"devices": {role: {"udid": serial}}, "tools": payload.get("tools", {})}
    package = payload["app_package"]
    phase = payload["phase"]
    result = {"schema": 1, "challenge": payload["challenge"], "mode": "adb_signals",
              "scope": "Vòng đời player media theo UID trên máy nhận.", "measurements": {}}
    info = adb(config, role, "shell", "pm", "list", "packages", "-U", package)
    match = re.search(r"^package:" + re.escape(package) + r" uid:(\d+)$", info, re.M)
    if not match:
        raise Blocked("Không xác minh được UID ứng dụng trên máy nhận.")
    uid = int(match[1])

    if phase == "check":
        snapshot(adb(config, role, "shell", "dumpsys", "audio"), uid)
        return {**result, "ready": True, "checks": ["Đọc được UID và bảng playback trên B."]}
    if phase == "cleanup" or (phase == "prepare" and payload.get("stage") != "baseline"):
        return result

    marker = payload["marker"]
    if not re.fullmatch(r"APPIUM-[a-f0-9]{12}", marker):
        raise ValueError("Marker voice không hợp lệ.")
    folder = Path(payload["report_directory"]) / ("voice-" + marker)
    folder.mkdir(parents=True, exist_ok=True)
    state_path = folder / "baseline.json"

    def take(label):
        raw = adb(config, role, "shell", "dumpsys", "audio")
        players = snapshot(raw, uid)["players"]
        save_private_json(folder / (label + ".json"), {
            "time": time.time(), "challenge": payload["challenge"], "uid": uid,
            "role": role, "players": players, "audio": raw,
        })
        return players

    if phase == "prepare":
        before = take("before")
        if any(row["state"] == "started" for row in before):
            raise Blocked("Máy nhận đã có player của app đang phát trước khi bấm phát tin thoại.")
        save_private_json(state_path, {"uid": uid, "serial": serial, "time": time.time()})
        return result
    if phase != "measure" or not state_path.is_file():
        raise Blocked("Thiếu baseline voice của lượt này.")
    state = json.loads(state_path.read_text())
    if (state["uid"], state["serial"]) != (uid, serial) or time.time() - state["time"] > 30:
        raise Blocked("Baseline voice đã hết hạn hoặc đổi thiết bị/UID.")

    for index in range(10):
        started = [row for row in take(f"during-{index}") if row["state"] == "started"
                   and row["usage"] in {"USAGE_MEDIA", "USAGE_UNKNOWN"}]
        if started:
            if len(started) != 1 or started[0]["muted"] is None:
                raise Blocked("Không quy được duy nhất một player có trường mutedState.")
            assert started[0]["muted"] is False, "Player voice đang muted."
            break
        time.sleep(.35)
    else:
        raise Blocked("Chưa quan sát được player voice đang phát trong cửa sổ đo.")

    consecutive = 0
    deadline = time.monotonic() + 25
    index = 0
    while time.monotonic() < deadline:
        players = take(f"after-{index}")
        consecutive = consecutive + 1 if stopped(started, {"players": players}) else 0
        if consecutive == 2:
            result["measurements"] = {"fresh_voice_players": len(started), "voice_players_stopped": 1}
            return result
        index += 1
        time.sleep(.55)
    raise AssertionError("Player voice vẫn phát quá cửa sổ sau tin thoại test.")


if __name__ == "__main__":
    payload = json.load(sys.stdin)
    try:
        result = main(payload)
    except Blocked as error:
        result = {"schema": 1, "challenge": payload["challenge"], "blocked": str(error)}
    except Exception as error:
        print(type(error).__name__ + ": " + str(error), file=sys.stderr)
        sys.exit(1)
    print(json.dumps(result, ensure_ascii=False))
