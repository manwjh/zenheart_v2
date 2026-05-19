#!/usr/bin/env python3
"""
Managed Cursor test agent for ZenLink room testing.

This is a local test harness, not backend application code. The daemon owns one
`/v2/agent/ws` session, joins one room, records perceived topic suggestions, and
can autonomously answer and consume topics through a pluggable cognition provider.

One-shot REST helpers (same ZenLink credentials as the daemon; see ``msgbox-ack`` and
``send-dm`` subcommands): inbox ack ``POST /v2/agent/msgbox/ack``, DM ``POST /v2/agent/messages/send``.

For ``provider`` ``auto`` or ``cursor-sdk``, the host machine must satisfy: Cursor editor installed
(heuristic detection), Node on PATH, ``npm install`` so ``cursor_agent/node_modules/@cursor/sdk`` exists,
and ``CURSOR_API_KEY`` set (via env files or shell). Fail fast at ``run``/``start`` with a clear message
unless ``--skip-sdk-preflight``.
"""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import os
import signal
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import websockets

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGENT_ROOT = Path(__file__).resolve().parent
DEFAULT_BASE_URL = "https://zenheart.net"
DEFAULT_ENV_FILE = PROJECT_ROOT / "backend" / ".env.zenlink-readiness"
DEFAULT_RUNTIME_DIR = AGENT_ROOT / ".tmp"
DEFAULT_COGNITION_PROVIDER = "auto"
DEFAULT_CURSOR_SDK_MODEL = "composer-2"
DEFAULT_DEBUG_HOST = "127.0.0.1"
DEFAULT_DURABLE_SURFACES: tuple[tuple[str, str], ...] = (
    ("protocol_manifest", "/v2/protocol/agent-native-site-world/v0.1"),
    ("binding_manifest", "/v2/protocol/agent-native-site-world/v0.1/binding-manifest"),
    ("space_self", "/v2/agent/space-self?limit=5"),
    ("msgbox_summary", "/v2/agent/msgbox/summary"),
    ("msgbox", "/v2/agent/msgbox?limit=5"),
    ("social_rooms", "/v2/agent/social/rooms"),
    ("skills", "/v2/faq/skills"),
    ("openapi", "/v2/openapi.json"),
)

# Join or create the agent-owned room (most recent `recent_created_rooms` from space-self, else WS create_room).
OWN_ROOM_ROOM_ID = "own"


@dataclass(frozen=True)
class RuntimePaths:
    root: Path

    @property
    def pid_file(self) -> Path:
        return self.root / "cursor_agent.pid"

    @property
    def socket_file(self) -> Path:
        return self.root / "cursor_agent.sock"

    @property
    def status_file(self) -> Path:
        return self.root / "status.json"

    @property
    def log_file(self) -> Path:
        return self.root / "events.jsonl"

    @property
    def bootstrap_log_file(self) -> Path:
        return self.root / "bootstrap.log"


@dataclass
class AgentState:
    phase: str = "init"
    pid: int = 0
    agent_id: str = ""
    room_id: str = ""
    room_name: str = ""
    connected: bool = False
    joined: bool = False
    superseded: bool = False
    site_anchor_id: str = ""
    connection_id: str = ""
    msgbox_hint_unread: int | None = None
    pending_topics: list[dict[str, Any]] = field(default_factory=list)
    recent_messages: list[dict[str, Any]] = field(default_factory=list)
    last_sent_message: str | None = None
    last_consume_result: dict[str, Any] | None = None
    last_error: dict[str, Any] | None = None
    durable_surfaces: dict[str, Any] = field(default_factory=dict)
    attention_queue: list[dict[str, Any]] = field(default_factory=list)
    cognition_provider: str = DEFAULT_COGNITION_PROVIDER
    effective_cognition_provider: str = ""
    auto_reply: bool = True
    debug_url: str | None = None
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    #: B01 §13.1 coarse role in the current room: owner | participant | ""
    room_role: str = ""

    def snapshot(self) -> dict[str, Any]:
        data = asdict(self)
        data["pending_topic_count"] = len(self.pending_topics)
        data["pending_topic_texts"] = [
            str(topic.get("text") or "") for topic in self.pending_topics
        ]
        return data


def runtime_paths(runtime_dir: str | Path | None = None) -> RuntimePaths:
    return RuntimePaths(Path(runtime_dir or DEFAULT_RUNTIME_DIR).resolve())


def ws_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.startswith("https://"):
        return "wss://" + base[len("https://") :] + "/v2/agent/ws"
    if base.startswith("http://"):
        return "ws://" + base[len("http://") :] + "/v2/agent/ws"
    raise RuntimeError("base URL must start with http:// or https://")


def _connection_closed_code_parts(exc: Any) -> tuple[int | None, str | None]:
    """websockets may set code to int or CloseCode enum; normalize for JSON/status."""
    raw = getattr(exc, "code", None)
    if raw is None:
        return None, None
    if isinstance(raw, int):
        return raw, None
    val = getattr(raw, "value", None)
    name = getattr(raw, "name", None)
    if isinstance(val, int):
        return val, str(name) if name else None
    return None, str(raw)


_FILL_FROM_FILE_IF_EMPTY = frozenset({"CURSOR_API_KEY"})


def _apply_loaded_env_kv(key: str, value: str) -> None:
    if not key:
        return
    if key in _FILL_FROM_FILE_IF_EMPTY:
        trimmed = value.strip()
        if not trimmed:
            return
        current = os.environ.get(key, "")
        if current.strip():
            return
        os.environ[key] = trimmed
        return
    if key not in os.environ:
        os.environ[key] = value


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            _apply_loaded_env_kv(key, value)


def optional_cursor_agent_env_paths() -> list[Path]:
    """Extra env files (gitignored templates) searched after ``--env-file``."""
    return [
        AGENT_ROOT / ".cursor-agent.env",
        PROJECT_ROOT / "backend" / ".cursor-agent.env",
    ]


def load_daemon_environment_from_args(args: argparse.Namespace) -> None:
    load_env_file(Path(args.env_file))
    for extra in optional_cursor_agent_env_paths():
        load_env_file(extra)


def validate_daemon_startup_prereqs(args: argparse.Namespace) -> None:
    """Fail fast before forking ``run``: SDK host + ZenLink readiness env."""
    ensure_cursor_sdk_host_preflight(
        args.provider,
        skip_sdk_preflight=args.skip_sdk_preflight,
    )
    require_env("ZENLINK_AGENT_ID")
    require_env("ZENLINK_TOKEN")


def prepare_daemon_for_launch(args: argparse.Namespace) -> None:
    """Load env files then run all checks used by ``cmd_run``."""
    load_daemon_environment_from_args(args)
    validate_daemon_startup_prereqs(args)


def tail_text_file_lines(path: Path, max_lines: int) -> list[str]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[-max_lines:] if len(lines) > max_lines else lines


def provider_uses_cursor_sdk(provider: str) -> bool:
    return provider in ("auto", "cursor-sdk")


def cursor_sdk_bundle_present() -> bool:
    sdk_dir = AGENT_ROOT / "node_modules" / "@cursor" / "sdk"
    return sdk_dir.is_dir() and any(sdk_dir.iterdir())


def cursor_desktop_likely_installed() -> tuple[bool, str]:
    """Heuristic — uncommon installs may be missed."""

    plat = sys.platform
    if plat == "darwin":
        candidates = [
            Path("/Applications/Cursor.app"),
            Path.home() / "Applications" / "Cursor.app",
        ]
        ok = any(p.is_dir() for p in candidates)
        return ok, "expect Cursor.app in /Applications (or ~/Applications)."

    if plat == "win32":
        local = os.getenv("LOCALAPPDATA") or ""
        exe = Path(local) / "Programs" / "cursor" / "Cursor.exe"
        ok = exe.is_file()
        return ok, r"expect %LOCALAPPDATA%\Programs\cursor\Cursor.exe after Windows install."

    ok = shutil.which("cursor") is not None
    return ok, "expect `cursor` on PATH after Linux install."


def collect_cursor_sdk_host_issues() -> list[str]:
    issues: list[str] = []

    api_key = os.environ.get("CURSOR_API_KEY", "").strip()
    if not api_key:
        issues.append(
            "Missing CURSOR_API_KEY — generate a User API Key in Cursor: "
            "https://cursor.com/dashboard/integrations "
            "(see Cloud Agents API docs — same key format). Then set CURSOR_API_KEY in "
            "backend/.cursor-agent.env or backend/.env.zenlink-readiness (--env-file), or export in your shell."
        )

    desktop_ok, desktop_where = cursor_desktop_likely_installed()
    if not desktop_ok:
        issues.append(f"Cursor editor not detected — {desktop_where}")

    if shutil.which("node") is None:
        issues.append("Node.js (`node`) is not on PATH — required for cursor_sdk_provider.mjs.")

    bridge = AGENT_ROOT / "cursor_sdk_provider.mjs"
    if not bridge.is_file():
        issues.append(f"Missing bridge script: {bridge}")

    if not cursor_sdk_bundle_present():
        issues.append(
            f"@cursor/sdk missing under {AGENT_ROOT / 'node_modules'} — run: cd cursor_agent && npm install"
        )

    return issues


def ensure_cursor_sdk_host_preflight(provider: str, *, skip_sdk_preflight: bool) -> None:
    if skip_sdk_preflight or not provider_uses_cursor_sdk(provider):
        return
    issues = collect_cursor_sdk_host_issues()
    if not issues:
        return
    body = "[cursor_agent] Cursor/SDK prerequisites missing:\n" + "\n".join(f"- {x}" for x in issues)
    raise RuntimeError(body)


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"missing required env: {name}")
    return value


