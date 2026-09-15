import os
import aiohttp
from aiohttp import web, ClientSession, TCPConnector

TELEGRAM_API = "https://api.telegram.org"
PORT = int(os.environ.get("PORT", 8080))

# هدرهایی که نباید فوروارد شوند
HOP_HEADERS = {
    "host", "connection", "keep-alive", "proxy-authenticate",
    "proxy-authorization", "te", "trailers",
    "transfer-encoding", "upgrade", "content-length",
}

# کلاینت سراسری (Connection Pooling)
session: ClientSession = None


async def init_session(app: web.Application):
    global session
    connector = TCPConnector(
        limit=200,              # حداکثر اتصال همزمان
        limit_per_host=200,
        ttl_dns_cache=300,      # کش DNS برای سرعت
        enable_cleanup_closed=True,
    )
    timeout = aiohttp.ClientTimeout(total=120, connect=10)
    session = ClientSession(connector=connector, timeout=timeout)


async def close_session(app: web.Application):
    await session.close()


async def proxy(request: web.Request) -> web.StreamResponse:
    # ساخت URL مقصد
    path = request.match_info["path"]
    url = f"{TELEGRAM_API}/{path}"
    if request.query_string:
        url += f"?{request.query_string}"

    # هدرها
    headers = {k: v for k, v in request.headers.items()
               if k.lower() not in HOP_HEADERS}

    body = await request.read()

    try:
        async with session.request(
            method=request.method,
            url=url,
            headers=headers,
            data=body if body else None,
            allow_redirects=True,
        ) as resp:
            # پاسخ استریم (برای فایل‌های حجیم عالی است)
            out = web.StreamResponse(
                status=resp.status,
                headers={
                    k: v for k, v in resp.headers.items()
                    if k.lower() not in HOP_HEADERS and k.lower() != "content-encoding"
                },
            )
            await out.prepare(request)
            async for chunk in resp.content.iter_chunked(64 * 1024):
                await out.write(chunk)
            await out.write_eof()
            return out

    except aiohttp.ClientError as e:
        return web.json_response(
            {"ok": False, "error_code": 502, "description": f"Proxy error: {e}"},
            status=502,
        )
    except Exception as e:
        return web.json_response(
            {"ok": False, "error_code": 500, "description": str(e)},
            status=500,
        )


async def health(_):
    return web.json_response({"status": "ok"})


app = web.Application(client_max_size=100 * 1024 * 1024)  # 100MB
app.on_startup.append(init_session)
app.on_cleanup.append(close_session)
app.router.add_route("*", "/health", health)
app.router.add_route("*", "/{path:.*}", proxy)


if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=PORT, access_log=None)
