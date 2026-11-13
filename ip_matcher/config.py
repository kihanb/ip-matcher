"""Configuration paths and defaults for IP Matcher."""

from __future__ import annotations

import os
from dataclasses import dataclass, asdict
from pathlib import Path
import json


def get_data_dir() -> Path:
    """Return persistent data directory, falling back to local ./data if APPDATA is restricted."""
    candidates: list[Path] = []
    env_dir = os.environ.get("IP_MATCHER_DATA_DIR")
    if env_dir:
        candidates.append(Path(env_dir))
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / "IPMatcher")
    candidates.append(Path(__file__).resolve().parent.parent / "data")

    for base in candidates:
        try:
            base.mkdir(parents=True, exist_ok=True)
            return base
        except OSError:
            continue
    return Path(__file__).resolve().parent.parent / "data"


DATA_DIR = get_data_dir()
DB_PATH = DATA_DIR / "ip_matcher.db"
SETTINGS_PATH = DATA_DIR / "settings.json"
BROWSER_PROFILES_DIR = DATA_DIR / "browser_profiles"
UI_DIR = Path(__file__).resolve().parent / "ui"


@dataclass
class AppSettings:
    """User-configurable settings persisted to disk."""

    ui_language: str = "fa"  # "fa" or "en"
    theme: str = "system"  # "system", "dark", "light"
    smart_auto_sync: bool = False  # Automatically apply when IP country/timezone changes
    watch_interval_sec: int = 12  # Background IP polling interval
    proxy_mode: str = "system"  # "system", "direct", "custom"
    custom_proxy_url: str = "socks5h://127.0.0.1:10808"

    # Granular synchronization toggles
    sync_timezone: bool = True
    sync_ntp_clock: bool = True
    sync_geoid: bool = True
    sync_culture: bool = True
    sync_language_list: bool = True
    keep_persian_keyboard: bool = True
    sync_location_privacy: bool = True
    sync_dns: bool = False
    preferred_dns_provider: str = "cloudflare"  # "cloudflare", "google", "quad9"

    # Behavior
    minimize_to_tray: bool = True
    auto_snapshot_before_apply: bool = True
    notify_on_mismatch: bool = True


def load_settings() -> AppSettings:
    """Load settings from JSON file, falling back to defaults."""
    if not SETTINGS_PATH.exists():
        cfg = AppSettings()
        save_settings(cfg)
        return cfg
    try:
        raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        valid_keys = {k for k in AppSettings.__dataclass_fields__}
        filtered = {k: v for k, v in raw.items() if k in valid_keys}
        return AppSettings(**filtered)
    except Exception:
        return AppSettings()


def save_settings(cfg: AppSettings) -> None:
    """Persist settings to JSON file."""
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(
        json.dumps(asdict(cfg), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
