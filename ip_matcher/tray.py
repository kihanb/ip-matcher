"""Windows System Tray controller with dynamic alignment-status shield icon."""

from __future__ import annotations

import threading
from typing import Callable

from PIL import Image, ImageDraw

try:
    import pystray
except Exception:  # pragma: no cover - optional fallback
    pystray = None  # type: ignore[assignment]


STATUS_COLORS = {
    "safe": (16, 185, 129),      # Emerald
    "warning": (245, 158, 11),   # Amber
    "critical": (239, 68, 68),   # Red
    "unknown": (100, 116, 139),  # Slate
}


def create_shield_icon(status: str = "unknown", size: int = 64) -> Image.Image:
    """Draw a crisp shield icon colored by current alignment status."""
    color = STATUS_COLORS.get(status, STATUS_COLORS["unknown"])
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Outer shield polygon
    pts = [
        (size * 0.50, size * 0.06),
        (size * 0.88, size * 0.20),
        (size * 0.84, size * 0.62),
        (size * 0.50, size * 0.94),
        (size * 0.16, size * 0.62),
        (size * 0.12, size * 0.20),
    ]
    draw.polygon(pts, fill=color, outline=(255, 255, 255, 220))

    # Inner checkmark / dot accent
    draw.line(
        [
            (size * 0.34, size * 0.50),
            (size * 0.46, size * 0.63),
            (size * 0.68, size * 0.36),
        ],
        fill=(255, 255, 255, 245),
        width=max(3, size // 12),
    )
    return img


class TrayController:
    """Manages the Windows system tray icon and quick actions."""

    def __init__(
        self,
        on_show: Callable[[], None],
        on_sync_now: Callable[[], None],
        on_restore_prev: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        self._on_show = on_show
        self._on_sync_now = on_sync_now
        self._on_restore_prev = on_restore_prev
        self._on_quit = on_quit
        self._icon: Any = None
        self._thread: threading.Thread | None = None

    @property
    def available(self) -> bool:
        return pystray is not None

    def start(self) -> None:
        if not pystray or self._icon is not None:
            return
        menu = pystray.Menu(
            pystray.MenuItem("باز کردن IP Matcher", lambda *_: self._on_show(), default=True),
            pystray.MenuItem("بررسی و همگام‌سازی فوری", lambda *_: self._on_sync_now()),
            pystray.MenuItem("بازگشت به تنظیمات قبلی", lambda *_: self._on_restore_prev()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("خروج کامل", lambda *_: self._on_quit()),
        )
        self._icon = pystray.Icon(
            "IPMatcher",
            create_shield_icon("unknown"),
            "IP Matcher — سپر هوشمند هماهنگی",
            menu,
        )
        self._thread = threading.Thread(target=self._icon.run, daemon=True)
        self._thread.start()

    def update_status(self, status: str, tooltip: str) -> None:
        if self._icon is None:
            return
        try:
            self._icon.icon = create_shield_icon(status)
            self._icon.title = tooltip[:120]
        except Exception:
            pass

    def stop(self) -> None:
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None