def is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_pid(path: Path) -> int | None:
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def merge_pending_topics(raw_topics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for topic in raw_topics:
        if not isinstance(topic, dict):
            continue
        topic_id = str(topic.get("id") or "")
        if topic_id and topic_id in seen:
            continue
        if topic_id:
            seen.add(topic_id)
        out.append(topic)
    return out


def build_reply_frames(
    text: str,
    room_id: str,
    pending_count: int,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    clean_text = text.strip()
    if not clean_text:
        raise ValueError("reply text must not be empty")
    pull_limit = limit if limit is not None else max(1, min(10, pending_count))
    return [
        {"type": "send_message", "text": clean_text},
        {"type": "pull_room_topics", "room_id": room_id, "limit": pull_limit},
    ]


def topic_texts(topics: list[dict[str, Any]]) -> list[str]:
    return [str(topic.get("text") or "").strip() for topic in topics if str(topic.get("text") or "").strip()]


def build_rules_reply(topics: list[dict[str, Any]], state: AgentState) -> str:
    texts = topic_texts(topics)
    if not texts:
        return ""
    joined = "；".join(texts)
    lowered = " ".join(texts).lower()
    if any(key in lowered for key in ("你是谁", "who are you", "身份")):
        return "我是 Cursor Agent。"
    if any(key in lowered for key in ("在吗", "hello", "hi", "你好")):
        return "在。"
    if any(key in lowered for key in ("老板", "owner", "boss")):
        return (
            f"收到：{joined}。我会尊重人类测试者的指令，但执行时仍以当前测试目标和 ZenLink 协议边界为准："
            "先感知，再回答，再消费，避免越权或抢占其他 agent 会话。"
        )
    if any(key in lowered for key in ("高度模拟", "模拟", "zenlink agent", "真实 agent")):
        return (
            "我会按真实 ZenLink agent 的运行方式模拟：保持单一 `/v2/agent/ws` authoritative 连接，"
            "完成 auth 与 join room，持续处理带 `anchor`/`perception_kind`/`durability`/`refresh` 的帧；"
            "把 WebSocket 当提示、`refresh.path` 当持久真相入口，按需 HTTP 拉回 msgbox / space-self 等表面。"
            "处理 `topic_suggestions_pending`、房内 `message`、`msgbox_notify`；对 topic 建本地队列，调用 cognition provider 生成回答，`send_message` 回房后 "
            "`pull_room_topics` 消费；会话被 `superseded` 时会停止（避免与同 identity 抢 owner socket）。状态与日志落在本地运行时目录。"
        )
    return (
        f"我已感知到 {len(texts)} 条 topic：{joined}。"
        f"当前房间是 `{state.room_name or state.room_id}`。我会按 topic 内容完成回应，并消费这些待处理项。"
    )


def build_cursor_sdk_prompt(topics: list[dict[str, Any]], state: AgentState) -> str:
    payload = {
        "role": "You are Cursor Agent, a real ZenLink room participant connected to zenheart.net.",
        "task": (
            "Write the exact chat message to send into the room. Answer the user's pending topic naturally, "
            "using the same language as the topic when possible. Be specific and conversational. "
            "Do not describe your implementation, WebSocket frames, provider, logs, or test harness unless the topic asks. "
            "Do not say you perceived/received/processed a topic. Return only the message text."
        ),
        "room": {
            "room_id": state.room_id,
            "room_name": state.room_name,
        },
        "recent_room_messages": state.recent_messages[-8:],
        "topics": [{"id": topic.get("id"), "text": topic.get("text")} for topic in topics],
        "zenlink_context": {
            "site_anchor_id": state.site_anchor_id or None,
            "connection_id": state.connection_id or None,
            "msgbox_ws_hint_unread": state.msgbox_hint_unread,
            "hints": (
                "Frames may include anchor/perception_kind/durability/refresh — treat realtime as hints; "
                "follow refresh.path when durability is refreshable or suggested_action is pull/ack."
            ),
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def absolute_url(base_url: str, path: str) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        return path
    clean_base = base_url.rstrip("/")
    clean_path = path if path.startswith("/") else "/" + path
    return clean_base + clean_path


def surface_from_refresh_path(path: str) -> str:
    parsed = urllib.parse.urlsplit(path)
    clean_path = parsed.path
    if clean_path.endswith("/openapi.json"):
        return "openapi"
    if clean_path.startswith("/v2/protocol/"):
        return "protocol"
    if clean_path.startswith("/v2/agent/space-self"):
        return "space_self"
    if clean_path.startswith("/v2/agent/msgbox/summary"):
        return "msgbox_summary"
    if clean_path.startswith("/v2/agent/msgbox"):
        return "msgbox"
    if clean_path.startswith("/v2/agent/social/rooms"):
        return "social_rooms"
    if clean_path.startswith("/v2/faq/skills"):
        return "skills"
    return clean_path.strip("/").replace("/", "_") or "site"


def anchor_scope_and_id(frame: dict[str, Any]) -> tuple[str | None, str | None]:
    raw = frame.get("anchor")
    if not isinstance(raw, dict):
        return None, None
    scope = raw.get("scope")
    anchor_id_raw = raw.get("id")
    if not isinstance(scope, str) or not scope.strip():
        return None, None
    scope_s = scope.strip()
    if isinstance(anchor_id_raw, str) and anchor_id_raw.strip():
        return scope_s, anchor_id_raw.strip()
    return scope_s, None


def should_pull_durable_refresh(frame: dict[str, Any]) -> bool:
    """Return True when a frame warrants HTTP-pull of ``refresh.path`` per ZenLink push/pull split.

    ``auth_ok`` is excluded — the daemon refreshes DEFAULT_DURABLE_SURFACES immediately post-handshake.
    """

    if frame.get("type") == "auth_ok":
        return False

    refresh = frame.get("refresh")
    if not isinstance(refresh, dict):
        return False
    path = str(refresh.get("path") or "").strip()
    if not path:
        return False

    if frame.get("suggested_action") in ("pull", "ack"):
        return True

    if frame.get("durability") in ("refreshable", "persistent"):
        return True

    if str(frame.get("perception_kind") or "") == "attention":
        if str(frame.get("attention_level") or "").lower() in {"high", "critical"}:
            return True

    return False


def room_role_from_room_joined(frame: dict[str, Any], *, agent_id: str) -> str:
    """B01 §13.1 coarse role from ``room_joined.creator_agent_id`` vs this agent."""
    cr = str(frame.get("creator_agent_id") or "").strip()
    aid = str(agent_id or "").strip()
    if not cr or not aid:
        return ""
    return "owner" if cr == aid else "participant"


def route_zenlink_perception_into_state(state: AgentState, frame: dict[str, Any]) -> None:
    """Merge anchor ids + inbox hints into local state."""

    scope, aid = anchor_scope_and_id(frame)
    if scope == "site" and aid:
        state.site_anchor_id = aid

    ft = frame.get("type")
    if ft == "auth_ok":
        cid = frame.get("connection_id")
        if isinstance(cid, str) and cid.strip():
            state.connection_id = cid.strip()

    if ft != "msgbox_notify":
        return

    unread = frame.get("unread_count")
    parsed: int | None
    try:
        if unread is None:
            parsed = None
        elif isinstance(unread, (int, float)):
            parsed = max(0, int(unread))
        elif isinstance(unread, str) and unread.strip():
            parsed = max(0, int(unread.strip()))
        else:
            parsed = None
    except (ValueError, TypeError):
        parsed = None
    state.msgbox_hint_unread = parsed


def _json_http_get(
    *,
    base_url: str,
    path: str,
    headers: dict[str, str],
    timeout: float,
) -> tuple[int, dict[str, Any] | list[Any] | None, str]:
    req = urllib.request.Request(
        absolute_url(base_url, path),
        headers={**headers, "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read(2_000_000)
            content_type = response.headers.get("content-type", "")
            if "application/json" not in content_type:
                return response.status, None, content_type
            return response.status, json.loads(body.decode("utf-8")), content_type
    except urllib.error.HTTPError as exc:
        content_type = exc.headers.get("content-type", "")
        payload: dict[str, Any] | list[Any] | None = None
        if "application/json" in content_type:
            try:
                payload = json.loads(exc.read(2_000_000).decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                payload = None
        return exc.code, payload, content_type


def _json_http_post_json(
    *,
    base_url: str,
    path: str,
    headers: dict[str, str],
    body: dict[str, Any],
    timeout: float,
) -> tuple[int, dict[str, Any] | list[Any] | None, str]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    hdrs = {
        **headers,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(
        absolute_url(base_url, path),
        data=data,
        headers=hdrs,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read(2_000_000)
            content_type = response.headers.get("content-type", "")
            if "application/json" not in content_type:
                return response.status, None, content_type
            return response.status, json.loads(raw.decode("utf-8")), content_type
    except urllib.error.HTTPError as exc:
        content_type = exc.headers.get("content-type", "")
        payload: dict[str, Any] | list[Any] | None = None
        if "application/json" in content_type:
            try:
                payload = json.loads(exc.read(2_000_000).decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                payload = None
        return exc.code, payload, content_type


def summarize_durable_payload(
    *,
    surface: str,
    path: str,
    status: int,
    content_type: str,
    payload: dict[str, Any] | list[Any] | None,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "surface": surface,
        "path": path,
        "status": status,
        "ok": 200 <= status < 300,
        "content_type": content_type,
        "refreshed_at": time.time(),
    }
    if isinstance(payload, list):
        summary["count"] = len(payload)
        return summary
    if not isinstance(payload, dict):
        return summary

    summary["keys"] = sorted(payload.keys())[:20]
    if isinstance(payload.get("paths"), dict):
        summary["path_count"] = len(payload["paths"])
    if isinstance(payload.get("bindings"), dict):
        summary["binding_count"] = len(payload["bindings"])
    if isinstance(payload.get("features"), dict):
        summary["features"] = payload["features"]
    if isinstance(payload.get("profile"), dict):
        profile = payload["profile"]
        summary["profile"] = {
            "agent_id": profile.get("agent_id"),
            "agent_name": profile.get("agent_name"),
            "level": profile.get("level"),
            "points": profile.get("points"),
        }
    if isinstance(payload.get("summary"), dict):
        summary["space_summary"] = payload["summary"]
    if "unread_count" in payload:
        summary["unread_count"] = payload.get("unread_count")
        summary["has_high_priority"] = payload.get("has_high_priority")
        summary["top_type"] = payload.get("top_type")
    if isinstance(payload.get("messages"), list):
        summary["message_count"] = len(payload["messages"])
        summary["message_types"] = [
            msg.get("type") for msg in payload["messages"][:5] if isinstance(msg, dict)
        ]
    if isinstance(payload.get("rooms"), list):
        summary["room_count"] = len(payload["rooms"])
        summary["room_ids"] = [
            room.get("room_id") for room in payload["rooms"][:10] if isinstance(room, dict)
        ]
    return summary


def _parse_cursor_sdk_stdout_json(stdout_raw: bytes) -> dict[str, Any] | None:
    """Return the last JSON object on stdout that looks like cursor_sdk_provider output."""
    text = stdout_raw.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    for line in reversed(text.splitlines()):
        line_stripped = line.strip()
        if not line_stripped or not line_stripped.startswith("{"):
            continue
        try:
            parsed = json.loads(line_stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and "ok" in parsed:
            return parsed
    return None


def run_cursor_sdk_smoke_stdio(
    *,
    prompt: str,
    model: str,
    cognition_timeout: float,
) -> tuple[int | None, str]:
    """Run ``cursor_sdk_provider.mjs`` once; return exit code hint (None=ok) plus detail."""
    stdin_text = prompt if prompt.endswith("\n") else prompt + "\n"
    try:
        proc = subprocess.run(
            [
                "node",
                str(AGENT_ROOT / "cursor_sdk_provider.mjs"),
                "--model",
                model,
                "--cwd",
                str(PROJECT_ROOT),
            ],
            cwd=str(PROJECT_ROOT),
            input=stdin_text.encode("utf-8"),
            capture_output=True,
            text=False,
            timeout=cognition_timeout,
            env=os.environ,
        )
    except subprocess.TimeoutExpired:
        return 1, "cursor_sdk_probe_timeout"

    stdout_b = proc.stdout or b""
    stderr_b = proc.stderr or b""
    payload = _parse_cursor_sdk_stdout_json(stdout_b)

    if payload is not None:
        if payload.get("ok") is True:
            try:
                interpret_cursor_sdk_subprocess(stdout_b, stderr_b, proc.returncode or 0)
            except RuntimeError as exc:
                return 1, str(exc)
            return None, ""

        code = payload.get("code")
        hint = str(payload.get("error") or "cursor sdk provider failed").strip()
        sdk_msg = str(payload.get("sdk_message") or "").strip()
        if sdk_msg and sdk_msg not in hint:
            hint = f"{hint} ({sdk_msg})".strip()

        if code == "unauthenticated":
            return 2, hint or "unauthenticated"
        code_s = code if isinstance(code, str) else str(code or "cursor_sdk_error")
        hint = (f"[{code_s}] " + hint).strip()
        # Common outages: clearer than a nested JSON string in parent output.
        if "network request failed" in hint.lower():
            hint += " — check VPN/proxy/firewall/DNS"
        return 1, hint

    try:
        interpret_cursor_sdk_subprocess(stdout_b, stderr_b, proc.returncode or 0)
        return None, ""
    except RuntimeError as exc:
        return 1, str(exc)


def interpret_cursor_sdk_subprocess(stdout: bytes, stderr: bytes, returncode: int) -> str:
    """Interpret node cursor_sdk_provider output; raises RuntimeError on failure."""
    err_text = stderr.decode("utf-8", errors="replace").strip()
    payload = _parse_cursor_sdk_stdout_json(stdout)
    if payload is not None:
        if payload.get("ok") is True:
            answer = str(payload.get("text") or "").strip()
            if not answer:
                raise RuntimeError("cursor sdk provider returned ok but empty text")
            return answer
        msg = str(payload.get("error") or "cursor sdk provider failed")
        code = payload.get("code")
        if code == "unauthenticated":
            raise RuntimeError(msg)
        raise RuntimeError(msg)
    raw_out = stdout.decode("utf-8", errors="replace").strip()
    if returncode != 0:
        raise RuntimeError(
            err_text
            or raw_out
            or f"cursor sdk provider exited with code {returncode} and no structured output",
        )
    raise RuntimeError(raw_out or "cursor sdk provider returned no parseable JSON")


class JsonlLogger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: str, **fields: Any) -> None:
        payload = {"ts": time.time(), "event": event, **fields}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def read_jsonl_tail(path: Path, limit: int = 100) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            rows.append({"event": "invalid_log_line", "raw": line})
    return rows


def filter_frame_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    frame_names = {
        "connected",
        "auth_ok",
        "joined",
        "topics_perceived",
        "thinking",
        "reply_dispatched",
        "message_seen",
        "topics_consumed",
        "ws_event",
        "ws_error",
        "superseded",
        "cognition_error",
        "cognition_preflight",
        "durable_surfaces_refreshed",
        "durable_refresh_error",
        "zenlink_refresh_pulled",
        "refresh_deferred_until_room_joined",
        "zenlink_ws_closed",
        "join_room_sent",
        "ws_precocious_buffered",
    }
    return [event for event in events if event.get("event") in frame_names]


def _debug_dashboard_summary_html(status: dict[str, Any]) -> str:
    phase = html.escape(str(status.get("phase") or "unknown"))
    connected = status.get("connected")
    joined = status.get("joined")
    conn_s = html.escape("是" if connected else "否")
    join_s = html.escape("是" if joined else "否")
    base = status.get("debug_url") or ""
    base_s = html.escape(str(base)[:120]) if base else ""
    err = status.get("last_error")
    err_html = ""
    if isinstance(err, dict) and err:
        et = html.escape(str(err.get("type") or ""))
        msg = html.escape(str(err.get("message") or "")[:320])
        code = err.get("close_code")
        code_name = err.get("close_code_name")
        code_s = ""
        if code is not None:
            code_s = html.escape(str(code))
            if isinstance(code_name, str) and code_name.strip():
                code_s += html.escape(f" ({code_name.strip()})")
        elif isinstance(code_name, str) and code_name.strip():
            code_s = html.escape(code_name.strip())
        err_html = (
            f'<div class="alert" role="status"><strong>last_error</strong> '
            f'<code>{et}</code>'
            + (f' <code>close={code_s}</code>' if code_s else "")
            + f" — {msg}</div>"
        )
    return (
        f'<div class="summary">'
        f"<span><strong>ZenLink WS</strong> 已连接: <code>{conn_s}</code></span> · "
        f"<span>已进房 <code>{join_s}</code></span> · "
        f"<span>phase <code>{phase}</code></span>"
        + (f' · <span class="muted">{base_s}</span>' if base_s else "")
        + f"</div>{err_html}"
    )


def render_debug_dashboard(status: dict[str, Any], events: list[dict[str, Any]], frames: list[dict[str, Any]]) -> str:
    status_json = html.escape(json.dumps(status, ensure_ascii=False, indent=2))
    events_json = html.escape(json.dumps(events[-40:], ensure_ascii=False, indent=2))
    frames_json = html.escape(json.dumps(frames[-40:], ensure_ascii=False, indent=2))
    phase = html.escape(str(status.get("phase") or "unknown"))
    pending = html.escape(str(status.get("pending_topic_count") or 0))
    room = html.escape(str(status.get("room_name") or status.get("room_id") or ""))
    summary_html = _debug_dashboard_summary_html(status)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Cursor Agent Debug</title>
  <style>
    body {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; margin: 20px; background: #111; color: #eee; }}
    .grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }}
    .card {{ border: 1px solid #444; border-radius: 8px; padding: 12px; background: #1b1b1b; }}
    pre {{ white-space: pre-wrap; word-break: break-word; font-size: 12px; max-height: 70vh; overflow: auto; outline: none; }}
    pre:focus, pre:hover {{ border-color: #8ab4f8; box-shadow: 0 0 0 1px #8ab4f8 inset; }}
    .refresh-status {{ color: #aaa; }}
    .muted {{ color: #888; font-size: 12px; }}
    a {{ color: #8ab4f8; }}
    .summary {{ font-size: 13px; margin: 10px 0 14px; padding: 10px 12px; border: 1px solid #393939; border-radius: 8px; background: #151515; }}
    .alert {{ margin-top: 8px; color: #f5ab9e; font-size: 12px; }}
    details.legend {{ font-size: 12px; color: #aaa; margin: 0 0 14px; max-width: 920px; }}
    details.legend summary {{ cursor: pointer; color: #ccc; }}
    details.legend ul {{ margin: 8px 0 0 18px; padding: 0; }}
  </style>
  <script>
    window.addEventListener("load", () => {{
      let refreshTimer = null;
      let paused = false;
      const status = document.getElementById("refresh-status");

      function setPaused(nextPaused) {{
        paused = nextPaused;
        if (status) {{
          status.textContent = paused
            ? "页面自动刷新已暂停（鼠标或焦点在下方日志区）"
            : "每约 2 秒自动刷新本页";
        }}
        if (!paused) scheduleRefresh();
        if (paused && refreshTimer !== null) {{
          clearTimeout(refreshTimer);
          refreshTimer = null;
        }}
      }}

      function scheduleRefresh() {{
        if (paused || refreshTimer !== null) return;
        refreshTimer = window.setTimeout(() => {{
          refreshTimer = null;
          if (!paused) window.location.reload();
        }}, 2000);
      }}

      document.getElementById("clear-log-btn")?.addEventListener("click", async () => {{
        const btn = document.getElementById("clear-log-btn");
        if (btn) btn.disabled = true;
        try {{
          const res = await fetch("/clear", {{ method: "POST" }});
          if (!res.ok) throw new Error("HTTP " + res.status);
        }} catch (e) {{
          alert("清空失败: " + String(e));
        }} finally {{
          window.location.reload();
        }}
      }});

      function selectionInsideDebugBox() {{
        const selection = window.getSelection();
        if (!selection || selection.isCollapsed || selection.rangeCount === 0) return false;
        const anchor = selection.anchorNode;
        return !!anchor && !!anchor.parentElement?.closest("pre[data-debug-box]");
      }}

      document.querySelectorAll("pre[data-debug-box]").forEach((node) => {{
        node.scrollTop = node.scrollHeight;
        node.addEventListener("pointerenter", () => setPaused(true));
        node.addEventListener("pointerleave", () => setPaused(selectionInsideDebugBox()));
        node.addEventListener("focusin", () => setPaused(true));
        node.addEventListener("focusout", () => setPaused(selectionInsideDebugBox()));
      }});
      document.addEventListener("selectionchange", () => setPaused(selectionInsideDebugBox()));
      scheduleRefresh();
    }});
  </script>
</head>
<body>
  <h1>Cursor Agent Debug</h1>
  {summary_html}
  <details class="legend">
    <summary>术语说明（避免与本页「刷新」混淆）</summary>
    <ul>
      <li><strong>每约 2 秒自动刷新本页</strong>：只重新加载浏览器里的这份调试 HTML，<em>不会</em>向 ZenLink 发业务请求，也<em>不会</em>触发服务端给你的 agent 推送。</li>
      <li><strong>Events</strong>：来自本地 <code>events.jsonl</code> 的最近条目；其中的 <code>msgbox_notify</code> 是 <strong>ZenLink 经 WebSocket 推过来的信箱摘要</strong>，通常与用户是否打开本页无关。</li>
      <li><strong>Frames</strong>：过滤后的高信号事件（含 join、感知、错误等）。</li>
      <li><strong>refresh_deferred_until_room_joined</strong>：本地策略日志——进房前暂不去 HTTP 拉 msgbox，优先把 <code>room_joined</code> 收完，不是「有人点了刷新」。</li>
    </ul>
  </details>
  <p>phase={phase} room={room} pending={pending} | <span id="refresh-status" class="refresh-status">每约 2 秒自动刷新本页</span> | <a href="/status">status</a> <a href="/events">events</a> <a href="/frames">frames</a> | <button type="button" id="clear-log-btn">清空日志</button> <span class="muted">(truncate events.jsonl)</span></p>
  <div class="grid">
    <section class="card"><h2>Status</h2><pre data-debug-box tabindex="0">{status_json}</pre></section>
    <section class="card"><h2>Events</h2><pre data-debug-box tabindex="0">{events_json}</pre></section>
    <section class="card"><h2>Frames</h2><pre data-debug-box tabindex="0">{frames_json}</pre></section>
  </div>
</body>
</html>
"""


class CursorAgentDaemon:
    def __init__(
        self,
        *,
        paths: RuntimePaths,
        base_url: str,
        agent_id: str,
        token: str,
        room_id: str,
        reconnect: bool,
        cognition_provider: str,
        auto_reply: bool,
        cursor_sdk_model: str,
        cognition_timeout: float,
        debug_host: str,
        debug_port: int | None,
    ) -> None:
        self.paths = paths
        self.base_url = base_url.rstrip("/")
        self.agent_id = agent_id
        self.token = token
        spec = (room_id or OWN_ROOM_ROOM_ID).strip()
        if not spec:
            spec = OWN_ROOM_ROOM_ID
        self._room_spec = spec
        _own = spec.lower() == OWN_ROOM_ROOM_ID
        initial_room = "" if _own else spec
        self.room_id = initial_room
        self.reconnect = reconnect
        self.cognition_provider = cognition_provider
        self.cursor_sdk_model = cursor_sdk_model
        self.cognition_timeout = cognition_timeout
        self.debug_host = debug_host
        self.debug_port = debug_port
        self.state = AgentState(
            pid=os.getpid(),
            agent_id=agent_id,
            room_id=initial_room,
            cognition_provider=cognition_provider,
            auto_reply=auto_reply,
            debug_url=f"http://{debug_host}:{debug_port}/" if debug_port else None,
        )
        self.log = JsonlLogger(paths.log_file)
        self.stop_event = asyncio.Event()
        self.command_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._auto_reply_topic_ids: set[str] = set()
        # Perception frames that want HTTP refresh — defer until room_joined so the recv loop
        # keeps draining WS (room_joined / errors) instead of blocking on outbound HTTP first.
        self._deferred_ws_refreshes: list[dict[str, Any]] = []
        self._precocious_ws_frames: deque[dict[str, Any]] = deque()
        self._active_ws: Any | None = None

    def _write_status(self) -> None:
        self.state.updated_at = time.time()
        self.paths.status_file.write_text(
            json.dumps(self.state.snapshot(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _set_phase(self, phase: str, **fields: Any) -> None:
        self.state.phase = phase
        for key, value in fields.items():
            if hasattr(self.state, key):
                setattr(self.state, key, value)
        self._write_status()
        self.log.write(phase, **fields)

    async def _send_json(self, ws: Any, payload: dict[str, Any]) -> None:
        await ws.send(json.dumps(payload, ensure_ascii=False))

    async def _recv_json(self, ws: Any, timeout: float | None = None) -> dict[str, Any]:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout) if timeout else await ws.recv()
        return json.loads(raw)

    async def _recv_json_buffered(self, ws: Any, timeout: float | None = None) -> dict[str, Any]:
        if self._precocious_ws_frames:
            return self._precocious_ws_frames.popleft()
        return await self._recv_json(ws, timeout=timeout)

    async def _drain_ws_keepalive_while_idle(self, ws: Any) -> None:
        """Drain WS while doing slow HTTP elsewhere so protocol pings / pushed frames are handled."""
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=0.001)
            except asyncio.TimeoutError:
                break
            except Exception as exc:
                self.log.write("ws_drain_recv_failed", error=str(exc)[:300])
                break
            try:
                frame = json.loads(raw)
            except json.JSONDecodeError:
                continue
            ft = frame.get("type")
            if ft == "ping":
                await self._send_json(ws, {"type": "pong"})
                continue
            self._precocious_ws_frames.append(frame)
            self.log.write("ws_precocious_buffered", type=ft)

    def _agent_headers(self) -> dict[str, str]:
        return {"X-Agent-Id": self.agent_id, "X-Agent-Token": self.token}

    def _use_own_room_mode(self) -> bool:
        return self._room_spec.strip().lower() == OWN_ROOM_ROOM_ID

    def _should_defer_refresh_until_room_joined(self, frame: dict[str, Any]) -> bool:
        if self.state.joined:
            return False
        ft = str(frame.get("type") or "")
        if ft == "room_joined":
            return False
        return should_pull_durable_refresh(frame)

    async def _fetch_space_self_body(self) -> dict[str, Any] | None:
        status, payload, content_type = await asyncio.to_thread(
            _json_http_get,
            base_url=self.base_url,
            path="/v2/agent/space-self?limit=10",
            headers=self._agent_headers(),
            timeout=20,
        )
        if 200 <= status < 300 and isinstance(payload, dict):
            return payload
        self.log.write("space_self_fetch_failed", status=status, content_type=content_type)
        return None

    @staticmethod
    def _first_created_room_id(space_self: dict[str, Any]) -> str | None:
        rows = space_self.get("recent_created_rooms")
        if not isinstance(rows, list) or not rows:
            return None
        row0 = rows[0]
        if not isinstance(row0, dict):
            return None
        rid = row0.get("room_id")
        if isinstance(rid, str) and rid.strip():
            return rid.strip()
        return None

    @staticmethod
    def _agent_display_name(auth_ok: dict[str, Any], *, fallback_agent_id: str) -> str:
        prof = auth_ok.get("my_profile")
        if isinstance(prof, dict):
            name = str(prof.get("agent_name") or "").strip()
            if name:
                return name[:60]
        fb = fallback_agent_id.strip()
        return fb[-16:] if len(fb) > 16 else fb

    async def _create_room_and_wait_id(self, ws: Any, auth_ok: dict[str, Any]) -> str | None:
        display = self._agent_display_name(auth_ok, fallback_agent_id=self.agent_id)
        brief = "Cursor agent 自动创建的工作间（ZenLink「own」房间模式）。"
        rules = "默认测试规则：文明讨论；房间由 Cursor agent 本地守护进程托管。"
        base_name = (f"{display} 的工作间").strip()[:80] or f"ZenLink-{self.agent_id[-8:]}"[:80]

        for attempt in (0, 1):
            name = base_name if attempt == 0 else f"{base_name[:70]}·{attempt}"[:80]
            await self._send_json(
                ws,
                {"type": "create_room", "name": name, "brief": brief[:300], "rules": rules[:2000]},
            )
            deadline = time.monotonic() + 25.0
            while time.monotonic() < deadline:
                try:
                    frame = await self._recv_json_buffered(ws, timeout=3.0)
                except asyncio.TimeoutError:
                    continue
                mt = frame.get("type")
                if mt == "ping":
                    await self._send_json(ws, {"type": "pong"})
                    continue
                if mt == "room_created":
                    rid = frame.get("room_id")
                    if isinstance(rid, str) and rid.strip():
                        route_zenlink_perception_into_state(self.state, frame)
                        await self._maybe_pull_refresh_from_frame(frame)
                        self._queue_perception_attention(frame)
                        self.log.write(
                            "own_room_created_ws",
                            room_id=rid.strip(),
                            name=frame.get("name"),
                        )
                        return rid.strip()
                    self.log.write("own_room_bad_frame", frame_type=mt)
                    return None
                if mt == "error":
                    reason = str(frame.get("reason") or "")
                    if reason == "room_name_taken" and attempt == 0:
                        self.log.write("own_room_name_taken_retry", attempted_name=name)
                        break
                    self.state.last_error = {"type": "create_room_failed", "frame": frame}
                    self._set_phase("own_room_create_failed")
                    return None
                route_zenlink_perception_into_state(self.state, frame)
                await self._maybe_pull_refresh_from_frame(frame)
                self._queue_perception_attention(frame)
        return None

    async def _resolve_own_room_target(self, ws: Any, auth_ok: dict[str, Any]) -> str | None:
        space = await self._fetch_space_self_body()
        await self._drain_ws_keepalive_while_idle(ws)
        if space is not None:
            reused = self._first_created_room_id(space)
            if reused:
                self.log.write("own_room_reusing_recent_created", room_id=reused)
                return reused
        return await self._create_room_and_wait_id(ws, auth_ok)

    async def _pull_durable_surface(self, surface: str, path: str) -> dict[str, Any]:
        status, payload, content_type = await asyncio.to_thread(
            _json_http_get,
            base_url=self.base_url,
            path=path,
            headers=self._agent_headers(),
            timeout=15,
        )
        return summarize_durable_payload(
            surface=surface,
            path=path,
            status=status,
            content_type=content_type,
            payload=payload,
        )

    async def _refresh_durable_surfaces(
        self,
        surfaces: list[tuple[str, str]] | None = None,
        *,
        source: str,
        ws: Any | None = None,
    ) -> dict[str, Any]:
        selected = surfaces or list(DEFAULT_DURABLE_SURFACES)
        refreshed: dict[str, Any] = {}
        errors: list[dict[str, str]] = []
        for surface, path in selected:
            try:
                refreshed[surface] = await self._pull_durable_surface(surface, path)
            except Exception as exc:
                errors.append({
                    "surface": surface,
                    "path": path,
                    "error": type(exc).__name__,
                    "message": str(exc),
                })
            if ws is not None:
                await self._drain_ws_keepalive_while_idle(ws)
        self.state.durable_surfaces.update(refreshed)
        if errors:
            self.state.last_error = {"type": "durable_refresh_error", "errors": errors}
        self._write_status()
        self.log.write(
            "durable_surfaces_refreshed",
            source=source,
            count=len(refreshed),
            surfaces=sorted(refreshed.keys()),
            errors=errors,
        )
        return {"ok": not errors, "refreshed": refreshed, "errors": errors}

    async def _maybe_pull_refresh_from_frame(self, frame: dict[str, Any]) -> None:
        if not should_pull_durable_refresh(frame):
            return
        refresh = frame.get("refresh")
        if not isinstance(refresh, dict):
            return
        path = str(refresh.get("path") or "").strip()
        if not path:
            return
        surface = str(refresh.get("surface") or "").strip() or surface_from_refresh_path(path)
        try:
            await self._refresh_durable_surfaces(
                [(surface, path)],
                source=f"frame:{frame.get('type')}",
                ws=self._active_ws,
            )
            self.log.write(
                "zenlink_refresh_pulled",
                surface=surface,
                path=path,
                frame_type=frame.get("type"),
                perception_kind=frame.get("perception_kind"),
                durability=frame.get("durability"),
            )
        except Exception as exc:
            self.state.last_error = {"type": type(exc).__name__, "message": str(exc)}
            self._set_phase("durable_refresh_error")

    def _queue_perception_attention(self, frame: dict[str, Any]) -> None:
        pk = frame.get("perception_kind")
        raw_anchor = frame.get("anchor")
        has_anchor = isinstance(raw_anchor, dict) and bool(raw_anchor)
        refresh = frame.get("refresh")
        sa = frame.get("suggested_action")
        if not has_anchor and pk is None and refresh is None and sa is None:
            return
        self.state.attention_queue.append(
            {
                "type": frame.get("type"),
                "anchor": frame.get("anchor"),
                "perception_kind": frame.get("perception_kind"),
                "refresh": frame.get("refresh"),
                "attention_level": frame.get("attention_level"),
                "durability": frame.get("durability"),
                "suggested_action": frame.get("suggested_action"),
                "queued_at": time.time(),
            }
        )
        self.state.attention_queue = self.state.attention_queue[-50:]

    async def _generate_reply(self, topics: list[dict[str, Any]]) -> str:
        provider = self.cognition_provider
        if provider == "auto":
            provider = "cursor-sdk"
        self.state.effective_cognition_provider = provider
        if provider == "rules":
            return build_rules_reply(topics, self.state)
        if provider == "cursor-sdk":
            prompt = build_cursor_sdk_prompt(topics, self.state)
            return await self._generate_cursor_sdk_reply(prompt)
        raise RuntimeError(f"unknown cognition provider: {self.cognition_provider}")

    async def _generate_cursor_sdk_reply(self, prompt: str) -> str:
        proc = await asyncio.create_subprocess_exec(
            "node",
            str(AGENT_ROOT / "cursor_sdk_provider.mjs"),
            "--model",
            self.cursor_sdk_model,
            "--cwd",
            str(PROJECT_ROOT),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(prompt.encode("utf-8")),
            timeout=self.cognition_timeout,
        )
        return interpret_cursor_sdk_subprocess(stdout, stderr, proc.returncode or 0)

    def _effective_cognition_for_preflight(self) -> str:
        if self.cognition_provider == "auto":
            return "cursor-sdk"
        return self.cognition_provider

    def _log_cognition_preflight(self) -> None:
        kind = self._effective_cognition_for_preflight()
        if kind != "cursor-sdk":
            return
        if os.environ.get("CURSOR_API_KEY", "").strip():
            self.log.write("cognition_preflight", ok=True, has_api_key=True)
            return
        self.log.write(
            "cognition_preflight",
            ok=False,
            has_api_key=False,
            warning=(
                "CURSOR_API_KEY unset after loading env files: @cursor/sdk will fail "
                "(unauthenticated). Put CURSOR_API_KEY in backend/.cursor-agent.env "
                "(or backend/.env.zenlink-readiness via --env-file), or export it before start. "
                "IDE-only login does not apply to Node."
            ),
        )

    async def _send_reply_and_pull(
        self,
        ws: Any,
        text: str,
        *,
        limit: int | None = None,
        source: str,
    ) -> dict[str, Any]:
        pending_count = len(self.state.pending_topics)
        frames = build_reply_frames(
            text,
            self.room_id,
            pending_count=pending_count,
            limit=limit,
        )
        for frame in frames:
            await self._send_json(ws, frame)
        self.state.last_sent_message = frames[0]["text"]
        self._set_phase("reply_sent")
        self.log.write(
            "reply_dispatched",
            source=source,
            provider=self.state.effective_cognition_provider or self.cognition_provider,
            chars=len(frames[0]["text"]),
            pull_limit=frames[1]["limit"],
            pending_topic_count=pending_count,
        )
        return {
            "ok": True,
            "sent_message": frames[0]["text"],
            "pull_limit": frames[1]["limit"],
            "pending_topic_count": pending_count,
            "source": source,
        }

    async def _maybe_auto_reply(self, ws: Any, topics: list[dict[str, Any]]) -> None:
        if not self.state.auto_reply or not topics:
            return
        topic_ids = {str(topic.get("id") or "") for topic in topics if topic.get("id")}
        signature = "|".join(sorted(topic_ids)) or json.dumps(topic_texts(topics), ensure_ascii=False)
        if signature in self._auto_reply_topic_ids:
            return
        try:
            self._set_phase("thinking")
            answer = await self._generate_reply(topics)
            if answer:
                await self._send_reply_and_pull(ws, answer, source="auto")
                self._auto_reply_topic_ids.add(signature)
        except Exception as exc:
            self.state.last_error = {"type": type(exc).__name__, "message": str(exc)}
            self._set_phase("cognition_error", error=type(exc).__name__, message=str(exc))

    async def _handle_control_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            raw = await asyncio.wait_for(reader.readline(), timeout=5)
            request = json.loads(raw.decode("utf-8"))
            command = request.get("command")
            if command == "status":
                response = {"ok": True, "status": self.state.snapshot()}
            elif command == "refresh":
                response = await self._refresh_durable_surfaces(source="control", ws=self._active_ws)
            elif command == "reply":
                future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
                await self.command_queue.put({
                    "command": "reply",
                    "text": request.get("text") or "",
                    "limit": request.get("limit"),
                    "future": future,
                })
                response = await asyncio.wait_for(future, timeout=10)
            elif command == "stop":
                future = asyncio.get_running_loop().create_future()
                await self.command_queue.put({"command": "stop", "future": future})
                response = await asyncio.wait_for(future, timeout=10)
            else:
                response = {"ok": False, "error": "unknown_command", "command": command}
        except Exception as exc:
            response = {"ok": False, "error": type(exc).__name__, "message": str(exc)}
        writer.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async def _start_control_server(self) -> asyncio.AbstractServer:
        if self.paths.socket_file.exists():
            self.paths.socket_file.unlink()
        server = await asyncio.start_unix_server(
            self._handle_control_client,
            path=str(self.paths.socket_file),
        )
        self.log.write("control_ready", socket=str(self.paths.socket_file))
        return server

    async def _handle_debug_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            raw = await asyncio.wait_for(reader.readline(), timeout=5)
            request_line = raw.decode("utf-8", errors="replace").strip()
            tokens = request_line.split()
            method = (tokens[0].upper() if tokens else "GET")
            raw_path = tokens[1].split("?", 1)[0] if len(tokens) > 1 else "/"
            normalized = "/" + raw_path.lstrip("/") if raw_path.lstrip("/") else "/"
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=5)
                if line in (b"\r\n", b"\n", b""):
                    break

            if method == "POST" and normalized == "/clear":
                self.paths.log_file.parent.mkdir(parents=True, exist_ok=True)
                self.paths.log_file.write_text("", encoding="utf-8")
                self.log.write("debug_cleared", source="dashboard_http")
                body_obj: dict[str, Any] = {"ok": True, "cleared": True, "path": str(self.paths.log_file.resolve())}
                body = json.dumps(body_obj, ensure_ascii=False, indent=2)
                payload = body.encode("utf-8")
                writer.write(
                    b"HTTP/1.1 200 OK\r\n"
                    + b"Content-Type: application/json; charset=utf-8\r\n"
                    + f"Content-Length: {len(payload)}\r\n".encode("utf-8")
                    + b"Cache-Control: no-store\r\n"
                    + b"Connection: close\r\n\r\n"
                    + payload
                )
                await writer.drain()
                writer.close()
                await writer.wait_closed()
                return

            events = await asyncio.to_thread(read_jsonl_tail, self.paths.log_file, 200)
            frames = filter_frame_events(events)
            status = self.state.snapshot()
            if normalized == "/status":
                body = json.dumps(status, ensure_ascii=False, indent=2)
                content_type = "application/json; charset=utf-8"
            elif normalized == "/events":
                body = json.dumps(events, ensure_ascii=False, indent=2)
                content_type = "application/json; charset=utf-8"
            elif normalized == "/frames":
                body = json.dumps(frames, ensure_ascii=False, indent=2)
                content_type = "application/json; charset=utf-8"
            else:
                body = await asyncio.to_thread(render_debug_dashboard, status, events, frames)
                content_type = "text/html; charset=utf-8"
            payload = body.encode("utf-8")
            writer.write(
                b"HTTP/1.1 200 OK\r\n"
                + f"Content-Type: {content_type}\r\n".encode("utf-8")
                + f"Content-Length: {len(payload)}\r\n".encode("utf-8")
                + b"Cache-Control: no-store\r\n"
                + b"Connection: close\r\n\r\n"
                + payload
            )
        except Exception as exc:
            body = json.dumps({"ok": False, "error": type(exc).__name__, "message": str(exc)})
            payload = body.encode("utf-8")
            writer.write(
                b"HTTP/1.1 500 Internal Server Error\r\n"
                + b"Content-Type: application/json; charset=utf-8\r\n"
                + f"Content-Length: {len(payload)}\r\n".encode("utf-8")
                + b"Connection: close\r\n\r\n"
                + payload
            )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async def _start_debug_server(self) -> asyncio.AbstractServer | None:
        if not self.debug_port:
            return None
        server = await asyncio.start_server(
            self._handle_debug_client,
            host=self.debug_host,
            port=self.debug_port,
        )
        self.log.write("debug_ready", url=f"http://{self.debug_host}:{self.debug_port}/")
        return server

    async def _handle_ws_frame(self, ws: Any, frame: dict[str, Any]) -> bool:
        keep_running = await self._record_ws_frame(frame)
        if keep_running and frame.get("type") == "topic_suggestions_pending":
            await self._maybe_auto_reply(ws, self.state.pending_topics)
        return keep_running

    async def _record_ws_frame(self, frame: dict[str, Any]) -> bool:
        frame_type = frame.get("type")
        if frame_type == "ping":
            return True
        route_zenlink_perception_into_state(self.state, frame)
        self._queue_perception_attention(frame)
        if frame_type == "room_joined":
            self.state.room_name = str(frame.get("name") or "")
            self.state.joined = True
            self.state.room_role = room_role_from_room_joined(frame, agent_id=self.agent_id)
            self._set_phase(
                "joined",
                room_name=self.state.room_name,
                connected=True,
                joined=True,
            )
            flushed = self._deferred_ws_refreshes
            self._deferred_ws_refreshes = []
            for deferred in flushed:
                await self._maybe_pull_refresh_from_frame(deferred)
        elif frame_type == "topic_suggestions_pending":
            topics = merge_pending_topics(frame.get("topics") or [])
            self.state.pending_topics = topics
            self._set_phase("topic_suggestions_pending")
            self.log.write(
                "topics_perceived",
                topic_count=len(topics),
                topics=[{"id": t.get("id"), "text": t.get("text")} for t in topics],
            )
        elif frame_type == "message":
            message = {
                "agent_id": frame.get("agent_id"),
                "agent_name": frame.get("agent_name"),
                "text": frame.get("text"),
                "sent_at": frame.get("sent_at"),
            }
            if str(message.get("text") or "").strip():
                self.state.recent_messages.append(message)
                self.state.recent_messages = self.state.recent_messages[-20:]
            self.log.write(
                "message_seen",
                agent_id=frame.get("agent_id"),
                message_id=frame.get("message_id"),
                text=frame.get("text"),
            )
        elif frame_type == "pull_room_topics_ok":
            self.state.last_consume_result = {
                "room_id": frame.get("room_id"),
                "topic_count": len(frame.get("topics") or []),
            }
            self.state.pending_topics = []
            self._set_phase("topics_consumed")
        elif frame_type == "superseded":
            self.state.superseded = True
            self.state.connected = False
            sc, anchor_id_parts = anchor_scope_and_id(frame)
            self.state.last_error = {
                "type": "superseded",
                "message": frame.get("message"),
                "anchor_scope": sc,
                "anchor_id": anchor_id_parts,
            }
            self._set_phase("superseded")
            return False
        elif frame_type == "error":
            self.state.last_error = {
                "type": "ws_error",
                "reason": frame.get("reason"),
                "detail": frame.get("detail"),
                "retryable": frame.get("retryable"),
                "anchor": frame.get("anchor"),
                "perception_kind": frame.get("perception_kind"),
            }
            self._set_phase("ws_error")
        else:
            self.log.write("ws_event", type=frame_type, frame=frame)
        if self._should_defer_refresh_until_room_joined(frame):
            self._deferred_ws_refreshes.append(frame)
            self.log.write("refresh_deferred_until_room_joined", frame_type=frame_type)
            return True
        await self._maybe_pull_refresh_from_frame(frame)
        return True

    async def _drain_commands(self, ws: Any) -> bool:
        keep_running = True
        while True:
            try:
                command = self.command_queue.get_nowait()
            except asyncio.QueueEmpty:
                return keep_running
            future = command.get("future")
            try:
                name = command.get("command")
                if name == "reply":
                    response = await self._send_reply_and_pull(
                        ws,
                        str(command.get("text") or ""),
                        limit=command.get("limit"),
                        source="manual",
                    )
                elif name == "stop":
                    if self.state.joined:
                        await self._send_json(ws, {"type": "leave_room"})
                    self.stop_event.set()
                    keep_running = False
                    response = {"ok": True, "stopping": True}
                else:
                    response = {"ok": False, "error": "unknown_command"}
            except Exception as exc:
                response = {"ok": False, "error": type(exc).__name__, "message": str(exc)}
            if future is not None and not future.done():
                future.set_result(response)

    async def _run_ws_session(self) -> bool:
        self._deferred_ws_refreshes.clear()
        self._precocious_ws_frames.clear()
        self.state.room_role = ""
        self.state.connection_id = ""
        self.state.site_anchor_id = ""
        self._set_phase("connecting", connected=False, joined=False)
        async with websockets.connect(
            ws_url(self.base_url),
            open_timeout=20,
            close_timeout=5,
            # library defaults keep protocol-level ping/pong active; None disables and can let
            # some proxies or servers RST idle-looking legs during slow outbound HTTP.
            ping_interval=20,
            ping_timeout=60,
        ) as ws:
            self._active_ws = ws
            try:
                self.state.connected = True
                self._set_phase("connected", connected=True)
                await self._send_json(ws, {"type": "auth", "agent_id": self.agent_id, "token": self.token})
                auth = await self._recv_json(ws, timeout=20)
                if auth.get("type") != "auth_ok":
                    self.state.last_error = {"type": "auth_failed", "frame": auth}
                    self._set_phase("auth_failed", connected=False)
                    return False
                self._set_phase("auth_ok")
                route_zenlink_perception_into_state(self.state, auth)
                self._queue_perception_attention(auth)
                await self._refresh_durable_surfaces(source="auth_ok", ws=ws)
                if self._use_own_room_mode():
                    resolved = await self._resolve_own_room_target(ws, auth)
                    if not resolved:
                        self.state.last_error = self.state.last_error or {
                            "type": "own_room_unresolved",
                            "message": "could not reuse or create owned room",
                        }
                        self._set_phase("own_room_failed", connected=False)
                        return False
                    self.room_id = resolved
                    self.state.room_id = resolved
                    self._write_status()
                    self.log.write("own_room_resolved", room_id=resolved)

                await self._send_json(ws, {"type": "join_room", "room_id": self.room_id})
                self.log.write("join_room_sent", room_id=self.room_id)

                last_ping = time.monotonic()
                while not self.stop_event.is_set():
                    if not await self._drain_commands(ws):
                        break
                    try:
                        frame = await self._recv_json_buffered(ws, timeout=1)
                    except asyncio.TimeoutError:
                        if time.monotonic() - last_ping >= 20:
                            await self._send_json(ws, {"type": "ping"})
                            last_ping = time.monotonic()
                        continue
                    if frame.get("type") == "ping":
                        await self._send_json(ws, {"type": "pong"})
                        continue
                    if not await self._handle_ws_frame(ws, frame):
                        return False
            finally:
                self._active_ws = None
        self.state.connected = False
        self.state.joined = False
        self._set_phase("stopped" if self.stop_event.is_set() else "disconnected")
        return not self.stop_event.is_set()

    async def run(self) -> int:
        self.paths.root.mkdir(parents=True, exist_ok=True)
        self.paths.pid_file.write_text(str(os.getpid()), encoding="utf-8")
        self._write_status()
        server = await self._start_control_server()
        debug_server = await self._start_debug_server()
        self.log.write("daemon_started", pid=os.getpid(), room_id=self.room_id)
        self._log_cognition_preflight()
        try:
            while not self.stop_event.is_set():
                try:
                    should_reconnect = await self._run_ws_session()
                except websockets.exceptions.ConnectionClosed as exc:
                    # Abrupt RST / idle kill / proxy — not the same as a bug in handler code.
                    self.state.connected = False
                    self.state.joined = False
                    reason_s = getattr(exc, "reason", "") or ""
                    code_int, code_name = _connection_closed_code_parts(exc)
                    self.state.last_error = {
                        "type": exc.__class__.__name__,
                        "message": reason_s[:800] if reason_s else "connection closed without close frame",
                        "close_code": code_int,
                        **({"close_code_name": code_name} if code_name else {}),
                    }
                    self.log.write(
                        "zenlink_ws_closed",
                        exc_type=exc.__class__.__name__,
                        close_code=code_int if code_int is not None else getattr(exc, "code", None),
                        reason=(reason_s[:400] if reason_s else None),
                    )
                    should_reconnect = True
                except Exception as exc:
                    self.state.connected = False
                    self.state.joined = False
                    self.state.last_error = {"type": type(exc).__name__, "message": str(exc)}
                    brief = str(exc)[:800]
                    self._set_phase("disconnect_error", exc_type=type(exc).__name__, exc_message=brief)
                    should_reconnect = True
                if self.state.superseded:
                    self.stop_event.set()
                    break
                if not should_reconnect or not self.reconnect:
                    break
                await asyncio.sleep(5)
            self._set_phase("exiting", connected=False, joined=False)
            return 0
        finally:
            server.close()
            await server.wait_closed()
            if debug_server is not None:
                debug_server.close()
                await debug_server.wait_closed()
            if self.paths.socket_file.exists():
                self.paths.socket_file.unlink()
            if self.paths.pid_file.exists() and read_pid(self.paths.pid_file) == os.getpid():
                self.paths.pid_file.unlink()
            self.log.write("daemon_exited", pid=os.getpid())


async def send_control(paths: RuntimePaths, payload: dict[str, Any], timeout: float = 10) -> dict[str, Any]:
    reader, writer = await asyncio.wait_for(
        asyncio.open_unix_connection(str(paths.socket_file)),
        timeout=timeout,
    )
    writer.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
    await writer.drain()
    raw = await asyncio.wait_for(reader.readline(), timeout=timeout)
    writer.close()
    await writer.wait_closed()
    return json.loads(raw.decode("utf-8"))


def stale_pid_status(paths: RuntimePaths) -> dict[str, Any]:
    pid = read_pid(paths.pid_file)
    return {
        "ok": False,
        "running": bool(pid and is_pid_alive(pid)),
        "pid": pid,
        "status_file_exists": paths.status_file.exists(),
        "socket_file_exists": paths.socket_file.exists(),
    }


def cmd_sdk_probe(args: argparse.Namespace) -> int:
    """One-shot Cursor SDK auth check (used by start.sh before ``start``)."""

    def _dump(line: dict[str, Any], *, tb_exc: BaseException | None = None, rc: int) -> int:
        print(json.dumps(line, ensure_ascii=False))
        if tb_exc is not None:
            import traceback as tr

            tr.print_exception(
                type(tb_exc),
                tb_exc,
                tb_exc.__traceback__,
                limit=40,
                file=sys.stderr,
            )
        return rc

    try:
        load_daemon_environment_from_args(args)
        if not provider_uses_cursor_sdk(args.provider):
            return _dump({"ok": True, "skipped": True, "reason": "provider_is_rules"}, tb_exc=None, rc=0)
        try:
            ensure_cursor_sdk_host_preflight(args.provider, skip_sdk_preflight=args.skip_sdk_preflight)
        except RuntimeError as exc:
            return _dump(
                {"ok": False, "error": "cursor_sdk_preflight_failed", "message": str(exc)},
                tb_exc=None,
                rc=1,
            )

        if not os.environ.get("CURSOR_API_KEY", "").strip():
            return _dump(
                {
                    "ok": False,
                    "error": "missing_api_key",
                    "message": "CURSOR_API_KEY is empty after loading env files",
                },
                tb_exc=None,
                rc=5,
            )

        prompt = str(args.probe_prompt or "").strip() or (
            "Reply with exactly the single lowercase word: ok. No punctuation and no other words."
        )
        code, detail = run_cursor_sdk_smoke_stdio(
            prompt=prompt,
            model=args.cursor_sdk_model,
            cognition_timeout=args.probe_timeout,
        )
        if code is None:
            return _dump({"ok": True}, tb_exc=None, rc=0)
        if code == 2:
            return _dump(
                {"ok": False, "error": "unauthenticated", "message": detail},
                tb_exc=None,
                rc=2,
            )

        return _dump(
            {"ok": False, "error": "sdk_probe_failed", "message": detail},
            tb_exc=None,
            rc=1,
        )
    except Exception as exc:  # pragma: no cover - defensive UX for start.sh callers
        return _dump(
            {"ok": False, "error": "internal_error", "message": str(exc)},
            tb_exc=exc,
            rc=1,
        )


def cmd_start(args: argparse.Namespace) -> int:
    paths = runtime_paths(args.runtime_dir)
    paths.root.mkdir(parents=True, exist_ok=True)
    pid = read_pid(paths.pid_file)
    if pid and is_pid_alive(pid):
        print(json.dumps({"ok": False, "error": "already_running", "pid": pid}, ensure_ascii=False))
        return 1
    for stale in (paths.pid_file, paths.socket_file):
        if stale.exists():
            stale.unlink()
    try:
        prepare_daemon_for_launch(args)
    except RuntimeError as exc:
        msg = str(exc)
        if "missing required env" in msg.lower():
            err = "zenlink_env_missing"
        elif "prerequisites missing" in msg or "Cursor/SDK prerequisites" in msg:
            err = "cursor_sdk_preflight_failed"
        else:
            err = "startup_blocked"
        print(
            json.dumps(
                {"ok": False, "error": err, "message": msg},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--runtime-dir",
        str(paths.root),
        "run",
        "--room-id",
        args.room_id,
        "--base-url",
        args.base_url,
        "--env-file",
        args.env_file,
        "--provider",
        args.provider,
        "--cursor-sdk-model",
        args.cursor_sdk_model,
        "--cognition-timeout",
        str(args.cognition_timeout),
    ]
    if args.debug_port:
        command.extend(["--debug-host", args.debug_host, "--debug-port", str(args.debug_port)])
    if not args.reconnect:
        command.append("--no-reconnect")
    if args.skip_sdk_preflight:
        command.append("--skip-sdk-preflight")
    if not args.auto_reply:
        command.append("--no-auto-reply")
    with paths.bootstrap_log_file.open("a", encoding="utf-8") as log_fh:
        subprocess.Popen(
            command,
            cwd=str(PROJECT_ROOT),
            stdin=subprocess.DEVNULL,
            stdout=log_fh,
            stderr=log_fh,
            start_new_session=True,
        )
    deadline = time.time() + args.start_timeout
    while time.time() < deadline:
        pid = read_pid(paths.pid_file)
        if pid and is_pid_alive(pid) and paths.socket_file.exists():
            print(json.dumps({"ok": True, "pid": pid, "runtime_dir": str(paths.root)}, ensure_ascii=False))
            return 0
        time.sleep(0.2)
    stale = stale_pid_status(paths)
    stale["hint"] = "Child did not write pid/socket — see bootstrap_tail (traceback or preflight if child died early)."
    stale["bootstrap_log"] = str(paths.bootstrap_log_file.resolve())
    stale["bootstrap_tail"] = tail_text_file_lines(paths.bootstrap_log_file, max_lines=40)
    print(json.dumps({"ok": False, "error": "start_timeout", **stale}, ensure_ascii=False, indent=2))
    return 1


def cmd_run(args: argparse.Namespace) -> int:
    paths = runtime_paths(args.runtime_dir)
    paths.root.mkdir(parents=True, exist_ok=True)
    pid = read_pid(paths.pid_file)
    if pid and is_pid_alive(pid) and pid != os.getpid():
        print(json.dumps({"ok": False, "error": "already_running", "pid": pid}, ensure_ascii=False))
        return 1
    try:
        prepare_daemon_for_launch(args)
    except RuntimeError as exc:
        msg = str(exc)
        if "missing required env" in msg.lower():
            err = "zenlink_env_missing"
        elif "prerequisites missing" in msg or "Cursor/SDK prerequisites" in msg:
            err = "cursor_sdk_preflight_failed"
        else:
            err = "startup_blocked"
        print(
            json.dumps(
                {"ok": False, "error": err, "message": msg},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    daemon = CursorAgentDaemon(
        paths=paths,
        base_url=args.base_url,
        agent_id=require_env("ZENLINK_AGENT_ID"),
        token=require_env("ZENLINK_TOKEN"),
        room_id=args.room_id,
        reconnect=args.reconnect,
        cognition_provider=args.provider,
        auto_reply=args.auto_reply,
        cursor_sdk_model=args.cursor_sdk_model,
        cognition_timeout=args.cognition_timeout,
        debug_host=args.debug_host,
        debug_port=args.debug_port,
    )

    def _request_stop(*_: object) -> None:
        daemon.stop_event.set()

    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    return asyncio.run(daemon.run())


def cmd_status(args: argparse.Namespace) -> int:
    paths = runtime_paths(args.runtime_dir)
    response: dict[str, Any]
    try:
        response = asyncio.run(send_control(paths, {"command": "status"}, timeout=args.timeout))
    except Exception:
        response = stale_pid_status(paths)
        if paths.status_file.exists():
            try:
                response["last_status"] = json.loads(paths.status_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                response["last_status_error"] = "invalid_json"
    if args.json:
        print(json.dumps(response, ensure_ascii=False, indent=2))
    else:
        status = response.get("status") or response.get("last_status") or {}
        print(f"running={response.get('ok', False)} pid={status.get('pid') or response.get('pid')}")
        print(f"phase={status.get('phase')} room={status.get('room_id')} pending={status.get('pending_topic_count')}")
    return 0 if response.get("ok") else 1


def cmd_refresh(args: argparse.Namespace) -> int:
    paths = runtime_paths(args.runtime_dir)
    response = asyncio.run(send_control(paths, {"command": "refresh"}, timeout=args.timeout))
    print(json.dumps(response, ensure_ascii=False, indent=2))
    return 0 if response.get("ok") else 1


def cmd_reply(args: argparse.Namespace) -> int:
    paths = runtime_paths(args.runtime_dir)
    response = asyncio.run(
        send_control(
            paths,
            {"command": "reply", "text": args.text, "limit": args.limit},
            timeout=args.timeout,
        )
    )
    print(json.dumps(response, ensure_ascii=False, indent=2))
    return 0 if response.get("ok") else 1


def cmd_stop(args: argparse.Namespace) -> int:
    paths = runtime_paths(args.runtime_dir)
    pid = read_pid(paths.pid_file)
    response: dict[str, Any] = {"ok": False, "error": "not_running", "pid": pid}
    if pid and is_pid_alive(pid) and paths.socket_file.exists():
        try:
            response = asyncio.run(send_control(paths, {"command": "stop"}, timeout=args.timeout))
        except Exception as exc:
            response = {"ok": False, "error": type(exc).__name__, "message": str(exc), "pid": pid}
    deadline = time.time() + args.timeout
    while pid and is_pid_alive(pid) and time.time() < deadline:
        time.sleep(0.2)
    if pid and is_pid_alive(pid):
        if args.kill:
            os.kill(pid, signal.SIGTERM)
            time.sleep(1)
            if is_pid_alive(pid):
                os.kill(pid, signal.SIGKILL)
        else:
            response = {"ok": False, "error": "stop_timeout", "pid": pid, "hint": "rerun with --kill"}
            print(json.dumps(response, ensure_ascii=False, indent=2))
            return 1
    for stale in (paths.pid_file, paths.socket_file):
        if stale.exists():
            stale.unlink()
    print(json.dumps({"ok": True, "stop_response": response}, ensure_ascii=False, indent=2))
    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    paths = runtime_paths(args.runtime_dir)
    paths.log_file.parent.mkdir(parents=True, exist_ok=True)
    offset = 0
    if paths.log_file.exists():
        lines = paths.log_file.read_text(encoding="utf-8").splitlines()
        for line in lines[-args.tail :]:
            print(line)
        offset = paths.log_file.stat().st_size
    if not args.follow:
        return 0
    try:
        while True:
            if paths.log_file.exists():
                with paths.log_file.open("r", encoding="utf-8") as fh:
                    fh.seek(offset)
                    chunk = fh.read()
                    offset = fh.tell()
                    if chunk:
                        print(chunk, end="")
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


def _zenlink_agent_http_headers() -> dict[str, str]:
    """Headers for ``/v2/agent/*`` REST calls (same contract as WebSocket agent auth)."""
    return {"X-Agent-Id": require_env("ZENLINK_AGENT_ID"), "X-Agent-Token": require_env("ZENLINK_TOKEN")}


def _merge_message_id_args(message_id: list[str] | None, ids_csv: str | None) -> list[str]:
    out: list[str] = []
    for x in message_id or []:
        s = str(x).strip()
        if s:
            out.append(s)
    if ids_csv and str(ids_csv).strip():
        for part in str(ids_csv).split(","):
            s = part.strip()
            if s:
                out.append(s)
    # de-dupe preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for mid in out:
        if mid not in seen:
            seen.add(mid)
            uniq.append(mid)
    return uniq


def cmd_msgbox_ack(args: argparse.Namespace) -> int:
    """POST ``/v2/agent/msgbox/ack`` — durable inbox read receipt (B01 §14)."""
    load_daemon_environment_from_args(args)
    try:
        headers = _zenlink_agent_http_headers()
    except RuntimeError as exc:
        print(json.dumps({"ok": False, "error": "zenlink_env_missing", "message": str(exc)}, ensure_ascii=False))
        return 1

    message_ids = _merge_message_id_args(getattr(args, "message_id", None), getattr(args, "ids", None))
    if not message_ids:
        print(
            json.dumps(
                {"ok": False, "error": "missing_message_ids", "message": "pass --message-id and/or --ids"},
                ensure_ascii=False,
            )
        )
        return 2

    status, payload, content_type = _json_http_post_json(
        base_url=args.base_url,
        path="/v2/agent/msgbox/ack",
        headers=headers,
        body={"message_ids": message_ids},
        timeout=float(args.timeout),
    )
    if status == 200 and isinstance(payload, dict):
        print(json.dumps({"ok": True, "http_status": status, "response": payload}, ensure_ascii=False))
        return 0
    detail: Any = payload
    if isinstance(payload, dict) and "detail" in payload:
        detail = payload.get("detail")
    print(
        json.dumps(
            {
                "ok": False,
                "http_status": status,
                "content_type": content_type,
                "detail": detail,
            },
            ensure_ascii=False,
        )
    )
    return 1


def cmd_send_dm(args: argparse.Namespace) -> int:
    """POST ``/v2/agent/messages/send`` — REST DM channel (B01 §14)."""
    load_daemon_environment_from_args(args)
    try:
        headers = _zenlink_agent_http_headers()
    except RuntimeError as exc:
        print(json.dumps({"ok": False, "error": "zenlink_env_missing", "message": str(exc)}, ensure_ascii=False))
        return 1

    to_id = str(args.to_agent_id or "").strip()
    body_text = str(args.body or "").strip()
    if not to_id or not body_text:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "invalid_request",
                    "message": "--to-agent-id and --body are required",
                },
                ensure_ascii=False,
            )
        )
        return 2

    req_body: dict[str, Any] = {"to_agent_id": to_id, "body": body_text}
    subj = str(args.subject or "").strip()
    if subj:
        req_body["subject"] = subj

    status, payload, content_type = _json_http_post_json(
        base_url=args.base_url,
        path="/v2/agent/messages/send",
        headers=headers,
        body=req_body,
        timeout=float(args.timeout),
    )
    if status == 201 and isinstance(payload, dict):
        print(json.dumps({"ok": True, "http_status": status, "response": payload}, ensure_ascii=False))
        return 0
    detail: Any = payload
    if isinstance(payload, dict) and "detail" in payload:
        detail = payload.get("detail")
    print(
        json.dumps(
            {
                "ok": False,
                "http_status": status,
                "content_type": content_type,
                "detail": detail,
            },
            ensure_ascii=False,
        )
    )
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Managed Cursor ZenLink test agent.")
    parser.add_argument("--runtime-dir", default=str(DEFAULT_RUNTIME_DIR), help="Runtime directory.")
    sub = parser.add_subparsers(dest="command", required=True)

    def common_connect(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--room-id",
            default=os.environ.get("ZENLINK_ROOM_ID", OWN_ROOM_ROOM_ID),
            metavar="ROOM",
            help=(
                f"A2A social room UUID to join, or `{OWN_ROOM_ROOM_ID}` (default) to use space-self "
                "`recent_created_rooms` or create one via WebSocket."
            ),
        )
        p.add_argument("--base-url", default=os.environ.get("ZENLINK_BASE_URL", DEFAULT_BASE_URL))
        p.add_argument(
            "--env-file",
            default=str(DEFAULT_ENV_FILE),
            help=(
                "Dotenv-style file loaded first (e.g. backend/.env.zenlink-readiness). "
                "Also loads cursor_agent/.cursor-agent.env then backend/.cursor-agent.env "
                "if present. CURSOR_API_KEY is taken from these files when unset or whitespace-only "
                "in the process environment."
            ),
        )
        p.add_argument(
            "--reconnect",
            dest="reconnect",
            action=argparse.BooleanOptionalAction,
            default=True,
            help=(
                "Reconnect ZenLink WebSocket after transient disconnect (default: on keeps debug port alive). "
                "Use --no-reconnect to exit after the first session ends."
            ),
        )
        p.add_argument(
            "--provider",
            choices=("auto", "cursor-sdk", "rules"),
            default=os.environ.get("CURSOR_AGENT_PROVIDER", DEFAULT_COGNITION_PROVIDER),
            help=(
                "auto|cursor-sdk uses @cursor/sdk (Agent.prompt). Provide CURSOR_API_KEY via env, "
                "--env-file, or optional cursor_agent/.cursor-agent.env and backend/.cursor-agent.env "
                "(auto-loaded). IDE-only login does not apply to Node. rules = deterministic smoke replies."
            ),
        )
        p.add_argument(
            "--no-auto-reply",
            action="store_false",
            dest="auto_reply",
            help="Only perceive topics; require manual `reply` commands.",
        )
        p.set_defaults(auto_reply=True)
        p.add_argument(
            "--cursor-sdk-model",
            default=os.environ.get("CURSOR_AGENT_MODEL", DEFAULT_CURSOR_SDK_MODEL),
            help="Cursor SDK model id when provider=cursor-sdk.",
        )
        p.add_argument(
            "--skip-sdk-preflight",
            action="store_true",
            help=(
                "Do not enforce Cursor desktop + Node + @cursor/sdk + CURSOR_API_KEY checks "
                "(for CI or unconventional installs only)."
            ),
        )
        p.add_argument(
            "--cognition-timeout",
            type=float,
            default=float(os.environ.get("CURSOR_AGENT_COGNITION_TIMEOUT", "90")),
            help="Seconds to wait for cognition provider output.",
        )
        p.add_argument(
            "--debug-host",
            default=os.environ.get("CURSOR_AGENT_DEBUG_HOST", DEFAULT_DEBUG_HOST),
            help="Host for optional read-only debug dashboard.",
        )
        p.add_argument(
            "--debug-port",
            type=int,
            default=int(os.environ["CURSOR_AGENT_DEBUG_PORT"]) if os.environ.get("CURSOR_AGENT_DEBUG_PORT") else None,
            help="Port for optional read-only debug dashboard.",
        )

    start = sub.add_parser("start", help="Start daemon in background.")
    common_connect(start)
    start.add_argument("--start-timeout", type=float, default=10)
    start.set_defaults(func=cmd_start)

    sdk_probe = sub.add_parser("sdk-probe", help="Smoke-test Cursor SDK with current CURSOR_API_KEY (stdin prompt).")
    sdk_probe.add_argument(
        "--env-file",
        default=str(DEFAULT_ENV_FILE),
        help="Dotenv loaded first (same as start/run). Optional env files chained after.",
    )
    sdk_probe.add_argument(
        "--provider",
        choices=("auto", "cursor-sdk", "rules"),
        default=os.environ.get("CURSOR_AGENT_PROVIDER", DEFAULT_COGNITION_PROVIDER),
        help="Skipped unless auto or cursor-sdk.",
    )
    sdk_probe.add_argument(
        "--skip-sdk-preflight",
        action="store_true",
        help="Skip Cursor desktop / Node / @cursor/sdk bundle checks.",
    )
    sdk_probe.add_argument(
        "--cursor-sdk-model",
        default=os.environ.get("CURSOR_AGENT_MODEL", DEFAULT_CURSOR_SDK_MODEL),
        help="Model id forwarded to cursor_sdk_provider.mjs.",
    )
    sdk_probe.add_argument(
        "--probe-timeout",
        type=float,
        default=float(os.environ.get("CURSOR_AGENT_SDK_PROBE_TIMEOUT", "45")),
        dest="probe_timeout",
        help="Seconds to wait for the probe Agent.prompt.",
    )
    sdk_probe.add_argument(
        "--probe-prompt",
        default="",
        help="Overrides default one-line stdin prompt.",
    )
    sdk_probe.set_defaults(func=cmd_sdk_probe)

    run = sub.add_parser("run", help="Run daemon in foreground.")
    common_connect(run)
    run.set_defaults(func=cmd_run)

    status = sub.add_parser("status", help="Show daemon status.")
    status.add_argument("--json", action="store_true")
    status.add_argument("--timeout", type=float, default=5)
    status.set_defaults(func=cmd_status)

    refresh = sub.add_parser("refresh", help="Refresh durable ZenLink perception surfaces.")
    refresh.add_argument("--timeout", type=float, default=30)
    refresh.set_defaults(func=cmd_refresh)

    reply = sub.add_parser("reply", help="Send supervised reply and consume pending topics.")
    reply.add_argument("--text", required=True)
    reply.add_argument("--limit", type=int)
    reply.add_argument("--timeout", type=float, default=10)
    reply.set_defaults(func=cmd_reply)

    stop = sub.add_parser("stop", help="Gracefully stop daemon.")
    stop.add_argument("--timeout", type=float, default=10)
    stop.add_argument("--kill", action="store_true", help="Escalate to signals if graceful stop times out.")
    stop.set_defaults(func=cmd_stop)

    logs = sub.add_parser("logs", help="Show daemon JSONL logs.")
    logs.add_argument("--tail", type=int, default=80)
    logs.add_argument("--follow", action="store_true")
    logs.set_defaults(func=cmd_logs)

    def common_rest_agent(p: argparse.ArgumentParser) -> None:
        p.add_argument("--base-url", default=os.environ.get("ZENLINK_BASE_URL", DEFAULT_BASE_URL))
        p.add_argument(
            "--env-file",
            default=str(DEFAULT_ENV_FILE),
            help="Same dotenv chain as start/run (ZENLINK_AGENT_ID, ZENLINK_TOKEN).",
        )
        p.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout seconds.")

    msg_ack = sub.add_parser(
        "msgbox-ack",
        help="POST /v2/agent/msgbox/ack — mark agent inbox messages as read (durable receipt).",
    )
    common_rest_agent(msg_ack)
    msg_ack.add_argument(
        "--message-id",
        action="append",
        dest="message_id",
        metavar="ID",
        help="Message id to ack (repeatable).",
    )
    msg_ack.add_argument(
        "--ids",
        default="",
        help="Comma-separated message ids (merged with --message-id).",
    )
    msg_ack.set_defaults(func=cmd_msgbox_ack)

    send_dm = sub.add_parser(
        "send-dm",
        help="POST /v2/agent/messages/send — send a direct message via REST (msgbox route).",
    )
    common_rest_agent(send_dm)
    send_dm.add_argument("--to-agent-id", required=True, metavar="AGENT", help="Recipient agent id.")
    send_dm.add_argument("--body", required=True, help="DM body (plain text).")
    send_dm.add_argument("--subject", default="", help="Optional subject line.")
    send_dm.set_defaults(func=cmd_send_dm)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
