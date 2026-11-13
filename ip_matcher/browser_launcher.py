"""Optional isolated browser launcher aligned with the detected IP profile."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .config import BROWSER_PROFILES_DIR


def find_browser_executable() -> tuple[str | None, str | None]:
    """Locate Microsoft Edge or Google Chrome on Windows."""
    candidates = [
        (
            "edge",
            [
                Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
                / "Microsoft/Edge/Application/msedge.exe",
                Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
                / "Microsoft/Edge/Application/msedge.exe",
            ],
        ),
        (
            "chrome",
            [
                Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
                / "Google/Chrome/Application/chrome.exe",
                Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
                / "Google/Chrome/Application/chrome.exe",
                Path(os.environ.get("LocalAppData", ""))
                / "Google/Chrome/Application/chrome.exe",
            ],
        ),
    ]
    for kind, paths in candidates:
        for p in paths:
            if p.exists():
                return kind, str(p)
        exe = shutil.which("msedge" if kind == "edge" else "chrome")
        if exe:
            return kind, exe
    return None, None


def launch_aligned_browser(
    target: dict[str, Any],
    proxy_mode: str = "system",
    custom_proxy_url: str = "",
    start_url: str = "https://whoer.net",
) -> dict[str, Any]:
    """Launch an isolated Edge/Chrome profile configured with matching language & optional proxy."""
    kind, exe_path = find_browser_executable()
    if not exe_path:
        return {
            "ok": False,
            "message": "مرورگر Edge یا Chrome روی سیستم پیدا نشد",
        }

    country_code = str(target.get("country_code") or "default").upper()
    lang = str(target.get("language_tag") or "en-US")
    profile_dir = BROWSER_PROFILES_DIR / f"{kind}_{country_code}"
    profile_dir.mkdir(parents=True, exist_ok=True)

    args = [
        exe_path,
        f"--user-data-dir={profile_dir}",
        f"--lang={lang}",
        f"--accept-lang={lang}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
    ]

    if proxy_mode == "custom" and custom_proxy_url.strip():
        # Chromium --proxy-server expects socks5://host:port or http://host:port
        proxy_arg = custom_proxy_url.strip().replace("socks5h://", "socks5://")
        args.append(f"--proxy-server={proxy_arg}")

    args.append(start_url)

    try:
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {
            "ok": True,
            "browser": kind,
            "profile_dir": str(profile_dir),
            "message": f"مرورگر ایزوله ({kind}) با زبان {lang} اجرا شد",
        }
    except Exception as exc:
        return {"ok": False, "message": str(exc)}
