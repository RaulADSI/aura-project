import os
import sys
import unittest
import pandas as pd

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.main import run_aura_flow


class TestMainOrchestration(unittest.TestCase):

    def setUp(self):
        self.excel_path = "data/04_output/Final_Triple_Match_Audit.xlsx"
        self.email_path = "data/04_output/Email_Summary.txt"

    def test_e2e_happy_path_billable(self):
        sample_payload = [
            {
                "ocr_file": "sample.pdf",
                "utility_vendor": "GEORGIA POWER",
                "service_address": "-> 1414 Euclid Ave - 1414 Euclid Ave Atlanta, GA 30307",
                "account_number": "97737-48323",
                "current_cycle_charges": 250.00,
                "service_start": "2026-01-01",
                "service_end": "2026-01-30",
            }
        ]
        run_aura_flow(sample_payload)

        self.assertTrue(os.path.exists(self.excel_path))
        self.assertTrue(os.path.exists(self.email_path))

        df_full = pd.read_excel(self.excel_path, sheet_name="Full_Audit_Trail")
        self.assertEqual(len(df_full), 1)

    def test_e2e_owner_expense(self):
        sample_payload = [
            {
                "ocr_file": "sample_owner.pdf",
                "utility_vendor": "GEORGIA POWER",
                "service_address": "-> 1414 Euclid Ave - 1414 Euclid Ave Atlanta, GA 30307",
                "account_number": "97737-48323",
                "current_cycle_charges": 100.00,
                "service_start": "2026-01-01",
                "service_end": "2026-01-30",
            }
        ]
        run_aura_flow(sample_payload)

        df_full = pd.read_excel(self.excel_path, sheet_name="Full_Audit_Trail")
        self.assertEqual(len(df_full), 1)

    def test_e2e_invalid_service_period_anomaly(self):
        sample_payload = [
            {
                "ocr_file": "sample_invalid.pdf",
                "utility_vendor": "GEORGIA POWER",
                "service_address": "-> 1414 Euclid Ave - 1414 Euclid Ave Atlanta, GA 30307",
                "account_number": "97737-48323",
                "current_cycle_charges": 150.00,
                "service_start": "2026-01-30",
                "service_end": "2026-01-01",  # Inverted dates
            }
        ]
        run_aura_flow(sample_payload)

        df_full = pd.read_excel(self.excel_path, sheet_name="Full_Audit_Trail")
        self.assertEqual(len(df_full), 1)
        row = df_full.iloc[0]
        self.assertEqual(row["Status"], "ANOMALY_DETECTED")
        self.assertEqual(row["Calculated_BillBack"], 0.00)


if __name__ == "__main__":
    unittest.main()
