"""FastAPI-приложение: WebSocket /ws, мини-API и раздача статики фронта (папка web/)."""
import logging
import mimetypes
import socket
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from game.constants import PORT
from server.manager import LobbyManager, Session

log = logging.getLogger("seabattle.app")

# На Windows реестр иногда отдаёт .js как text/plain — браузер тогда отказывается грузить ES-модули
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")


def web_dir() -> Path:
    """Папка web/: внутри exe (PyInstaller распаковывает в sys._MEIPASS) или рядом с проектом."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "web"


def get_lan_ips() -> list[str]:
    """IP-адреса компьютера в локальной сети. Адреса Wi-Fi/Ethernet (частные) идут первыми,
    VPN-адреса (Radmin, Hamachi и т.п.) — в конце."""
    import ipaddress
    found: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))     # реальный пакет не отправляется
            found.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        found += socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        pass

    def rank(ip: str) -> int:
        return 0 if ipaddress.ip_address(ip).is_private else 1

    ips = [ip for ip in dict.fromkeys(found)
           if not ip.startswith("127.") and not ipaddress.ip_address(ip).is_link_local]
    return sorted(ips, key=rank)      # sorted стабильна: порядок внутри групп сохраняется


app = FastAPI(title="Морской бой 100×100")
manager = LobbyManager()


@app.get("/api/info")
async def info() -> dict:
    return {"port": PORT, "ips": get_lan_ips()}


@app.post("/api/shutdown")
async def shutdown(request: Request) -> dict:
    """Остановить сервер. Разрешено только с самого компьютера."""
    if not request.client or request.client.host not in ("127.0.0.1", "::1"):
        raise HTTPException(status_code=403, detail="Только с локального компьютера")
    callback = getattr(app.state, "shutdown_callback", None)
    if callback:
        callback()
    return {"ok": True}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    session = Session(ws)
    try:
        while True:
            raw = await ws.receive_text()
            await manager.handle_raw(session, raw)
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("Ошибка WebSocket")
    finally:
        await manager.disconnect(session)


# Статика монтируется ПОСЛЕДНЕЙ, иначе "/" перехватит остальные маршруты
app.mount("/", StaticFiles(directory=str(web_dir()), html=True), name="web")
