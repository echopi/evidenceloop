"""Android tombstone parser.

The format is close to the platform tombstone but also covers crash SDK
dumps that embed a second ``signal`` block from a subprocess. The parser is
deliberately tolerant: unknown lines are ignored and every field is optional.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List

from ..util import bounded, env_int

MAX_FRAMES = env_int("ELOOP_MAX_FRAMES", 8)
MAX_TRANSLATED = env_int("ELOOP_MAX_TRANSLATED", 8)
MAX_TEXT = env_int("ELOOP_MAX_TEXT", 240)

SKIP_SYMBOL_PREFIXES = ("std::", "__gnu_cxx", "absl::", "boost::", "testing::")

SIGNAL_RE = re.compile(
    r"^\s*>?\s*signal (\d+) \((SIG[A-Z]+)\), code (-?\d+) \(([^)]*)\)"
    r"(?:, fault addr (\S+))?"
)
PID_HEADER_RE = re.compile(r"^pid: (\d+), tid: (\d+)\s+>>> (.+) <<<")
SUBPROCESS_RE = re.compile(
    r"subprocess occurred exception, pid: (\d+), tid: (\d+), signal: (\d+)"
)
ABORT_RE = re.compile(r"Abort message:\s*'(.*)'")
FRAME_RE = re.compile(r"^\s*#(\d+) pc ([0-9a-fA-F]+)\s+(.*)$")
BASIC_RE = re.compile(r"Basic Information: 'pid: (\d+)/tid: (\d+)/time: (\d+)'")
APP_VERSION_RE = re.compile(r"Application Information: 'version: ([^/]+)")
MODEL_RE = re.compile(r"model: ([^/]+)")
SDK_RE = re.compile(r"sdk: (\d+)")
META_RE = re.compile(r"^([A-Za-z0-9_]*(?:[Vv]ersion|[Rr]evision)[A-Za-z0-9_]*):\s*(\S+)$")

INLINED_PREFIX = "(inlined by) "


def _new_event(signal: int, name: str, code: int, code_name: str, fault: Any) -> Dict[str, Any]:
    return {
        "signal": signal,
        "name": name,
        "code": code,
        "code_name": code_name,
        "fault_addr": fault,
        "pid": None,
        "tid": None,
        "process": None,
        "subprocess": False,
        "abort_message": None,
        "frame_count": 0,
        "frames": [],
        "translated": [],
        "app_frame": None,
    }


def _is_app_symbol(symbol: str) -> bool:
    if not symbol:
        return False
    if symbol.startswith("__"):
        return False
    return not symbol.startswith(SKIP_SYMBOL_PREFIXES)


def _symbol_from_translated(line: str) -> str:
    stripped = line.strip()
    if stripped.startswith(INLINED_PREFIX):
        return stripped[len(INLINED_PREFIX) :]
    match = re.match(r"^#\d+ pc [0-9a-fA-F]+ (.*)$", stripped)
    return match.group(1) if match else ""


def parse_tombstone(path: Path) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "format": "android_tombstone",
        "basic": {},
        "app": {},
        "signal_events": [],
        "abort_messages": [],
    }
    current: Any = None
    in_translated = False
    last_pid_header: Dict[str, Any] = {}
    pending_header: Any = None

    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\n")

            match = BASIC_RE.search(line)
            if match:
                summary["basic"] = {
                    "pid": int(match.group(1)),
                    "tid": int(match.group(2)),
                    "time": match.group(3),
                }
            match = APP_VERSION_RE.search(line)
            if match:
                summary["app"]["version"] = match.group(1)
            match = MODEL_RE.search(line)
            if match:
                summary["app"]["model"] = match.group(1)
            match = SDK_RE.search(line)
            if match:
                summary["app"]["sdk"] = match.group(1)
            match = META_RE.match(line.strip())
            if match:
                summary["app"].setdefault("metadata", {})[match.group(1)] = bounded(
                    match.group(2), 120
                )

            match = PID_HEADER_RE.match(line)
            if match:
                last_pid_header = {
                    "pid": int(match.group(1)),
                    "tid": int(match.group(2)),
                    "process": bounded(match.group(3), 80),
                    "subprocess": False,
                }

            match = SUBPROCESS_RE.search(line)
            if match:
                pending_header = {
                    "pid": int(match.group(1)),
                    "tid": int(match.group(2)),
                    "process": "subprocess",
                    "subprocess": True,
                }

            match = SIGNAL_RE.match(line)
            if match:
                header = pending_header or last_pid_header
                current = _new_event(
                    int(match.group(1)),
                    match.group(2),
                    int(match.group(3)),
                    match.group(4),
                    match.group(5),
                )
                current.update(
                    {
                        "pid": header.get("pid"),
                        "tid": header.get("tid"),
                        "process": header.get("process"),
                        "subprocess": header.get("subprocess", False),
                    }
                )
                pending_header = None
                summary["signal_events"].append(current)
                in_translated = False
                continue

            if current is None:
                continue

            match = ABORT_RE.search(line)
            if match:
                message = bounded(match.group(1), MAX_TEXT)
                current["abort_message"] = message
                summary["abort_messages"].append(message)

            if "translate by crash parser" in line:
                in_translated = True
                continue

            stripped = line.strip()
            if in_translated and (
                stripped.startswith(INLINED_PREFIX) or "LINE:" in stripped
            ):
                symbol = _symbol_from_translated(stripped)
                if symbol and current["app_frame"] is None and _is_app_symbol(symbol):
                    current["app_frame"] = bounded(stripped, 300)
                if stripped.startswith(INLINED_PREFIX) and len(current["translated"]) < MAX_TRANSLATED:
                    current["translated"].append(bounded(stripped, 300))
                    continue

            match = FRAME_RE.match(line)
            if not match:
                continue

            current["frame_count"] += 1
            if "LINE:" in line and in_translated:
                if len(current["translated"]) < MAX_TRANSLATED:
                    current["translated"].append(bounded(line, 300))
                continue

            if len(current["frames"]) >= MAX_FRAMES:
                continue
            index = int(match.group(1))
            pc = match.group(2)
            if any(frame["idx"] == index and frame["pc"] == pc for frame in current["frames"]):
                continue
            rest = match.group(3).strip()
            symbol = ""
            if " (" in rest and rest.endswith(")"):
                symbol = rest[rest.rfind("(") + 1 : -1]
            lib = os.path.basename(rest.split()[0]) if "/" in rest else ""
            current["frames"].append(
                {
                    "idx": index,
                    "pc": pc,
                    "lib": lib,
                    "symbol": bounded(symbol, 160) if symbol else "",
                }
            )

    summary["signal_count"] = len(summary["signal_events"])
    summary["signal_names"] = [event["name"] for event in summary["signal_events"]]
    return summary
