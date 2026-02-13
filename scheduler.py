from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parent


def _python_executable() -> str:
    exe = sys.executable
    if not exe:
        raise RuntimeError("Python executable not found")
    return exe


def _cron_marker() -> str:
    return "# dev-memory:run_daily"


def _cron_command() -> str:
    root = _project_root()
    logs_dir = root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    python = _python_executable()
    run_daily = root / "run_daily.py"
    # run_daily.py is silent and writes logs via logger.py into logs/cron-YYYY-MM-DD.log
    return f"0 6 * * 1-5 {python} {run_daily} {_cron_marker()}"


def _startup_desktop_path() -> Path:
    return Path.home() / ".config" / "autostart" / "dev-memory.desktop"


def install_startup_hook() -> None:
    autostart_dir = _startup_desktop_path().parent
    autostart_dir.mkdir(parents=True, exist_ok=True)

    python = _python_executable()
    script = _project_root() / "run_on_startup.py"
    content = "\n".join(
        [
            "[Desktop Entry]",
            "Type=Application",
            f"Exec={python} {script}",
            "Hidden=false",
            "NoDisplay=false",
            "X-GNOME-Autostart-enabled=true",
            "Name=Dev Memory Startup",
            "",
        ]
    )

    path = _startup_desktop_path()
    if path.exists() and path.read_text(encoding="utf-8") == content:
        print("Startup hook already installed")
        return

    path.write_text(content, encoding="utf-8")
    print("Startup hook installed")


def remove_startup_hook() -> None:
    path = _startup_desktop_path()
    if not path.exists():
        print("Startup hook not found")
        return
    path.unlink()
    print("Startup hook removed")


def _read_crontab() -> str:
    if shutil.which("crontab") is None:
        raise RuntimeError("crontab command not found")

    proc = subprocess.run(
        ["crontab", "-l"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        # when no crontab exists, many systems return exit code 1
        return ""
    return proc.stdout or ""


def _write_crontab(content: str) -> None:
    if shutil.which("crontab") is None:
        raise RuntimeError("crontab command not found")

    subprocess.run(
        ["crontab", "-"],
        input=content,
        text=True,
        check=True,
    )


def install_cron_job() -> None:
    existing = _read_crontab().splitlines()
    marker = _cron_marker()
    if any(marker in line for line in existing):
        print("Cron job already installed")
        return

    lines = [line.rstrip() for line in existing if line.strip()]
    lines.append(_cron_command())
    _write_crontab("\n".join(lines) + "\n")
    print("Cron job installed")


def remove_cron_job() -> None:
    existing = _read_crontab().splitlines()
    marker = _cron_marker()
    filtered = [line for line in existing if marker not in line]

    if len(filtered) == len(existing):
        print("Cron job not found")
        return

    # Keep file ending newline
    content = "\n".join([line.rstrip() for line in filtered if line.strip()])
    if content:
        content += "\n"
    _write_crontab(content)
    print("Cron job removed")
