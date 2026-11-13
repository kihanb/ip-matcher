"""Intelligent matching and risk-scoring engine comparing IP profile vs Windows state."""

from __future__ import annotations

from typing import Any

from .config import AppSettings
from .geo_db import DNS_PROVIDERS, resolve_target_profile


def _lang_base(tag: str) -> str:
    return tag.split("-")[0].lower().strip() if tag else ""


def evaluate_alignment(
    ip_info: dict[str, Any],
    sys_state: dict[str, Any],
    settings: AppSettings,
) -> dict[str, Any]:
    """
    Compare detected IP geolocation against current Windows configuration.

    Returns alignment score (0-100), risk level, itemized checks, and planned changes.
    """
    if not ip_info.get("ok"):
        return {
            "ready": False,
            "score": 0,
            "risk_level": "unknown",
            "target": None,
            "checks": [],
            "planned_changes": [],
            "mismatch_count": 0,
        }

    target = resolve_target_profile(ip_info)
    checks: list[dict[str, Any]] = []
    penalty = 0

    # 1. Timezone check (weight: 30)
    cur_tz = sys_state.get("timezone_id") or ""
    exp_tz = target["windows_tz"]
    tz_match = cur_tz.lower() == exp_tz.lower() and bool(exp_tz)
    if not tz_match:
        # Check if UTC offset at least matches (e.g. Romance vs W. Europe both UTC+01:00)
        same_offset = sys_state.get("utc_offset_sec") == target["utc_offset_sec"]
        if same_offset and cur_tz:
            tz_match = True
            tz_severity = "ok"
        else:
            penalty += 30
            tz_severity = "high"
    else:
        tz_severity = "ok"

    checks.append(
        {
            "key": "timezone",
            "title_fa": "منطقه زمانی و ساعت سیستم",
            "title_en": "System Timezone & Clock",
            "current": f"{cur_tz or 'نامشخص'} ({sys_state.get('utc_offset_str', '')})",
            "expected": f"{exp_tz} ({target['iana_timezone']})",
            "matched": tz_match,
            "severity": tz_severity,
            "fixable": True,
            "detail_fa": (
                "منطقه زمانی سیستم با موقعیت آی‌پی هماهنگ است."
                if tz_match
                else "عدم تطابق منطقه زمانی یکی از اصلی‌ترین نشانه‌های لو رفتن موقعیت واقعی است."
            ),
            "detail_en": (
                "Windows timezone matches the IP geolocation."
                if tz_match
                else "Timezone mismatch is a primary anti-fraud trigger for websites."
            ),
        }
    )

    # 2. Windows Home Location GeoID check (weight: 20)
    cur_geo = sys_state.get("geo_id")
    exp_geo = target.get("geo_id")
    geo_match = (cur_geo == exp_geo) if exp_geo is not None else True
    if not geo_match:
        penalty += 20
    checks.append(
        {
            "key": "geo_id",
            "title_fa": "کشور سیستم (Windows GeoID)",
            "title_en": "Windows Home Location (GeoID)",
            "current": f"{sys_state.get('geo_country_name', 'Unknown')} ({cur_geo})",
            "expected": f"{target['country_name']} ({exp_geo})" if exp_geo else target["country_name"],
            "matched": geo_match,
            "severity": "ok" if geo_match else "high",
            "fixable": exp_geo is not None,
            "detail_fa": (
                "شناسه کشور ویندوز با کشور آی‌پی یکسان است."
                if geo_match
                else "فروشگاه و سرویس‌های سیستم کشور متفاوتی از آی‌پی گزارش می‌دهند."
            ),
            "detail_en": (
                "Windows Home Location matches the IP country."
                if geo_match
                else "OS region GeoID differs from your public IP country."
            ),
        }
    )

    # 3. Regional Format / Culture check (weight: 15)
    cur_culture = sys_state.get("culture") or ""
    exp_culture = target["culture"]
    culture_match = cur_culture.lower() == exp_culture.lower()
    if not culture_match:
        # Partial credit if English-speaking countries share language
        if _lang_base(cur_culture) == "en" and _lang_base(exp_culture) == "en":
            penalty += 7
            cult_sev = "medium"
        else:
            penalty += 15
            cult_sev = "high"
    else:
        cult_sev = "ok"
    checks.append(
        {
            "key": "culture",
            "title_fa": "فرمت منطقه‌ای و واحد پول",
            "title_en": "Regional Format & Culture",
            "current": cur_culture,
            "expected": exp_culture,
            "matched": culture_match,
            "severity": cult_sev,
            "fixable": True,
            "detail_fa": (
                "فرمت تاریخ، اعداد و تقویم با منطقه آی‌پی هماهنگ است."
                if culture_match
                else "فرمت منطقه‌ای سیستم (تقویم/اعداد/ارز) با کشور آی‌پی هم‌خوانی ندارد."
            ),
            "detail_en": (
                "Regional culture and formats match the IP region."
                if culture_match
                else "Regional date/number/currency culture differs from IP country."
            ),
        }
    )

    # 4. Preferred Language / Accept-Language check (weight: 15)
    cur_langs = sys_state.get("language_list") or []
    cur_primary = cur_langs[0]["language_tag"] if cur_langs else sys_state.get("primary_language", "")
    exp_lang = target["language_tag"]
    lang_match = _lang_base(cur_primary) == _lang_base(exp_lang)
    if not lang_match:
        penalty += 15
    checks.append(
        {
            "key": "language",
            "title_fa": "زبان اولویت سیستم و مرورگر",
            "title_en": "Primary System & Browser Language",
            "current": cur_primary or "نامشخص",
            "expected": exp_lang,
            "matched": lang_match,
            "severity": "ok" if lang_match else "medium",
            "fixable": True,
            "detail_fa": (
                "زبان اول سیستم با کشور مقصد هماهنگ است."
                if lang_match
                else "اولویت زبان سیستم ممکن است هدر Accept-Language غیرهم‌خوان ارسال کند."
            ),
            "detail_en": (
                "Primary language aligns with target region."
                if lang_match
                else "Primary language differs from target country language."
            ),
        }
    )

    # 5. Windows Location Privacy Guard (weight: 10)
    loc_blocked = bool(sys_state.get("location_leak_blocked", False))
    target_is_ir = target["country_code"] == "IR"
    loc_ok = True if target_is_ir else loc_blocked
    if not loc_ok:
        penalty += 10
    checks.append(
        {
            "key": "location_privacy",
            "title_fa": "محافظت از نشت GPS/Wi-Fi ویندوز",
            "title_en": "Windows Location Leak Guard",
            "current": "مسدود (ایمن)" if loc_blocked else "فعال (احتمال نشت موقعیت واقعی)",
            "expected": "آزاد (ایران)" if target_is_ir else "مسدود (Deny)",
            "matched": loc_ok,
            "severity": "ok" if loc_ok else "medium",
            "fixable": not target_is_ir,
            "detail_fa": (
                "سرویس موقعیت مکانی ویندوز نشت مختصات فیزیکی را مسدود کرده است."
                if loc_ok
                else "سرویس Location ویندوز فعال است و ممکن است مختصات واقعی از طریق Wi-Fi لو برود."
            ),
            "detail_en": (
                "Windows Location Service will not leak physical Wi-Fi/GPS coordinates."
                if loc_ok
                else "Windows Location Service is enabled and can leak real coordinates."
            ),
        }
    )

    # 6. DNS Leak Check (weight: 10)
    dns_info = sys_state.get("dns") or {}
    dns_risk = dns_info.get("risk", "unknown")
    all_dns = dns_info.get("all_dns") or []
    dns_ok = dns_risk in ("safe", "unknown") or target_is_ir
    if not dns_ok:
        penalty += 10 if dns_risk == "high" else 5
    dns_provider = DNS_PROVIDERS.get(settings.preferred_dns_provider, DNS_PROVIDERS["cloudflare"])
    checks.append(
        {
            "key": "dns",
            "title_fa": "وضعیت نشت DNS",
            "title_en": "DNS Leak Status",
            "current": ", ".join(all_dns[:3]) if all_dns else "نامشخص",
            "expected": ", ".join(dns_provider["servers"]),
            "matched": dns_ok,
            "severity": "ok" if dns_ok else ("high" if dns_risk == "high" else "medium"),
            "fixable": True,
            "detail_fa": (
                "تنظیمات DNS در وضعیت ایمن است."
                if dns_ok
                else "؛ ".join(dns_info.get("notes") or ["احتمال نشت DNS به شبکه محلی یا ISP وجود دارد."])
            ),
            "detail_en": (
                "DNS configuration appears clean."
                if dns_ok
                else "Local or ISP DNS detected; may cause DNS leak."
            ),
        }
    )

    # 7. IPv6 Leak Check (informational / warning)
    ipv6_leak = bool(ip_info.get("ipv6_leak", False))
    if ipv6_leak:
        penalty += 5
    checks.append(
        {
            "key": "ipv6",
            "title_fa": "بررسی نشت IPv6",
            "title_en": "IPv6 Leak Check",
            "current": ip_info.get("ipv6") or "غیرفعال / بدون نشت",
            "expected": "بدون نشت IPv6",
            "matched": not ipv6_leak,
            "severity": "ok" if not ipv6_leak else "high",
            "fixable": False,
            "detail_fa": (
                "هیچ نشت IPv6 خارج از تونل VPN مشاهده نشد."
                if not ipv6_leak
                else "آدرس IPv6 فعال است در حالی که IPv4 از VPN عبور می‌کند؛ ممکن است هویت واقعی لو برود."
            ),
            "detail_en": (
                "No IPv6 leak detected."
                if not ipv6_leak
                else "IPv6 is reachable outside IPv4 tunnel and may leak real ISP."
            ),
        }
    )

    score = max(0, min(100, 100 - penalty))
    if score >= 90:
        risk_level = "safe"
    elif score >= 60:
        risk_level = "warning"
    else:
        risk_level = "critical"

    # Build planned changes respecting user settings
    planned_changes: list[dict[str, Any]] = []
    if settings.sync_timezone and not tz_match:
        planned_changes.append(
            {
                "key": "timezone",
                "label_fa": "تغییر منطقه زمانی",
                "label_en": "Set Timezone",
                "from": cur_tz or "-",
                "to": exp_tz,
            }
        )
    if settings.sync_geoid and not geo_match and exp_geo is not None:
        planned_changes.append(
            {
                "key": "geo_id",
                "label_fa": "تغییر کشور ویندوز (GeoID)",
                "label_en": "Set Windows GeoID",
                "from": f"{sys_state.get('geo_country_name')} ({cur_geo})",
                "to": f"{target['country_name']} ({exp_geo})",
            }
        )
    if settings.sync_culture and not culture_match:
        planned_changes.append(
            {
                "key": "culture",
                "label_fa": "تغییر فرمت منطقه‌ای",
                "label_en": "Set Regional Culture",
                "from": cur_culture,
                "to": exp_culture,
            }
        )
    if settings.sync_language_list and not lang_match:
        planned_changes.append(
            {
                "key": "language",
                "label_fa": "تنظیم زبان اولویت",
                "label_en": "Set Language Order",
                "from": cur_primary or "-",
                "to": f"{exp_lang} (+ fa-IR)" if settings.keep_persian_keyboard and exp_lang != "fa-IR" else exp_lang,
            }
        )
    if settings.sync_location_privacy and not loc_ok:
        planned_changes.append(
            {
                "key": "location_privacy",
                "label_fa": "مسدودسازی دسترسی موقعیت مکانی ویندوز",
                "label_en": "Block Windows Location Service",
                "from": "Allow",
                "to": "Deny",
            }
        )
    if settings.sync_dns and not dns_ok:
        planned_changes.append(
            {
                "key": "dns",
                "label_fa": f"تنظیم DNS روی {dns_provider['name']}",
                "label_en": f"Set DNS ({dns_provider['name']})",
                "from": ", ".join(all_dns[:2]) if all_dns else "Auto",
                "to": ", ".join(dns_provider["servers"]),
            }
        )

    mismatch_count = sum(1 for c in checks if not c["matched"])
    return {
        "ready": True,
        "score": score,
        "risk_level": risk_level,
        "target": target,
        "checks": checks,
        "planned_changes": planned_changes,
        "mismatch_count": mismatch_count,
    }
