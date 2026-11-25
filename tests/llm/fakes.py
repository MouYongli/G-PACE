"""Test doubles for llm/: a whitespace token counter and a fake OpenAI-compatible HTTP server."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class WordCounter:
    """Counts whitespace-separated words plus 4 per message (a stand-in chat template)."""

    name = "words"

    def count_text(self, text: str) -> int:
        return len(text.split())

    def count_messages(self, messages) -> int:
        return sum(4 + len(m["content"].split()) for m in messages)


class FakeServer:
    """Serves /v1/chat/completions from a queue of scripted replies.

    Each reply is (status_code, body) with body a dict (sent as JSON) or a str (sent raw).
    Received payloads are kept in `requests`.
    """

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 (http.server API)
                length = int(self.headers["Content-Length"])
                outer.requests.append({"path": self.path,
                                       "auth": self.headers.get("Authorization"),
                                       "body": json.loads(self.rfile.read(length))})
                status, body = outer.replies.pop(0)
                data = body if isinstance(body, str) else json.dumps(body)
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(data.encode("utf-8"))

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/v1"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


def completion(text: str, completion_tokens: int = 3, prompt_tokens: int | None = None,
               cached: int | None = None) -> dict:
    usage = {"completion_tokens": completion_tokens}
    if prompt_tokens is not None:
        usage["prompt_tokens"] = prompt_tokens
    if cached is not None:
        usage["prompt_tokens_details"] = {"cached_tokens": cached}
    return {"choices": [{"message": {"role": "assistant", "content": text}}], "usage": usage}
