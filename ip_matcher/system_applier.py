"""Applies target location profiles or restores saved Windows snapshots safely."""

from __future__ import annotations

import ctypes
import subprocess
import winreg
from typing import Any

from .config import AppSettings
from .geo_db import DNS_PROVIDERS, COUNTRY_PROFILES
from .system_inspector import get_dns_diagnostics, is_user_admin


def _run_ps(script: str, timeout: float = 15.0) -> tuple[int, str, str]:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=creationflags,
            encoding="utf-8",
            errors="replace",
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except Exception as exc:
        return 1, "", str(exc)


def _run_cmd(args: list[str], timeout: float = 10.0) -> tuple[int, str, str]:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=creationflags,
            encoding="utf-8",
            errors="replace",
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except Exception as exc:
        return 1, "", str(exc)


def _broadcast_locale_change() -> None:
    """Notify Windows Explorer and running apps of regional/environment change."""
    try:
        HWND_BROADCAST = 0xFFFF
        WM_SETTINGCHANGE = 0x001A
        SMTO_ABORTIFHUNG = 0x0002
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST, WM_SETTINGCHANGE, 0, "intl", SMTO_ABORTIFHUNG, 1000, None
        )
    except Exception:
        pass


def apply_timezone(windows_tz: str) -> dict[str, Any]:
    if not windows_tz:
        return {"step": "timezone", "ok": False, "message": "Empty timezone ID"}
    code, out, err = _run_cmd(["tzutil", "/s", windows_tz])
    if code == 0:
        return {"step": "timezone", "ok": True, "message": f"Timezone set to {windows_tz}"}
    return {"step": "timezone", "ok": False, "message": err or out or "Failed to set timezone"}


def sync_ntp_clock() -> dict[str, Any]:
    """Trigger Windows Time resynchronization (requires Administrator for service control)."""
    if not is_user_admin():
        return {
            "step": "ntp_clock",
            "ok": False,
            "needs_admin": True,
            "message": "همگام‌سازی سرویس ساعت (w32tm) نیازمند دسترسی مدیر (Administrator) است",
        }
    _run_cmd(["sc", "start", "w32time"], timeout=6.0)
    code, out, err = _run_cmd(["w32tm", "/resync", "/force"], timeout=10.0)
    if code == 0:
        return {"step": "ntp_clock", "ok": True, "message": "System clock resynchronized"}
    return {
        "step": "ntp_clock",
        "ok": False,
        "message": err or out or "w32tm resync failed",
    }


def apply_geoid(geo_id: int) -> dict[str, Any]:
    code, out, err = _run_ps(f"Set-WinHomeLocation -GeoId {int(geo_id)}")
    if code == 0:
        _broadcast_locale_change()
        return {"step": "geo_id", "ok": True, "message": f"GeoID set to {geo_id}"}
    # Registry fallback
    try:
        with winreg.CreateKey(
            winreg.HKEY_CURRENT_USER, r"Control Panel\International\Geo"
        ) as key:
            winreg.SetValueEx(key, "Nation", 0, winreg.REG_SZ, str(int(geo_id)))
        _broadcast_locale_change()
        return {"step": "geo_id", "ok": True, "message": f"GeoID set to {geo_id} (Registry)"}
    except Exception as exc:
        return {"step": "geo_id", "ok": False, "message": err or out or str(exc)}


def apply_culture(culture: str) -> dict[str, Any]:
    if not culture:
        return {"step": "culture", "ok": False, "message": "Empty culture"}
    safe = culture.replace("'", "")
    code, out, err = _run_ps(f"Set-Culture -CultureInfo '{safe}'")
    if code == 0:
        _broadcast_locale_change()
        return {"step": "culture", "ok": True, "message": f"Culture set to {safe}"}
    return {"step": "culture", "ok": False, "message": err or out or f"Failed Set-Culture {safe}"}


