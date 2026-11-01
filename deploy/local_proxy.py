"""Serve the API and the page on one port, the way nginx does in the image.

    python deploy/local_proxy.py --port 7860

Why this exists: Google sign-in only works when the callback and the page
share an origin. The browser is handed ``br_session`` by the API at
``/auth/google/callback``, and Streamlit reads that cookie back on the next
request -- which it can only do if both answer on the same host. Two tunnels
to two ports are two origins, and the cookie is invisible to the second.

So this is the development twin of deploy/nginx.conf: ``/auth/`` goes to the
API, everything else to Streamlit, and the websocket Streamlit runs on is
relayed rather than dropped. Point a tunnel at this one port and sign-in
behaves exactly as it does locally.

Not a general-purpose proxy. It forwards what these two services need and
nothing more.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import httpx
import uvicorn
import websockets
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

API = "http://127.0.0.1:8000"
PAGE = "http://127.0.0.1:8501"

#: Hop-by-hop headers belong to one connection and must not be forwarded.
DROP = {"connection", "keep-alive", "transfer-encoding", "upgrade",
        "proxy-authenticate", "proxy-authorization", "te", "trailer"}

# The long model calls: screening ten papers over two vendors runs past a
# minute, and reading full text longer still.
TIMEOUT = httpx.Timeout(900.0, connect=10.0)

client = httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False)


def _upstream(path: str) -> str:
    return API if path.startswith("/auth") else PAGE


class RawStreamingResponse(StreamingResponse):
    """StreamingResponse that keeps duplicate headers (Set-Cookie)."""

    def __init__(self, *args, raw_headers=None, **kwargs):
        super().__init__(*args, **kwargs)
        if raw_headers is not None:
            self.raw_headers = list(raw_headers)


async def http_proxy(request):
    target = _upstream(request.url.path) + request.url.path
    if request.url.query:
        target += "?" + request.url.query

    headers = [(k, v) for k, v in request.headers.raw
               if k.decode().lower() not in DROP]
    # Tell the app it is behind TLS, so the cookies it sets are marked secure
    # and its redirects come back to the public name, not to localhost.
    forwarded = request.headers.get("x-forwarded-proto", request.url.scheme)
    headers.append((b"x-forwarded-proto", forwarded.encode()))

    req = client.build_request(request.method, target, headers=headers,
                               content=request.stream())
    try:
        upstream = await client.send(req, stream=True)
    except httpx.ConnectError:
        return Response("Upstream service is not running.", status_code=502)

    out = [(k, v) for k, v in upstream.headers.raw
           if k.decode().lower() not in DROP]
    return RawStreamingResponse(
        upstream.aiter_raw(),
        status_code=upstream.status_code,
        raw_headers=out,
        background=BackgroundTask(upstream.aclose),
    )


async def ws_proxy(ws: WebSocket):
    """Relay Streamlit's websocket. Without this the page loads and hangs.

    Three things here are not optional, and each of them cost a take:

    * Connect upstream *before* accepting the browser. Accepting first and
      failing after leaves the browser reconnecting in a loop against a
      socket that closes every time.
    * Echo the negotiated subprotocol. Streamlit offers one on the
      handshake and refuses a connection that comes back without it.
    * Forward the Cookie header. ``st.context.cookies`` is read off this
      handshake, so without it the page never sees ``br_session`` and a
      signed-in reload comes back a guest.
    """
    url = PAGE.replace("http://", "ws://") + ws.url.path
    if ws.url.query:
        url += "?" + ws.url.query

    requested = list(ws.scope.get("subprotocols") or [])
    forward = [(k.decode(), v.decode()) for k, v in ws.scope["headers"]
               if k.decode().lower() in ("cookie", "user-agent")]

    try:
        upstream = await websockets.connect(
            url, additional_headers=forward,
            subprotocols=requested or None, max_size=None, open_timeout=20)
    except Exception as exc:
        print(f"websocket upstream refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        await ws.close(code=1011)
        return

    await ws.accept(subprotocol=upstream.subprotocol)

    async def to_upstream():
        try:
            while True:
                message = await ws.receive()
                if message["type"] == "websocket.disconnect":
                    return
                data = message.get("bytes")
                await upstream.send(data if data is not None else message.get("text", ""))
        except (WebSocketDisconnect, websockets.ConnectionClosed):
            return

    async def to_browser():
        try:
            async for data in upstream:
                if isinstance(data, bytes):
                    await ws.send_bytes(data)
                else:
                    await ws.send_text(data)
        except (WebSocketDisconnect, websockets.ConnectionClosed, RuntimeError):
            return

    tasks = [asyncio.create_task(to_upstream()), asyncio.create_task(to_browser())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        await upstream.close()
        try:
            await ws.close()
        except RuntimeError:
            pass


app = Starlette(routes=[
    WebSocketRoute("/_stcore/stream", ws_proxy),
    WebSocketRoute("/stream", ws_proxy),
    Route("/{path:path}", http_proxy,
          methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]),
])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=7860)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    print(f"one origin on http://{a.host}:{a.port}  (/auth -> {API}, rest -> {PAGE})")
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
