#!/usr/bin/env python3
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def load_required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def request_json(method: str, path: str, body: dict[str, Any] | None) -> Any:
    base_url = load_required_env("ADMIN_API_BASE_URL").rstrip("/")
    admin_key = load_required_env("ADMIN_API_KEY")
    url = f"{base_url}{path}"
    payload = None
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url=url,
        data=payload,
        method=method,
        headers={
            "Content-Type": "application/json",
            "X-Admin-Key": admin_key,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {url}: {raw}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error calling {url}: {exc}") from exc


def cmd_list_agents(_: argparse.Namespace) -> None:
    result = request_json("GET", "/v2/admin/agents", None)
    print(json.dumps(result, ensure_ascii=True, indent=2))


def cmd_connection_status(args: argparse.Namespace) -> None:
    result = request_json("GET", f"/v2/admin/agents/{args.agent_id}/connection", None)
    print(json.dumps(result, ensure_ascii=True, indent=2))


def cmd_send_command(args: argparse.Namespace) -> None:
    command_args = {}
    if args.args_json:
        try:
            parsed = json.loads(args.args_json)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"--args-json must be valid JSON object: {exc}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("--args-json must decode to a JSON object")
        command_args = parsed
    body = {
        "command": args.command,
        "args": command_args,
        "timeout_seconds": args.timeout_seconds,
    }
    result = request_json("POST", f"/v2/admin/agents/{args.agent_id}/commands", body)
    print(json.dumps(result, ensure_ascii=True, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="CLI for ZenHeart admin agent control API",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    parser_list = subparsers.add_parser("list-agents", help="List registered agents")
    parser_list.set_defaults(func=cmd_list_agents)

    parser_connection = subparsers.add_parser(
        "connection-status", help="Check if an agent is connected"
    )
    parser_connection.add_argument("agent_id", help="Target agent_id")
    parser_connection.set_defaults(func=cmd_connection_status)

    parser_send = subparsers.add_parser(
        "send-command", help="Send one command to connected agent and wait for result"
    )
    parser_send.add_argument("agent_id", help="Target agent_id")
    parser_send.add_argument("command", help="Command name for the agent")
    parser_send.add_argument(
        "--args-json",
        default="{}",
        help="JSON object passed to command args",
    )
    parser_send.add_argument(
        "--timeout-seconds",
        type=int,
        required=True,
        help="Command timeout in seconds (must match API constraints)",
    )
    parser_send.set_defaults(func=cmd_send_command)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
        return 0
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
