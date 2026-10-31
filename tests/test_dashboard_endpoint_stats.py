from __future__ import annotations

import unittest
from local_ai_hub.dashboard import DASHBOARD_HTML


class DashboardEndpointStatsTest(unittest.TestCase):
    def test_dashboard_contains_endpoint_stats_elements(self) -> None:
        self.assertIn('id="endpointStatsSection"', DASHBOARD_HTML)
        self.assertIn('id="epStatsProjectSelect"', DASHBOARD_HTML)
        self.assertIn('id="epStatsTypeSelect"', DASHBOARD_HTML)
        self.assertIn('id="epStatsSortSelect"', DASHBOARD_HTML)
        self.assertIn('id="epStatsResetBtn"', DASHBOARD_HTML)
        self.assertIn("loadEndpointStatsView", DASHBOARD_HTML)
        self.assertIn("renderEndpointStatsView", DASHBOARD_HTML)
        self.assertIn("/api/telemetry/endpoint-stats", DASHBOARD_HTML)


if __name__ == "__main__":
    unittest.main()
