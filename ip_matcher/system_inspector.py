"""Inspects current Windows OS settings related to IP/location fingerprinting."""

from __future__ import annotations

import ctypes
import json
import re
import subprocess
import winreg
from datetime import datetime, timezone
from typing import Any

from .geo_db import GEOID_TO_COUNTRY, KNOWN_IRANIAN_DNS, KNOWN_SAFE_DNS


def is_user_admin() -> bool:
    """Return True if the current process has Administrator privileges."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _run_cmd(args: list[str], timeout: float = 5.0) -> tuple[int, str, str]:
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


def get_windows_timezone() -> dict[str, Any]:
    """Read active Windows timezone ID and current local/UTC offset."""
    code, out, _ = _run_cmd(["tzutil", "/g"])
    tz_id = out.splitlines()[0].strip() if code == 0 and out else ""
    now_local = datetime.now().astimezone()
    offset = now_local.utcoffset()
    offset_sec = int(offset.total_seconds()) if offset else 0
    return {
        "timezone_id": tz_id,
        "local_time": now_local.strftime("%Y-%m-%d %H:%M:%S"),
        "utc_offset_sec": offset_sec,
        "utc_offset_str": _format_utc_offset(offset_sec),
    }


def _format_utc_offset(offset_sec: int) -> str:
    sign = "+" if offset_sec >= 0 else "-"
    total_mins = abs(offset_sec) // 60
    hrs, mins = divmod(total_mins, 60)
    return f"UTC{sign}{hrs:02d}:{mins:02d}"


def get_geo_location() -> dict[str, Any]:
    """Read Windows Home Location GeoID from Registry with PowerShell fallback."""
    geo_id: int | None = None
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Control Panel\International\Geo"
        ) as key:
            val, _ = winreg.QueryValueEx(key, "Nation")
            geo_id = int(str(val).strip())
    except Exception:
        pass

    if geo_id is None:
        code, out, _ = _run_cmd(
            ["powershell", "-NoProfile", "-Command", "(Get-WinHomeLocation).GeoId"]
        )
        if code == 0 and out.isdigit():
            geo_id = int(out)

    country_info = GEOID_TO_COUNTRY.get(geo_id or -1, {})
    return {
        "geo_id": geo_id,
        "geo_country_code": country_info.get("code", ""),
        "geo_country_name": country_info.get("name", f"GeoID {geo_id}" if geo_id else "Unknown"),
    }


def get_culture_and_formats() -> dict[str, Any]:
    """Read current Windows regional format / culture."""
    locale_name = ""
    country_name = ""
    currency_symbol = ""
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Control Panel\International"
        ) as key:
            locale_name, _ = winreg.QueryValueEx(key, "LocaleName")
            try:
                country_name, _ = winreg.QueryValueEx(key, "sCountry")
            except OSError:
                pass
            try:
                currency_symbol, _ = winreg.QueryValueEx(key, "sCurrency")
            except OSError:
                pass
    except Exception:
        pass

    if not locale_name:
        code, out, _ = _run_cmd(
            ["powershell", "-NoProfile", "-Command", "(Get-Culture).Name"]
        )
        if code == 0 and out:
            locale_name = out.strip()

    return {
        "culture": locale_name or "en-US",
        "regional_country": country_name,
        "currency_symbol": currency_symbol,
    }


def get_user_language_list() -> list[dict[str, Any]]:
    """Read Windows User Language List (preferred UI/Accept-Language order & keyboards)."""
    langs: list[str] = []
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Control Panel\International\User Profile"
        ) as key:
            val, _ = winreg.QueryValueEx(key, "Languages")
            if isinstance(val, list):
                langs = [str(x).strip() for x in val if str(x).strip()]
    except Exception:
        pass

    if langs:
        result: list[dict[str, Any]] = []
        for tag in langs:
            tips = _read_input_tips_for_lang(tag)
            result.append({"language_tag": tag, "input_tips": tips})
        return result

    # Fallback to PowerShell
    ps = (
        "Get-WinUserLanguageList | ForEach-Object { "
        "[PSCustomObject]@{language_tag=$_.LanguageTag; input_tips=@($_.InputMethodTips)} "
        "} | ConvertTo-Json -Compress"
    )
    code, out, _ = _run_cmd(["powershell", "-NoProfile", "-Command", ps], timeout=8.0)
    if code == 0 and out:
        try:
            data = json.loads(out)
            if isinstance(data, dict):
                data = [data]
            if isinstance(data, list):
                return [
                    {
                        "language_tag": str(item.get("language_tag", "")),
                        "input_tips": list(item.get("input_tips") or []),
                    }
                    for item in data
                    if item.get("language_tag")
                ]
        except Exception:
            pass
    return []


def _read_input_tips_for_lang(lang_tag: str) -> list[str]:
    tips: list[str] = []
    subkey = rf"Control Panel\International\User Profile\{lang_tag}"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey) as key:
            i = 0
            while True:
                try:
                    name, val, _ = winreg.EnumValue(key, i)
                    if ":" in name and str(val) == "1":
                        tips.append(name)
                    i += 1
                except OSError:
                    break
    except Exception:
        pass
    return tips


def get_location_privacy() -> dict[str, Any]:
    """Read Windows Location Service consent (HKCU and HKLM if accessible)."""
    hkcu_val = "Unknown"
    hklm_val = "Unknown"
    sub = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\location"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub) as key:
            val, _ = winreg.QueryValueEx(key, "Value")
            hkcu_val = str(val)
    except Exception:
        pass
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, sub) as key:
            val, _ = winreg.QueryValueEx(key, "Value")
            hklm_val = str(val)
    except Exception:
        pass

    is_protected = hkcu_val.lower() == "deny" or hklm_val.lower() == "deny"
    return {
        "hkcu_location_consent": hkcu_val,
        "hklm_location_consent": hklm_val,
        "location_leak_blocked": is_protected,
    }


def get_dns_diagnostics() -> dict[str, Any]:
    """Parse active IPv4 DNS servers from ipconfig /all and evaluate leak risk."""
    code, out, _ = _run_cmd(["ipconfig", "/all"], timeout=5.0)
    if code != 0 or not out:
        return {"interfaces": [], "all_dns": [], "risk": "unknown", "notes": []}

    interfaces: list[dict[str, Any]] = []
    current_iface: dict[str, Any] | None = None
    reading_dns = False

    for raw_line in out.splitlines():
        line = raw_line.rstrip()
        if line and not line.startswith(" "):
            if current_iface and (current_iface["dns"] or current_iface["connected"]):
                interfaces.append(current_iface)
            current_iface = {
                "name": line.rstrip(":"),
                "connected": True,
                "dns": [],
            }
            reading_dns = False
            continue

        if current_iface is None:
            continue

        stripped = line.strip()
        if "Media disconnected" in stripped:
            current_iface["connected"] = False
            reading_dns = False
            continue

        if re.match(r"^DNS Servers\s*[\.\s]*:", stripped, re.IGNORECASE):
            reading_dns = True
            _, _, rhs = stripped.partition(":")
            ip = rhs.strip()
            if _looks_like_ipv4(ip):
                current_iface["dns"].append(ip)
            continue

        if reading_dns:
            if ":" in stripped and not _looks_like_ipv6(stripped):
                reading_dns = False
            elif _looks_like_ipv4(stripped):
                current_iface["dns"].append(stripped)

    if current_iface and (current_iface["dns"] or current_iface["connected"]):
        interfaces.append(current_iface)

    active = [i for i in interfaces if i["connected"] and i["dns"]]
    all_dns: list[str] = []
    for i in active:
        for ip in i["dns"]:
            if ip not in all_dns:
                all_dns.append(ip)

    risk = "safe"
    notes: list[str] = []
    for ip in all_dns:
        if ip in KNOWN_IRANIAN_DNS:
            risk = "high"
            notes.append(f"DNS ایرانی/تحریم‌شکن شناسایی شد: {ip}")
        elif _is_private_ip(ip) and risk != "high":
            risk = "medium"
            notes.append(f"DNS روتر/شبکه محلی ({ip}) ممکن است درخواست‌ها را به ISP ارسال کند")
        elif ip in KNOWN_SAFE_DNS:
            notes.append(f"DNS عمومی استاندارد: {ip}")

    if not all_dns:
        risk = "unknown"

    return {
        "interfaces": active,
        "all_dns": all_dns,
        "risk": risk,
        "notes": notes,
    }


def _looks_like_ipv4(val: str) -> bool:
    return bool(re.match(r"^\d{1,3}(?:\.\d{1,3}){3}$", val))


def _looks_like_ipv6(val: str) -> bool:
    return ":" in val and bool(re.match(r"^[0-9a-fA-F:]+(%[0-9a-zA-Z]+)?$", val))


def _is_private_ip(ip: str) -> bool:
    return (
        ip.startswith("192.168.")
        or ip.startswith("10.")
        or bool(re.match(r"^172\.(1[6-9]|2\d|3[0-1])\.", ip))
    )


def inspect_system_state() -> dict[str, Any]:
    """Return a complete snapshot of current Windows configuration."""
    tz = get_windows_timezone()
    geo = get_geo_location()
    culture = get_culture_and_formats()
    languages = get_user_language_list()
    location = get_location_privacy()
    dns = get_dns_diagnostics()

    primary_lang = languages[0]["language_tag"] if languages else culture["culture"]

    return {
        "inspected_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "is_admin": is_user_admin(),
        "timezone_id": tz["timezone_id"],
        "local_time": tz["local_time"],
        "utc_offset_sec": tz["utc_offset_sec"],
        "utc_offset_str": tz["utc_offset_str"],
        "geo_id": geo["geo_id"],
        "geo_country_code": geo["geo_country_code"],
        "geo_country_name": geo["geo_country_name"],
        "culture": culture["culture"],
        "regional_country": culture["regional_country"],
        "currency_symbol": culture["currency_symbol"],
        "primary_language": primary_lang,
        "language_list": languages,
        "location_consent": location["hkcu_location_consent"],
        "location_leak_blocked": location["location_leak_blocked"],
        "dns": dns,
    }