def apply_language_list(
    language_tags: list[str],
    input_tips_map: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Set Windows User Language List in exact order with optional input tips."""
    clean_tags: list[str] = []
    for t in language_tags:
        t_clean = t.strip()
        if t_clean and t_clean not in clean_tags:
            clean_tags.append(t_clean)
    if not clean_tags:
        return {"step": "language_list", "ok": False, "message": "No language tags specified"}

    lines = ["$list = New-WinUserLanguageList -Language '" + clean_tags[0].replace("'", "") + "'"]
    for extra in clean_tags[1:]:
        safe_extra = extra.replace("'", "")
        lines.append(f"$list.Add('{safe_extra}')")

    if input_tips_map:
        for idx, tag in enumerate(clean_tags):
            tips = input_tips_map.get(tag) or []
            if tips:
                tips_ps = ",".join("'" + tip.replace("'", "") + "'" for tip in tips)
                lines.append(f"$list[{idx}].InputMethodTips.Clear()")
                lines.append(f"foreach ($t in @({tips_ps})) {{ $list[{idx}].InputMethodTips.Add($t) }}")

    lines.append("Set-WinUserLanguageList -LanguageList $list -Force")
    ps_script = "; ".join(lines)
    code, out, err = _run_ps(ps_script, timeout=20.0)
    if code == 0:
        _broadcast_locale_change()
        return {
            "step": "language_list",
            "ok": True,
            "message": f"Language priority set to {', '.join(clean_tags)}",
        }
    return {
        "step": "language_list",
        "ok": False,
        "message": err or out or "Failed to update language list",
    }


def apply_location_privacy(block: bool) -> dict[str, Any]:
    """Set HKCU (and HKLM if admin) Windows Location Service consent."""
    val = "Deny" if block else "Allow"
    sub = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\location"
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, sub) as key:
            winreg.SetValueEx(key, "Value", 0, winreg.REG_SZ, val)
    except Exception as exc:
        return {"step": "location_privacy", "ok": False, "message": str(exc)}

    if is_user_admin():
        try:
            with winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, sub) as key:
                winreg.SetValueEx(key, "Value", 0, winreg.REG_SZ, val)
        except Exception:
            pass

    return {
        "step": "location_privacy",
        "ok": True,
        "message": f"Windows Location access set to {val}",
    }


def apply_dns_servers(servers: list[str]) -> dict[str, Any]:
    """Set IPv4 DNS servers on active network interfaces (requires Administrator)."""
    if not is_user_admin():
        return {
            "step": "dns",
            "ok": False,
            "needs_admin": True,
            "message": "تغییر DNS نیازمند دسترسی مدیر (Administrator) است",
        }
    if not servers:
        return {"step": "dns", "ok": False, "message": "No DNS servers specified"}

    diag = get_dns_diagnostics()
    ifaces = [i["name"] for i in diag.get("interfaces", []) if i.get("name")]
    if not ifaces:
        return {"step": "dns", "ok": False, "message": "No active network interfaces detected"}

    applied = []
    errors = []
    for raw_name in ifaces:
        # Strip ipconfig adapter prefix like "Ethernet adapter " or "Wireless LAN adapter "
        iface_name = raw_name
        for prefix in ("Ethernet adapter ", "Wireless LAN adapter ", "Unknown adapter "):
            if iface_name.startswith(prefix):
                iface_name = iface_name[len(prefix):]
                break
        c1, _, e1 = _run_cmd(
            ["netsh", "interface", "ip", "set", "dns", f'name={iface_name}', "static", servers[0]]
        )
        if c1 == 0:
            if len(servers) > 1:
                _run_cmd(
                    ["netsh", "interface", "ip", "add", "dns", f'name={iface_name}', servers[1], "index=2"]
                )
            applied.append(iface_name)
        else:
            errors.append(f"{iface_name}: {e1}")

    _run_cmd(["ipconfig", "/flushdns"])
    if applied:
        return {
            "step": "dns",
            "ok": True,
            "message": f"DNS set to {', '.join(servers)} on {', '.join(applied)}",
        }
    return {"step": "dns", "ok": False, "message": "; ".join(errors) or "Failed to set DNS"}


def apply_target_profile(
    target: dict[str, Any],
    settings: AppSettings,
    current_sys_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply all enabled alignment steps for a resolved IP target profile."""
    results: list[dict[str, Any]] = []

    if settings.sync_timezone and target.get("windows_tz"):
        results.append(apply_timezone(target["windows_tz"]))

    if settings.sync_ntp_clock:
        results.append(sync_ntp_clock())

    if settings.sync_geoid and target.get("geo_id") is not None:
        results.append(apply_geoid(int(target["geo_id"])))

    if settings.sync_culture and target.get("culture"):
        results.append(apply_culture(target["culture"]))

    if settings.sync_language_list and target.get("language_tag"):
        target_lang = str(target["language_tag"])
        langs = [target_lang]
        tips_map: dict[str, list[str]] = {}
        country_info = COUNTRY_PROFILES.get(str(target.get("country_code", "")).upper(), {})
        if country_info.get("input_tip"):
            tips_map[target_lang] = [country_info["input_tip"]]

        if settings.keep_persian_keyboard and target_lang.lower() != "fa-ir":
            langs.append("fa-IR")
            # Preserve existing Persian input tips if available
            if current_sys_state:
                for item in current_sys_state.get("language_list") or []:
                    if item.get("language_tag", "").lower() == "fa-ir" and item.get("input_tips"):
                        tips_map["fa-IR"] = list(item["input_tips"])
            if "fa-IR" not in tips_map:
                tips_map["fa-IR"] = ["0429:00000429"]

        results.append(apply_language_list(langs, tips_map))

    if settings.sync_location_privacy:
        should_block = str(target.get("country_code", "")).upper() != "IR"
        results.append(apply_location_privacy(block=should_block))

    if settings.sync_dns:
        provider = DNS_PROVIDERS.get(settings.preferred_dns_provider, DNS_PROVIDERS["cloudflare"])
        results.append(apply_dns_servers(provider["servers"]))

    ok_count = sum(1 for r in results if r.get("ok"))
    fail_count = len(results) - ok_count
    needs_admin = any(r.get("needs_admin") for r in results)

    return {
        "ok": fail_count == 0,
        "partial": ok_count > 0 and fail_count > 0,
        "applied_count": ok_count,
        "failed_count": fail_count,
        "needs_admin": needs_admin,
        "results": results,
    }


def restore_snapshot_state(state: dict[str, Any]) -> dict[str, Any]:
    """Restore Windows settings to an exact saved snapshot state."""
    results: list[dict[str, Any]] = []

    if state.get("timezone_id"):
        results.append(apply_timezone(str(state["timezone_id"])))

    if state.get("geo_id") is not None:
        results.append(apply_geoid(int(state["geo_id"])))

    if state.get("culture"):
        results.append(apply_culture(str(state["culture"])))

    lang_list = state.get("language_list") or []
    if lang_list:
        tags = [str(item["language_tag"]) for item in lang_list if item.get("language_tag")]
        tips_map = {
            str(item["language_tag"]): list(item.get("input_tips") or [])
            for item in lang_list
            if item.get("language_tag") and item.get("input_tips")
        }
        if tags:
            results.append(apply_language_list(tags, tips_map))

    loc_consent = str(state.get("location_consent") or "")
    if loc_consent.lower() in ("allow", "deny"):
        results.append(apply_location_privacy(block=loc_consent.lower() == "deny"))

    ok_count = sum(1 for r in results if r.get("ok"))
    fail_count = len(results) - ok_count
    return {
        "ok": fail_count == 0,
        "partial": ok_count > 0 and fail_count > 0,
        "applied_count": ok_count,
        "failed_count": fail_count,
        "results": results,
    }
