from __future__ import annotations

import json
import urllib.request


def send_text_message(webhook_url: str, text: str, timeout_seconds: int = 5) -> None:
    payload = {"msg_type": "text", "content": {"text": text}}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        webhook_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds):
        return
