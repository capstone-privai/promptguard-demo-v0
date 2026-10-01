from __future__ import annotations

import json
import re
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from promptguard.transport.client import TransportError, post  # noqa: E402


RUNNER = ROOT / "promptguard" / "runner" / "main.py"
RAW_SECRET = re.compile(r"\bPG_FAKE_(?:PASSWORD|TOKEN|API_KEY)_[A-Za-z0-9_-]+\b")


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def main() -> int:
    event = json.load(sys.stdin)
    event_name = event.get("hook_event_name")
    session_id, turn_id = str(event.get("session_id", "")), str(event.get("turn_id", ""))
    if event_name == "UserPromptSubmit":
        try:
            post("/task", {"session_id": session_id, "turn_id": turn_id, "prompt": str(event.get("prompt", ""))})
        except TransportError:
            pass
        return 0
    if event_name == "PreToolUse":
        command = str(event.get("tool_input", {}).get("command", ""))
        if "promptguard/runner/main.py" in command.replace("\\", "/") and "--operation-id" in command:
            return 0
        operation_id = str(uuid.uuid4())
        status = "daemon_unavailable"
        try:
            result = post("/register", {"session_id": session_id, "turn_id": turn_id, "command": command})
            operation_id, status = result["operation_id"], "registered"
        except (TransportError, KeyError):
            pass
        rewritten = f"& {_ps_quote(sys.executable)} {_ps_quote(str(RUNNER))} --operation-id {_ps_quote(operation_id)}; exit $LASTEXITCODE"
        try:
            post("/event", {"event": "pretool_rewrite", "session_id": session_id, "turn_id": turn_id, "operation_id": operation_id, "status": status})
        except TransportError:
            pass
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow", "updatedInput": {"command": rewritten}}}))
        return 0
    if event_name == "PostToolUse":
        command = str(event.get("tool_input", {}).get("command", ""))
        if "promptguard/runner/main.py" not in command.replace("\\", "/"):
            return 0
        response_obj = event.get("tool_response", "")
        response = response_obj if isinstance(response_obj, str) else json.dumps(response_obj, ensure_ascii=False)
        marker_present = bool(RAW_SECRET.search(response))
        valid = "[PROMPTGUARD_RESULT]" in response and not marker_present
        try:
            post("/event", {"event": "posttool_verify", "session_id": session_id, "turn_id": turn_id, "status": "verified" if valid else "blocked", "marker_present": marker_present})
        except TransportError:
            pass
        if not valid:
            print(json.dumps({"decision": "block", "reason": "PromptGuard verification failed. Tool result withheld."}))
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
