import unittest

from src.ingestion.fetch_macro_data import fetch_macro_data


class TestFetchMacroData(unittest.TestCase):

    def test_output_structure(self):
        result = fetch_macro_data()

        self.assertIsInstance(result, dict)
        self.assertIn("indicators_processed", result)
        self.assertIn("rows_inserted", result)
        self.assertIn("failures", result)

    def test_non_negative_values(self):
        result = fetch_macro_data()

        self.assertGreaterEqual(result["indicators_processed"], 0)
        self.assertGreaterEqual(result["rows_inserted"], 0)

    def test_failures_type(self):
        result = fetch_macro_data()

        self.assertIsInstance(result["failures"], list)


if __name__ == "__main__":
    unittest.main()