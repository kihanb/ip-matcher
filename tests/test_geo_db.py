"""Tests for geo_db mappings and Windows timezone validity."""

from __future__ import annotations

import subprocess
import unittest

from ip_matcher.geo_db import (
    COUNTRY_PROFILES,
    IANA_TO_WINDOWS_TZ,
    OFFSET_TO_WINDOWS_TZ,
    iana_to_windows_timezone,
    resolve_target_profile,
)


class TestGeoDB(unittest.TestCase):
    def test_all_windows_tz_ids_exist_in_tzutil(self) -> None:
        out = subprocess.check_output(["tzutil", "/l"], text=True, encoding="utf-8", errors="replace")
        valid_ids = {
            line.strip()
            for line in out.splitlines()
            if line.strip() and not line.strip().startswith("(UTC")
        }
        for iana, win_tz in IANA_TO_WINDOWS_TZ.items():
            self.assertIn(win_tz, valid_ids, f"Invalid Windows TZ for {iana}: {win_tz}")
        for offset, win_tz in OFFSET_TO_WINDOWS_TZ.items():
            self.assertIn(win_tz, valid_ids, f"Invalid Windows TZ for offset {offset}: {win_tz}")
        for code, info in COUNTRY_PROFILES.items():
            self.assertIn(
                info["default_tz"],
                valid_ids,
                f"Invalid default_tz for {code}: {info['default_tz']}",
            )

    def test_resolve_target_profile_germany(self) -> None:
        target = resolve_target_profile(
            {
                "country_code": "DE",
                "country_name": "Germany",
                "iana_timezone": "Europe/Berlin",
                "utc_offset_sec": 3600,
                "city": "Frankfurt",
                "latitude": 50.11,
                "longitude": 8.68,
            }
        )
        self.assertEqual(target["geo_id"], 94)
        self.assertEqual(target["windows_tz"], "W. Europe Standard Time")
        self.assertEqual(target["culture"], "de-DE")
        self.assertEqual(target["currency"], "EUR")

    def test_iana_fallback_by_offset(self) -> None:
        tz = iana_to_windows_timezone("Unknown/Zone", offset_sec=12600)
        self.assertEqual(tz, "Iran Standard Time")


if __name__ == "__main__":
    unittest.main()
