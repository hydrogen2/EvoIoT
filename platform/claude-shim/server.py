#!/usr/bin/env python3
"""OpenAI-compatible chat-completions shim backed by the Claude Code CLI.

Runs on the docker HOST (where the `claude` CLI is installed and
authenticated). The workflows container points LiteLLM at it via
LLM_API_BASE=http://host.docker.internal:8787/v1.

Only implements what shared/llm.py needs: POST /v1/chat/completions with
system+user messages, non-streaming, text response. Auth is a static
bearer token (SHIM_TOKEN env) since the port is bound on all interfaces.

Usage:
    SHIM_TOKEN=<secret> python3 server.py
    # optional: SHIM_PORT (default 8787), SHIM_MODEL (default haiku),
    #           SHIM_CLAUDE_BIN (default: claude on PATH)
"""

import json
import os
import subprocess
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("SHIM_PORT", "8787"))
TOKEN = os.environ.get("SHIM_TOKEN", "")
MODEL = os.environ.get("SHIM_MODEL", "haiku")
CLAUDE_BIN = os.environ.get("SHIM_CLAUDE_BIN", "claude")
TIMEOUT_S = int(os.environ.get("SHIM_TIMEOUT_S", "300"))

# Minimal, scrubbed environment for the CLI subprocess: keep auth/config
# discovery (HOME) and PATH, drop any nested-session variables inherited
# from whatever shell started this server.
CLI_ENV = {
    "HOME": os.environ["HOME"],
    "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
    "TERM": "dumb",
}


def call_claude(prompt: str) -> str:
    """Run claude -p and return the result text. Raises on failure."""
    proc = subprocess.run(
        [CLAUDE_BIN, "-p", "--model", MODEL, "--output-format", "json"],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=TIMEOUT_S,
        env=CLI_ENV,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "claude CLI exited %d: %s" % (proc.returncode, (proc.stderr or proc.stdout)[-2000:])
        )
    out = json.loads(proc.stdout)
    if out.get("is_error"):
        raise RuntimeError("claude CLI returned error: %s" % str(out)[:2000])
    return out.get("result", "")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code: int, payload: dict):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print("[shim] %s - %s" % (self.address_string(), fmt % args), flush=True)

    def do_GET(self):
        if self.path in ("/health", "/v1/health"):
            self._send(200, {"status": "ok", "model": MODEL})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path.rstrip("/") not in ("/v1/chat/completions", "/chat/completions"):
            self._send(404, {"error": {"message": "not found", "type": "invalid_request_error"}})
            return

        auth = self.headers.get("Authorization", "")
        if not TOKEN or auth != "Bearer " + TOKEN:
            self._send(401, {"error": {"message": "invalid api key", "type": "auth_error"}})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            req = json.loads(self.rfile.read(length))
            messages = req.get("messages", [])
            # Flatten system + user messages into one prompt; the CLI has no
            # separate system channel in -p mode and the prompts are one-shot.
            parts = []
            for m in messages:
                content = m.get("content", "")
                if isinstance(content, list):  # OpenAI content-parts form
                    content = "".join(p.get("text", "") for p in content)
                parts.append(content)
            prompt = "\n\n".join(p for p in parts if p)

            started = time.time()
            text = call_claude(prompt)
            print("[shim] completed in %.1fs, %d chars" % (time.time() - started, len(text)), flush=True)

            self._send(200, {
                "id": "chatcmpl-" + uuid.uuid4().hex[:24],
                "object": "chat.completion",
                "created": int(time.time()),
                "model": "claude-code/" + MODEL,
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            })
        except Exception as e:  # surface failures as OpenAI-style errors
            print("[shim] ERROR: %s" % e, flush=True)
            self._send(500, {"error": {"message": str(e)[:2000], "type": "server_error"}})


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("SHIM_TOKEN must be set")
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("[shim] listening on :%d, backing model: %s" % (PORT, MODEL), flush=True)
    server.serve_forever()
