"""Tests for matcher_engine scoring, mismatch detection, and diff planning."""

from __future__ import annotations

import unittest

from ip_matcher.config import AppSettings
from ip_matcher.matcher_engine import evaluate_alignment


class TestMatcherEngine(unittest.TestCase):
    def test_perfect_match_scores_100(self) -> None:
        settings = AppSettings(sync_dns=False)
        ip_info = {
            "ok": True,
            "ip": "185.20.1.1",
            "country_code": "DE",
            "country_name": "Germany",
            "iana_timezone": "Europe/Berlin",
            "utc_offset_sec": 3600,
            "currency": "EUR",
            "ipv6": None,
            "ipv6_leak": False,
        }
        sys_state = {
            "timezone_id": "W. Europe Standard Time",
            "utc_offset_sec": 3600,
            "utc_offset_str": "UTC+01:00",
            "geo_id": 94,
            "geo_country_code": "DE",
            "geo_country_name": "Germany",
            "culture": "de-DE",
            "primary_language": "de-DE",
            "language_list": [{"language_tag": "de-DE", "input_tips": []}],
            "location_leak_blocked": True,
            "dns": {"all_dns": ["1.1.1.1"], "risk": "safe", "notes": []},
        }
        report = evaluate_alignment(ip_info, sys_state, settings)
        self.assertTrue(report["ready"])
        self.assertEqual(report["score"], 100)
        self.assertEqual(report["risk_level"], "safe")
        self.assertEqual(report["mismatch_count"], 0)
        self.assertEqual(report["planned_changes"], [])

    def test_iran_system_with_us_ip_flags_critical(self) -> None:
        settings = AppSettings(sync_dns=True, keep_persian_keyboard=True)
        ip_info = {
            "ok": True,
            "ip": "23.1.2.3",
            "country_code": "US",
            "country_name": "United States",
            "iana_timezone": "America/New_York",
            "utc_offset_sec": -18000,
            "currency": "USD",
            "ipv6": "2001:db8::1",
            "ipv6_leak": True,
        }
        sys_state = {
            "timezone_id": "Iran Standard Time",
            "utc_offset_sec": 12600,
            "utc_offset_str": "UTC+03:30",
            "geo_id": 116,
            "geo_country_code": "IR",
            "geo_country_name": "Iran",
            "culture": "fa-IR",
            "primary_language": "fa-IR",
            "language_list": [{"language_tag": "fa-IR", "input_tips": ["0429:00000429"]}],
            "location_leak_blocked": False,
            "dns": {"all_dns": ["178.22.122.100"], "risk": "high", "notes": ["Iranian DNS"]},
        }
        report = evaluate_alignment(ip_info, sys_state, settings)
        self.assertEqual(report["risk_level"], "critical")
        self.assertLess(report["score"], 30)
        keys = {c["key"] for c in report["planned_changes"]}
        self.assertEqual(keys, {"timezone", "geo_id", "culture", "language", "location_privacy", "dns"})


if __name__ == "__main__":
    unittest.main()
