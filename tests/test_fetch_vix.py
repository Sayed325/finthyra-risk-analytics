import unittest

from src.ingestion.fetch_vix import fetch_vix


class TestFetchVIX(unittest.TestCase):

    def test_output_structure(self):
        result = fetch_vix()

        self.assertIsInstance(result, dict)
        self.assertIn("rows_inserted", result)
        self.assertIn("latest_value", result)

    def test_rows_non_negative(self):
        result = fetch_vix()

        self.assertGreaterEqual(result["rows_inserted"], 0)

    def test_latest_value_type(self):
        result = fetch_vix()

        self.assertTrue(
            result["latest_value"] is None or isinstance(result["latest_value"], float)
        )


if __name__ == "__main__":
    unittest.main()