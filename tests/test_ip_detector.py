"""Tests for ip_detector provider normalization and failover."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from ip_matcher.ip_detector import detect_ip_info


class TestIPDetector(unittest.TestCase):
    @patch("ip_matcher.ip_detector.requests.get")
    def test_failover_to_second_provider(self, mock_get: MagicMock) -> None:
        fail_resp = MagicMock()
        fail_resp.ok = False
        fail_resp.status_code = 429

        ok_resp = MagicMock()
        ok_resp.ok = True
        ok_resp.json.return_value = {
            "success": True,
            "ip": "46.101.10.20",
            "country": "Germany",
            "country_code": "DE",
            "region": "Hesse",
            "city": "Frankfurt",
            "latitude": 50.11,
            "longitude": 8.68,
            "timezone": {"id": "Europe/Berlin", "offset": 3600},
            "connection": {"isp": "DigitalOcean", "org": "DigitalOcean", "asn": 14061},
            "currency": {"code": "EUR"},
        }

        ipv6_resp = MagicMock()
        ipv6_resp.ok = False

        mock_get.side_effect = [fail_resp, ok_resp, ipv6_resp]
        info = detect_ip_info(proxy_mode="direct", check_ipv6=True)

        self.assertTrue(info["ok"])
        self.assertEqual(info["provider"], "ipwho.is")
        self.assertEqual(info["country_code"], "DE")
        self.assertEqual(info["iana_timezone"], "Europe/Berlin")
        self.assertFalse(info["ipv6_leak"])


if __name__ == "__main__":
    unittest.main()
