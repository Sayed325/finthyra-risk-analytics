#Author: @ShoumikDutta
import unittest
from scripts.historical_backfill import run_backfill


class TestHistoricalBackfill(unittest.TestCase):

    def test_run_backfill_structure(self):
        result = run_backfill(start_date="2024-01-01")

        self.assertIsInstance(result, dict)

        self.assertIn("tickers_processed", result)
        self.assertIn("total_rows", result)
        self.assertIn("failures", result)

    def test_non_negative_rows(self):
        result = run_backfill(start_date="2024-01-01")

        self.assertGreaterEqual(result["tickers_processed"], 0)
        self.assertGreaterEqual(result["total_rows"], 0)

    def test_failures_type(self):
        result = run_backfill(start_date="2024-01-01")

        self.assertIsInstance(result["failures"], list)


if __name__ == "__main__":
    unittest.main()