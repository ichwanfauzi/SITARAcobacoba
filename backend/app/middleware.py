"""Request middleware for early evidence upload size enforcement."""

import json

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class _EvidenceRequestTooLarge(Exception):
    pass


class EvidenceUploadSizeLimitMiddleware:
    """Reject oversized evidence requests before or while multipart parsing consumes them."""

    def __init__(self, app: ASGIApp, *, max_request_bytes: int) -> None:
        if max_request_bytes < 1:
            raise ValueError("max_request_bytes must be positive")
        self.app = app
        self.max_request_bytes = max_request_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or not scope.get("path", "").endswith("/evidence/files")
        ):
            await self.app(scope, receive, send)
            return

        content_lengths = [
            value for name, value in scope.get("headers", []) if name.lower() == b"content-length"
        ]
        if content_lengths:
            try:
                declared_length = int(content_lengths[0])
            except ValueError:
                await self._send_too_large(send)
                return
            if (
                declared_length < 0
                or declared_length > self.max_request_bytes
                or any(value != content_lengths[0] for value in content_lengths[1:])
            ):
                await self._send_too_large(send)
                return

        received_bytes = 0

        async def limited_receive() -> Message:
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self.max_request_bytes:
                    raise _EvidenceRequestTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _EvidenceRequestTooLarge:
            await self._send_too_large(send)

    async def _send_too_large(self, send: Send) -> None:
        body = json.dumps({"detail": "Evidence upload request is too large"}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
