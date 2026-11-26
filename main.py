"""Точка входа: запускает сервер uvicorn в отдельном потоке и открывает браузер.

Работает и из исходников (python main.py), и из exe (PyInstaller --onefile --noconsole).
В режиме --noconsole sys.stdout/sys.stderr равны None, поэтому все логи пишем в файл
sea_battle.log рядом с exe.
"""
import logging
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

from game.constants import HOST, PORT

URL = f"http://127.0.0.1:{PORT}"


def app_dir() -> Path:
    """Папка, где лежит exe (или main.py при запуске из исходников)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def setup_logging() -> None:
    """Логи в файл рядом с exe. Заодно подменяем None-потоки, иначе uvicorn упадёт."""
    log_path = app_dir() / "sea_battle.log"
    handlers: list[logging.Handler] = [logging.FileHandler(log_path, encoding="utf-8")]
    if sys.stdout is None or sys.stderr is None:
        # --noconsole: перенаправляем stdout/stderr в тот же лог-файл
        stream = open(log_path, "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or stream
        sys.stderr = sys.stderr or stream
    else:
        handlers.append(logging.StreamHandler(sys.stdout))  # обычный запуск из консоли
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


def port_is_busy(port: int) -> bool:
    """True, если на localhost уже кто-то слушает порт (например, вторая копия игры)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0

def message_box(text: str, title: str = "Морской бой") -> None:
    """Окно с сообщением (в режиме --noconsole другого способа показать ошибку нет)."""
    logging.getLogger("seabattle.main").warning(text)
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, title, 0x40)
    except Exception:
        pass

def main() -> None:
    setup_logging()
    log = logging.getLogger("seabattle.main")

    if port_is_busy(PORT):
        log.warning("Порт %s уже занят — открываю браузер для существующего сервера", PORT)
        webbrowser.open(URL)
        return

    # Импортируем после настройки логирования, чтобы поймать все сообщения
    import uvicorn
    from server.app import app, get_lan_ips
    from server.discovery import HostBeacon, find_host

    # Открываем порты брандмауэра (Windows/Linux). Флаги: --no-firewall — пропустить, --open-ports — повторить
    if "--no-firewall" not in sys.argv:
        from server.firewall import ensure_firewall_open
        ensure_firewall_open(force="--open-ports" in sys.argv)

    # Автопоиск: если в сети уже есть хост, открываем его страницу вместо своего сервера.
    # Флаг --host пропускает поиск (принудительно стать хостом), флаг --join только ищет.
    args = sys.argv[1:]
    if "--host" not in args:
        url, blocked = find_host(get_lan_ips(), timeout=4.0)
        if url:
            webbrowser.open(url)
            return
        if blocked:
            message_box("Хост найден в сети, но порт игры (TCP 8000) недоступен.\n"
                        "Скорее всего, на ПК хоста его блокирует брандмауэр: "
                        "запустите там open_port.bat от имени администратора.")
            return
        if "--join" in args:
            message_box("Хост в сети не найден. Запустите игру на ПК хоста и проверьте, "
                        "что оба ПК в одной Wi-Fi сети.")
            return

    config = uvicorn.Config(
        app,                      # передаём объект, а не строку "server.app:app" — так надёжнее в exe
        host=HOST,                # 0.0.0.0 — доступ из локальной сети
        port=PORT,
        log_config=None,          # свой конфиг логов не нужен: пишем через logging в файл
        access_log=True,
        ws="websockets",
        ws_max_size=16 * 1024,    # античит/защита: огромные сообщения не принимаем
    )
    server = uvicorn.Server(config)
    # Кнопка «Выключить сервер» в меню вызывает этот колбэк
    app.state.shutdown_callback = lambda: setattr(server, "should_exit", True)

    thread = threading.Thread(target=server.run, name="uvicorn", daemon=True)
    thread.start()

    # Ждём готовности сервера (до 15 секунд)
    deadline = time.time() + 15
    while not server.started and thread.is_alive() and time.time() < deadline:
        time.sleep(0.1)
    if not server.started:
        log.error("Сервер не стартовал (см. лог выше)")
        return

    for ip in get_lan_ips():
        log.info("Адрес для подключения из локальной сети: http://%s:%s", ip, PORT)
    log.info("Сервер запущен: %s", URL)
    HostBeacon(get_lan_ips).start()
    webbrowser.open(URL)

    try:
        while thread.is_alive():
            thread.join(0.5)
    except KeyboardInterrupt:
        server.should_exit = True
        thread.join(5)


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        # В режиме --noconsole ошибку иначе не видно — пишем рядом с exe
        import traceback
        (app_dir() / "sea_battle_crash.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
