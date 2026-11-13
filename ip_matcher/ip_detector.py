"""Real-time multi-provider IP & geolocation detection with proxy and IPv6 leak support."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import requests


def _build_proxies(proxy_mode: str, custom_proxy_url: str) -> dict[str, str] | None:
    """Return requests proxies dict based on user proxy mode."""
    if proxy_mode == "direct":
        return {"http": "", "https": ""}
    if proxy_mode == "custom" and custom_proxy_url.strip():
        url = custom_proxy_url.strip()
        return {"http": url, "https": url}
    return None  # Use system / environment proxy settings


def _normalize_ip_api(data: dict[str, Any]) -> dict[str, Any] | None:
    if data.get("status") != "success" or not data.get("query"):
        return None
    return {
        "ip": str(data.get("query", "")),
        "country_code": str(data.get("countryCode", "")).upper(),
        "country_name": str(data.get("country", "")),
        "region": str(data.get("regionName", "")),
        "city": str(data.get("city", "")),
        "postal": str(data.get("zip", "")),
        "latitude": data.get("lat"),
        "longitude": data.get("lon"),
        "iana_timezone": str(data.get("timezone", "")),
        "utc_offset_sec": int(data.get("offset") or 0),
        "isp": str(data.get("isp", "")),
        "org": str(data.get("org", "")),
        "asn": str(data.get("as", "")),
        "currency": str(data.get("currency", "")),
        "is_proxy": bool(data.get("proxy", False)),
        "is_hosting": bool(data.get("hosting", False)),
        "provider": "ip-api.com",
    }


def _normalize_ipwhois(data: dict[str, Any]) -> dict[str, Any] | None:
    if not data.get("success", True) or not data.get("ip"):
        return None
    tz = data.get("timezone") or {}
    conn = data.get("connection") or {}
    curr = data.get("currency") or {}
    return {
        "ip": str(data.get("ip", "")),
        "country_code": str(data.get("country_code", "")).upper(),
        "country_name": str(data.get("country", "")),
        "region": str(data.get("region", "")),
        "city": str(data.get("city", "")),
        "postal": str(data.get("postal", "")),
        "latitude": data.get("latitude"),
        "longitude": data.get("longitude"),
        "iana_timezone": str(tz.get("id", "")),
        "utc_offset_sec": int(tz.get("offset") or 0),
        "isp": str(conn.get("isp", "")),
        "org": str(conn.get("org", "")),
        "asn": f"AS{conn['asn']}" if conn.get("asn") else "",
        "currency": str(curr.get("code", "")),
        "is_proxy": False,
        "is_hosting": False,
        "provider": "ipwho.is",
    }


def _normalize_ipapi_co(data: dict[str, Any]) -> dict[str, Any] | None:
    if data.get("error") or not data.get("ip"):
        return None
    utc_str = str(data.get("utc_offset") or "+0000")
    offset_sec = 0
    if len(utc_str) == 5 and utc_str[0] in ("+", "-"):
        try:
            sign = 1 if utc_str[0] == "+" else -1
            hrs = int(utc_str[1:3])
            mins = int(utc_str[3:5])
            offset_sec = sign * (hrs * 3600 + mins * 60)
        except ValueError:
            offset_sec = 0
    return {
        "ip": str(data.get("ip", "")),
        "country_code": str(data.get("country_code", "")).upper(),
        "country_name": str(data.get("country_name", "")),
        "region": str(data.get("region", "")),
        "city": str(data.get("city", "")),
        "postal": str(data.get("postal", "")),
        "latitude": data.get("latitude"),
        "longitude": data.get("longitude"),
        "iana_timezone": str(data.get("timezone", "")),
        "utc_offset_sec": offset_sec,
        "isp": str(data.get("org", "")),
        "org": str(data.get("org", "")),
        "asn": str(data.get("asn", "")),
        "currency": str(data.get("currency", "")),
        "is_proxy": False,
        "is_hosting": False,
        "provider": "ipapi.co",
    }


def _detect_ipv6(proxies: dict[str, str] | None, timeout: float = 3.0) -> str | None:
    """Check whether outbound IPv6 is active (potential leak if VPN only routes IPv4)."""
    try:
        resp = requests.get(
            "https://api6.ipify.org?format=json",
            timeout=timeout,
            proxies=proxies,
        )
        if resp.ok:
            ip = resp.json().get("ip")
            if ip and ":" in str(ip):
                return str(ip)
    except Exception:
        pass
    return None


def detect_ip_info(
    proxy_mode: str = "system",
    custom_proxy_url: str = "",
    timeout: float = 6.0,
    check_ipv6: bool = True,
) -> dict[str, Any]:
    """
    Detect current public IP and rich geolocation metadata using multi-provider failover.

    Returns a normalized dict with keys:
      ok, ip, ipv6, ipv6_leak, country_code, country_name, region, city,
      latitude, longitude, iana_timezone, utc_offset_sec, isp, org, asn,
      currency, is_proxy, is_hosting, provider, latency_ms, checked_at, error
    """
    proxies = _build_proxies(proxy_mode, custom_proxy_url)
    headers = {"User-Agent": "IPMatcher/1.0"}
    t0 = time.perf_counter()

    providers = [
        (
            "http://ip-api.com/json/?fields=status,message,country,countryCode,regionName,city,zip,lat,lon,timezone,offset,currency,isp,org,as,proxy,hosting,query",
            _normalize_ip_api,
        ),
        ("https://ipwho.is/", _normalize_ipwhois),
        ("https://ipapi.co/json/", _normalize_ipapi_co),
    ]

    last_error = ""
    result: dict[str, Any] | None = None

    for url, parser in providers:
        try:
            resp = requests.get(url, timeout=timeout, proxies=proxies, headers=headers)
            if not resp.ok:
                last_error = f"HTTP {resp.status_code} from {url}"
                continue
            parsed = parser(resp.json())
            if parsed and parsed.get("country_code"):
                result = parsed
                break
            last_error = f"Incomplete payload from {url}"
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"

    latency_ms = int((time.perf_counter() - t0) * 1000)
    checked_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    if not result:
        return {
            "ok": False,
            "error": last_error or "Unable to reach geolocation providers",
            "ip": "",
            "ipv6": None,
            "ipv6_leak": False,
            "country_code": "",
            "country_name": "",
            "region": "",
            "city": "",
            "postal": "",
            "latitude": None,
            "longitude": None,
            "iana_timezone": "",
            "utc_offset_sec": 0,
            "isp": "",
            "org": "",
            "asn": "",
            "currency": "",
            "is_proxy": False,
            "is_hosting": False,
            "provider": "",
            "latency_ms": latency_ms,
            "checked_at": checked_at,
        }

    ipv6 = _detect_ipv6(proxies) if check_ipv6 else None
    ipv6_leak = bool(ipv6 and result["ip"] and ":" not in result["ip"])

    result.update(
        {
            "ok": True,
            "error": "",
            "ipv6": ipv6,
            "ipv6_leak": ipv6_leak,
            "latency_ms": latency_ms,
            "checked_at": checked_at,
        }
    )
    return result
