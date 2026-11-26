"""Автоматическое открытие портов брандмауэра (Windows и Linux).

Порты: TCP 8000 (игра), UDP 48000 и 48001 (автопоиск хоста).
Windows: netsh; без прав администратора один раз показывается окно UAC.
Linux: ufw или firewalld, если они включены; права запрашиваются через pkexec/sudo.
Любые ошибки только пишутся в лог — игра из-за них не падает.
"""
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from game.constants import PORT
from server.discovery import CLIENT_PORT, DISCOVERY_PORT

log = logging.getLogger("seabattle.firewall")

RULES = [("TCP", PORT), ("UDP", DISCOVERY_PORT), ("UDP", CLIENT_PORT)]
NO_WINDOW = 0x08000000   # CREATE_NO_WINDOW: не мигать консолью на Windows


# ============================================================ Windows
def _win_rule_exists(name: str) -> bool:
    r = subprocess.run(["netsh", "advfirewall", "firewall", "show", "rule", f"name={name}"],
                       capture_output=True, creationflags=NO_WINDOW)
    return r.returncode == 0          # 0 — правило найдено (текст ответа зависит от языка Windows)


def _open_windows(force: bool) -> None:
    import ctypes
    names = [f"SeaBattle {proto} {port}" for proto, port in RULES]
    if not force and all(_win_rule_exists(n) for n in names):
        return                        # правила уже есть
    cmds = []
    for (proto, port), name in zip(RULES, names):
        cmds.append(f'netsh advfirewall firewall delete rule name="{name}" >nul 2>&1')
        cmds.append(f'netsh advfirewall firewall add rule name="{name}" dir=in action=allow '
                    f'protocol={proto} localport={port} profile=any')
    line = " & ".join(cmds)

    if ctypes.windll.shell32.IsUserAnAdmin():
        subprocess.run(line, shell=True, capture_output=True, creationflags=NO_WINDOW)
        log.info("Правила брандмауэра созданы")
    else:
        # Запрашиваем права администратора (окно UAC), скрытое окно cmd
        ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", "cmd.exe", f'/c "{line}"', None, 0)
        if ret > 32:
            log.info("Запрошены права администратора для открытия портов")
            time.sleep(1.5)           # даём правилам примениться
        else:
            log.warning("Права администратора не получены — порты не открыты")


# ============================================================ Linux
def _ok(cmd: list[str]) -> bool:
    try:
        return subprocess.run(cmd, capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _linux_script() -> str:
    """Команды для активных брандмауэров (пустая строка — открывать нечего)."""
    parts = []
    if shutil.which("ufw") and _ok(["systemctl", "is-active", "--quiet", "ufw"]):
        parts += [f"ufw allow {port}/{proto.lower()}" for proto, port in RULES]
    if shutil.which("firewall-cmd") and _ok(["firewall-cmd", "--state"]):
        parts += [f"firewall-cmd --permanent --add-port={port}/{proto.lower()}" for proto, port in RULES]
        parts.append("firewall-cmd --reload")
    return " && ".join(parts)


def _open_linux(force: bool) -> None:
    marker = Path.home() / ".config" / "seabattle_firewall_ok"
    if marker.exists() and not force:
        return
    script = _linux_script()
    if not script:
        log.info("Активный брандмауэр (ufw/firewalld) не найден — открывать порты не нужно")
        return
    if os.geteuid() == 0:
        prefix: list[str] = []
    elif shutil.which("pkexec") and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        prefix = ["pkexec"]
    elif shutil.which("sudo") and sys.stdin and sys.stdin.isatty():
        print("Для открытия портов игры нужен пароль sudo:")
        prefix = ["sudo"]
    else:
        log.warning("Откройте порты вручную от root: sh -c '%s'", script)
        return
    r = subprocess.run(prefix + ["sh", "-c", script], timeout=120)
    if r.returncode == 0:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("ok")
        log.info("Порты брандмауэра открыты")
    else:
        log.warning("Не удалось открыть порты (код %s). Вручную: sh -c '%s'", r.returncode, script)


def ensure_firewall_open(force: bool = False) -> None:
    try:
        if sys.platform.startswith("win"):
            _open_windows(force)
        elif sys.platform.startswith("linux"):
            _open_linux(force)
    except Exception:
        log.exception("Не удалось настроить брандмауэр")
