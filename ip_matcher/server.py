"""Core application controller, background smart IP watcher, and local HTTP API server."""

from __future__ import annotations

import ctypes
import json
import mimetypes
import os
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from .browser_launcher import launch_aligned_browser
from .config import AppSettings, UI_DIR, load_settings, save_settings
from .geo_db import COUNTRY_PROFILES, resolve_target_profile
from .ip_detector import detect_ip_info
from .matcher_engine import evaluate_alignment
from .profile_store import ProfileStore
from .system_applier import apply_target_profile, restore_snapshot_state
from .system_inspector import inspect_system_state, is_user_admin


class AppController:
    """Thread-safe coordinator between IP detection, OS state, snapshots, and UI."""

    def __init__(self, store: ProfileStore | None = None) -> None:
        self.settings: AppSettings = load_settings()
        self.store: ProfileStore = store or ProfileStore()
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._watcher_thread: threading.Thread | None = None

        self.ip_info: dict[str, Any] = {}
        self.sys_state: dict[str, Any] = inspect_system_state()
        self.alignment: dict[str, Any] = {"ready": False, "score": 0, "risk_level": "unknown", "checks": [], "planned_changes": []}
        self.last_ip_seen: str = ""
        self.last_country_seen: str = ""
        self.status_callbacks: list[Callable[[str, str], None]] = []

        # Capture baseline system configuration on very first run
        self.store.ensure_baseline(self.sys_state)

    def start_watcher(self) -> None:
        if self._watcher_thread and self._watcher_thread.is_alive():
            return
        self._stop_event.clear()
        self._watcher_thread = threading.Thread(target=self._watcher_loop, daemon=True)
        self._watcher_thread.start()

    def stop_watcher(self) -> None:
        self._stop_event.set()

    def _notify_status(self) -> None:
        risk = self.alignment.get("risk_level", "unknown")
        score = self.alignment.get("score", 0)
        cc = self.ip_info.get("country_code", "--")
        ip = self.ip_info.get("ip", "...")
        tooltip = f"IP Matcher | {ip} ({cc}) | تطابق: {score}%"
        for cb in self.status_callbacks:
            try:
                cb(risk, tooltip)
            except Exception:
                pass

    def _watcher_loop(self) -> None:
        # Run an initial refresh quickly on startup
        self.refresh_all(source="startup")
        while not self._stop_event.is_set():
            interval = max(5, min(300, int(self.settings.watch_interval_sec or 12)))
            if self._stop_event.wait(interval):
                break
            try:
                self.refresh_all(source="watcher")
            except Exception:
                pass

    def refresh_all(self, source: str = "manual") -> dict[str, Any]:
        """Refresh public IP, local Windows state, and re-evaluate alignment."""
        ip_info = detect_ip_info(
            proxy_mode=self.settings.proxy_mode,
            custom_proxy_url=self.settings.custom_proxy_url,
        )
        sys_state = inspect_system_state()

        with self._lock:
            prev_ip = self.last_ip_seen
            prev_cc = self.last_country_seen
            self.ip_info = ip_info
            self.sys_state = sys_state
            self.alignment = evaluate_alignment(ip_info, sys_state, self.settings)

            cur_ip = ip_info.get("ip", "")
            cur_cc = ip_info.get("country_code", "")
            ip_changed = bool(cur_ip and cur_ip != prev_ip)
            if cur_ip:
                self.last_ip_seen = cur_ip
                self.last_country_seen = cur_cc

            # Update baseline IP tag once if empty
            baseline = self.store.get_baseline()
            if baseline and not baseline.get("ip_address") and cur_ip and cur_cc == "IR":
                self.store.rename_snapshot(
                    baseline["id"],
                    baseline["name"],
                    notes=f"تنظیمات اولیه سیستم در کشور {cur_cc} ({cur_ip})",
                )

            if ip_changed and prev_ip:
                self.store.add_log(
                    "detect",
                    "ok",
                    f"تغییر آی‌پی تشخیص داده شد: {prev_ip} ({prev_cc}) ← {cur_ip} ({cur_cc})",
                    {"prev_ip": prev_ip, "new_ip": cur_ip, "country": cur_cc},
                )

            # Smart Auto-Sync when enabled and IP/country shifted with pending changes
            if (
                self.settings.smart_auto_sync
                and ip_info.get("ok")
                and self.alignment.get("planned_changes")
                and (ip_changed or source == "watcher")
            ):
                self._apply_locked(auto_mode=True)

            self._notify_status()
            return self.get_full_state()

    def _apply_locked(
        self,
        auto_mode: bool = False,
        target_override: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        sys_before = inspect_system_state()
        target = target_override or self.alignment.get("target")
        if not target:
            return {"ok": False, "message": "پروفایل مقصد مشخص نیست"}

        if self.settings.auto_snapshot_before_apply:
            cc_label = target.get("country_code") or "Target"
            self.store.save_snapshot(
                name=f"ذخیره خودکار پیش از تغییر به {cc_label}",
                kind="auto",
                state=sys_before,
                ip_address=self.ip_info.get("ip", ""),
                country_code=sys_before.get("geo_country_code", ""),
                country_name=sys_before.get("geo_country_name", ""),
                notes="اسنپ‌شات خودکار برای بازگشت سریع",
            )

        res = apply_target_profile(target, self.settings, current_sys_state=sys_before)
        self.sys_state = inspect_system_state()
        self.alignment = evaluate_alignment(self.ip_info, self.sys_state, self.settings)

        action_name = "auto_sync" if auto_mode else "apply"
        status = "ok" if res["ok"] else ("partial" if res["partial"] else "error")
        self.store.add_log(
            action_name,
            status,
            f"همگام‌سازی سیستم با {target.get('country_name_fa') or target.get('country_name')} ({res['applied_count']} مورد اعمال شد)",
            res,
        )
        self._notify_status()
        return res

    def apply_current_target(self) -> dict[str, Any]:
        with self._lock:
            if not self.ip_info.get("ok"):
                self.refresh_all(source="pre_apply")
            res = self._apply_locked(auto_mode=False)
            return {"result": res, "state": self.get_full_state()}

    def apply_country_preset(self, country_code: str) -> dict[str, Any]:
        code = country_code.strip().upper()
        if code not in COUNTRY_PROFILES:
            return {"ok": False, "message": f"Country {code} not found"}
        c = COUNTRY_PROFILES[code]
        target = resolve_target_profile(
            {
                "country_code": code,
                "country_name": c["name"],
                "iana_timezone": "",
                "utc_offset_sec": 0,
                "currency": c["currency"],
            }
        )
        target["windows_tz"] = c["default_tz"]
        with self._lock:
            res = self._apply_locked(auto_mode=False, target_override=target)
            return {"result": res, "state": self.get_full_state()}

    def restore_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        with self._lock:
            if snapshot_id == "baseline":
                snap = self.store.get_baseline()
            elif snapshot_id == "latest":
                snap = self.store.get_latest_auto_snapshot() or self.store.get_baseline()
            else:
                snap = self.store.get_snapshot(snapshot_id)

            if not snap:
                return {"ok": False, "message": "پروفایل یا اسنپ‌شات مورد نظر یافت نشد"}

            # Backup current state before restoring so even a restore is reversible
            sys_before = inspect_system_state()
            self.store.save_snapshot(
                name=f"پیش از بازگشت به «{snap['name']}»",
                kind="auto",
                state=sys_before,
                ip_address=self.ip_info.get("ip", ""),
                country_code=sys_before.get("geo_country_code", ""),
                country_name=sys_before.get("geo_country_name", ""),
                notes="ذخیره خودکار پیش از بازگردانی",
            )

            res = restore_snapshot_state(snap["state"])
            self.sys_state = inspect_system_state()
            self.alignment = evaluate_alignment(self.ip_info, self.sys_state, self.settings)

            status = "ok" if res["ok"] else ("partial" if res["partial"] else "error")
            self.store.add_log(
                "restore",
                status,
                f"بازگردانی تنظیمات به «{snap['name']}»",
                res,
            )
            self._notify_status()
            return {"ok": True, "result": res, "restored": snap["name"], "state": self.get_full_state()}

    def save_custom_profile(self, name: str, notes: str = "") -> dict[str, Any]:
        clean_name = name.strip()
        if not clean_name:
            return {"ok": False, "message": "نام پروفایل نمی‌تواند خالی باشد"}
        with self._lock:
            sys_now = inspect_system_state()
            snap = self.store.save_snapshot(
                name=clean_name,
                kind="custom",
                state=sys_now,
                is_pinned=True,
                ip_address=self.ip_info.get("ip", ""),
                country_code=sys_now.get("geo_country_code", ""),
                country_name=sys_now.get("geo_country_name", ""),
                notes=notes.strip(),
            )
            self.store.add_log("snapshot", "ok", f"پروفایل جدید ذخیره شد: «{clean_name}»")
            return {"ok": True, "snapshot": snap, "state": self.get_full_state()}

    def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            for key, val in patch.items():
                if hasattr(self.settings, key):
                    field_type = type(getattr(self.settings, key))
                    if field_type is bool:
                        setattr(self.settings, key, bool(val))
                    elif field_type is int:
                        setattr(self.settings, key, int(val))
                    else:
                        setattr(self.settings, key, str(val))
            save_settings(self.settings)
            self.alignment = evaluate_alignment(self.ip_info, self.sys_state, self.settings)
            self._notify_status()
            return {"ok": True, "state": self.get_full_state()}

    def launch_browser(self, start_url: str = "https://whoer.net") -> dict[str, Any]:
        with self._lock:
            target = self.alignment.get("target") or {
                "country_code": "US",
                "language_tag": "en-US",
            }
            res = launch_aligned_browser(
                target=target,
                proxy_mode=self.settings.proxy_mode,
                custom_proxy_url=self.settings.custom_proxy_url,
                start_url=start_url,
            )
            self.store.add_log(
                "browser_launch",
                "ok" if res.get("ok") else "error",
                res.get("message", ""),
            )
            return res

    def get_full_state(self) -> dict[str, Any]:
        with self._lock:
            from dataclasses import asdict

            return {
                "settings": asdict(self.settings),
                "ip_info": self.ip_info,
                "sys_state": self.sys_state,
                "alignment": self.alignment,
                "snapshots": self.store.list_snapshots(),
                "logs": self.store.list_logs(50),
                "is_admin": is_user_admin(),
            }


def request_uac_elevation() -> bool:
    """Relaunch the current Python script with Administrator (UAC) privileges without a console."""
    try:
        exe = Path(sys.executable)
        pythonw = exe.with_name("pythonw.exe")
        target_exe = str(pythonw) if pythonw.exists() else str(exe)
        script = os.path.abspath(sys.argv[0])
        params = f'"{script}" --elevated'
        ret = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", target_exe, params, None, 1
        )
        return int(ret) > 32
    except Exception:
        return False


