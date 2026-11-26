"""Автопоиск хоста в локальной сети по UDP: гостю не нужно вводить IP.

Хост шлёт маяк на CLIENT_PORT и отвечает на запросы, пришедшие на DISCOVERY_PORT.
Гость шлёт запрос, слушает CLIENT_PORT и проверяет, что TCP-порт игры реально открыт.
"""
import json
import logging
import socket
import threading
import time

from game.constants import PORT

DISCOVERY_PORT = 48000   # хост слушает запросы гостей
CLIENT_PORT = 48001      # гость слушает маяки и ответы хоста
MAGIC = "seabattle-v1"

log = logging.getLogger("seabattle.discovery")


def _broadcast_targets(ips) -> set[str]:
    """Широковещательные адреса: общий и по каждой подсети /24 (192.168.1.x -> 192.168.1.255)."""
    targets = {"255.255.255.255"}
    for ip in ips:
        parts = ip.split(".")
        if len(parts) == 4:
            targets.add(".".join(parts[:3] + ["255"]))
    return targets


class HostBeacon:
    """Работает на стороне хоста: маяк + ответы на запросы гостей."""

    def __init__(self, get_ips):
        self.get_ips = get_ips
        self._stop = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._beacon_loop, daemon=True, name="beacon").start()
        threading.Thread(target=self._listen_loop, daemon=True, name="discovery-listen").start()

    def stop(self) -> None:
        self._stop.set()

    def _payload(self) -> bytes:
        return json.dumps({"magic": MAGIC, "port": PORT, "ips": self.get_ips()}).encode()

    def _beacon_loop(self) -> None:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except OSError:
            log.exception("Маяк не запущен")
            return
        with s:
            while not self._stop.is_set():
                for target in _broadcast_targets(self.get_ips()):
                    try:
                        s.sendto(self._payload(), (target, CLIENT_PORT))
                    except OSError:
                        pass          # нет такой сети/интерфейса — пропускаем
                self._stop.wait(2)

    def _listen_loop(self) -> None:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.bind(("", DISCOVERY_PORT))
        except OSError:
            log.exception("Не удалось открыть UDP-порт %s для запросов гостей", DISCOVERY_PORT)
            return
        s.settimeout(1)
        with s:
            while not self._stop.is_set():
                try:
                    data, addr = s.recvfrom(1024)
                except socket.timeout:
                    continue
                except OSError:
                    return
                try:
                    if json.loads(data).get("magic") == MAGIC:
                        s.sendto(self._payload(), (addr[0], CLIENT_PORT))   # ответ напрямую гостю
                        log.info("Гость %s запросил адрес игры", addr[0])
                except (ValueError, AttributeError, OSError):
                    pass


def _tcp_open(ip: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def find_host(own_ips, timeout: float = 4.0) -> tuple[str | None, bool]:
    """Ищет хоста. Возвращает (url, blocked).
    blocked=True: хост слышно по UDP, но TCP-порт игры недоступен (обычно брандмауэр)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.bind(("", CLIENT_PORT))
    except OSError:
        log.warning("UDP-порт %s занят — автопоиск пропущен", CLIENT_PORT)
        return None, False
    own = set(own_ips)
    heard = False
    query = json.dumps({"magic": MAGIC, "query": True}).encode()
    deadline = time.time() + timeout
    next_query = 0.0
    with s:
        s.settimeout(0.4)
        while time.time() < deadline:
            if time.time() >= next_query:
                for target in _broadcast_targets(own):
                    try:
                        s.sendto(query, (target, DISCOVERY_PORT))
                    except OSError:
                        pass
                next_query = time.time() + 1
            try:
                data, addr = s.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                msg = json.loads(data)
                if msg.get("magic") != MAGIC:
                    continue
                port = int(msg.get("port", PORT))
                candidates = [addr[0]] + [ip for ip in msg.get("ips", []) if isinstance(ip, str)]
            except (ValueError, AttributeError, TypeError):
                continue
            for ip in dict.fromkeys(candidates):        # без повторов, порядок сохраняется
                if ip in own:
                    continue                            # это мы сами
                heard = True
                if _tcp_open(ip, port):
                    log.info("Найден хост: %s:%s", ip, port)
                    return f"http://{ip}:{port}", False
    return None, heard