def create_http_server(controller: AppController, port: int = 0) -> ThreadingHTTPServer:
    """Create a local-only HTTP server serving the UI and JSON API."""

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: Any) -> None:
            return  # Keep stdout clean in desktop mode

        def _send_json(self, payload: Any, status: int = 200) -> None:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def _read_json_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return {}
            body = self.rfile.read(length).decode("utf-8", errors="replace")
            try:
                data = json.loads(body)
                return data if isinstance(data, dict) else {}
            except Exception:
                return {}

        def _serve_static(self, rel_path: str) -> None:
            clean = rel_path.lstrip("/") or "index.html"
            target = (UI_DIR / clean).resolve()
            if not str(target).startswith(str(UI_DIR.resolve())) or not target.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            mime, _ = mimetypes.guess_type(str(target))
            if target.suffix == ".ttf":
                mime = "font/ttf"
            data = target.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", f"{mime or 'application/octet-stream'}; charset=utf-8" if (mime or "").startswith("text/") or mime == "application/javascript" else (mime or "application/octet-stream"))
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path

            if path == "/api/state":
                self._send_json(controller.get_full_state())
            elif path == "/api/countries":
                items = [
                    {
                        "code": code,
                        "name": info["name"],
                        "name_fa": info["name_fa"],
                        "geo_id": info["geo_id"],
                        "culture": info["culture"],
                        "tz": info["default_tz"],
                        "currency": info["currency"],
                    }
                    for code, info in sorted(
                        COUNTRY_PROFILES.items(), key=lambda kv: kv[1]["name"]
                    )
                ]
                self._send_json({"countries": items})
            elif path == "/api/snapshots/export":
                raw = controller.store.export_profiles_json().encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="ip-matcher-profiles.json"')
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            else:
                self._serve_static(path)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            body = self._read_json_body()

            if path == "/api/refresh":
                self._send_json(controller.refresh_all(source="manual"))
            elif path == "/api/apply":
                self._send_json(controller.apply_current_target())
            elif path == "/api/apply-country":
                code = str(body.get("country_code", ""))
                self._send_json(controller.apply_country_preset(code))
            elif path == "/api/restore":
                snap_id = str(body.get("snapshot_id", "latest"))
                self._send_json(controller.restore_snapshot(snap_id))
            elif path == "/api/snapshots":
                res = controller.save_custom_profile(
                    str(body.get("name", "")),
                    str(body.get("notes", "")),
                )
                self._send_json(res, status=200 if res.get("ok") else 400)
            elif path == "/api/snapshots/import":
                try:
                    count = controller.store.import_profiles_json(str(body.get("raw_json", "")))
                    self._send_json({"ok": True, "imported": count, "state": controller.get_full_state()})
                except Exception as exc:
                    self._send_json({"ok": False, "message": str(exc)}, status=400)
            elif path == "/api/settings":
                self._send_json(controller.update_settings(body))
            elif path == "/api/launch-browser":
                url = str(body.get("url") or "https://whoer.net")
                self._send_json(controller.launch_browser(url))
            elif path == "/api/elevate":
                ok = request_uac_elevation()
                self._send_json({"ok": ok})
                if ok:
                    threading.Timer(0.6, lambda: os._exit(0)).start()
            else:
                self.send_error(HTTPStatus.NOT_FOUND)

        def do_DELETE(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path.startswith("/api/snapshots/"):
                snap_id = parsed.path.split("/api/snapshots/", 1)[1]
                ok = controller.store.delete_snapshot(snap_id)
                self._send_json(
                    {"ok": ok, "state": controller.get_full_state()},
                    status=200 if ok else 400,
                )
            else:
                self.send_error(HTTPStatus.NOT_FOUND)

        def do_PATCH(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path.startswith("/api/snapshots/"):
                snap_id = parsed.path.split("/api/snapshots/", 1)[1]
                body = self._read_json_body()
                ok = controller.store.rename_snapshot(
                    snap_id,
                    str(body.get("name", "")),
                    body.get("notes"),
                )
                self._send_json({"ok": ok, "state": controller.get_full_state()})
            else:
                self.send_error(HTTPStatus.NOT_FOUND)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    return server
