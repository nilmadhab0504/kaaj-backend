"""
Basic tests for the matching engine: eligibility, fit score, rejection reasons.
Run from backend dir: python -m pytest tests/test_matching_engine.py -v
Or: python -m unittest tests.test_matching_engine -v
"""
import unittest

from services.matching_engine import evaluate_application


def _base_application():
    return {
        "business": {
            "state": "TX",
            "industry": "Retail",
            "years_in_business": 5,
            "annual_revenue": 1_500_000,
        },
        "guarantor": {"fico_score": 720},
        "business_credit": {"paynet_score": 70},
        "loan_request": {"amount": 50_000, "equipment": {"type": "Forklift", "age_years": 3}},
    }


class TestMatchingEngine(unittest.TestCase):
    def test_eligible_single_program(self):
        """Application meets all criteria -> eligible, fit score 100."""
        business = _base_application()["business"]
        guarantor = _base_application()["guarantor"]
        business_credit = _base_application()["business_credit"]
        loan_request = _base_application()["loan_request"]
        programs = [
            {
                "id": "p1",
                "name": "Standard",
                "tier": "A",
                "criteria": {
                    "fico": {"min_score": 680},
                    "paynet": {"min_score": 60},
                    "loan_amount": {"min_amount": 10_000, "max_amount": 100_000},
                    "time_in_business": {"min_years": 2},
                },
            }
        ]
        result = evaluate_application(
            business=business,
            guarantor=guarantor,
            business_credit=business_credit,
            loan_request=loan_request,
            lender_id="l1",
            lender_name="Test Lender",
            programs=programs,
        )
        self.assertTrue(result.eligible)
        self.assertEqual(result.fit_score, 100)
        self.assertIsNotNone(result.best_program)
        self.assertEqual(result.best_program.name, "Standard")
        self.assertEqual(len(result.rejection_reasons), 0)

    def test_ineligible_fico(self):
        """FICO below minimum -> not eligible, rejection reason mentions FICO."""
        business = _base_application()["business"]
        guarantor = {"fico_score": 600}
        business_credit = _base_application()["business_credit"]
        loan_request = _base_application()["loan_request"]
        programs = [
            {
                "id": "p1",
                "name": "Standard",
                "criteria": {
                    "fico": {"min_score": 700},
                    "loan_amount": {"min_amount": 10_000, "max_amount": 100_000},
                },
            }
        ]
        result = evaluate_application(
            business=business,
            guarantor=guarantor,
            business_credit=business_credit,
            loan_request=loan_request,
            lender_id="l1",
            lender_name="Strict Lender",
            programs=programs,
        )
        self.assertFalse(result.eligible)
        self.assertIn("FICO", " ".join(result.rejection_reasons))
        self.assertIn("700", " ".join(result.rejection_reasons))
        criteria_fico = next((c for c in result.criteria_results if "FICO" in c.name), None)
        self.assertIsNotNone(criteria_fico)
        self.assertFalse(criteria_fico.met)

    def test_ineligible_loan_amount(self):
        """Loan amount outside range -> not eligible."""
        business = _base_application()["business"]
        guarantor = _base_application()["guarantor"]
        business_credit = _base_application()["business_credit"]
        loan_request = {"amount": 500_000, "equipment": {"type": "Forklift", "age_years": 3}}
        programs = [
            {
                "id": "p1",
                "name": "Standard",
                "criteria": {
                    "fico": {"min_score": 680},
                    "loan_amount": {"min_amount": 10_000, "max_amount": 100_000},
                },
            }
        ]
        result = evaluate_application(
            business=business,
            guarantor=guarantor,
            business_credit=business_credit,
            loan_request=loan_request,
            lender_id="l1",
            lender_name="Small Ticket",
            programs=programs,
        )
        self.assertFalse(result.eligible)
        self.assertTrue(any("Loan amount" in r or "500,000" in r for r in result.rejection_reasons))

    def test_ineligible_geographic(self):
        """State excluded -> not eligible."""
        business = {**_base_application()["business"], "state": "CA"}
        guarantor = _base_application()["guarantor"]
        business_credit = _base_application()["business_credit"]
        loan_request = _base_application()["loan_request"]
        programs = [
            {
                "id": "p1",
                "name": "Standard",
                "criteria": {
                    "loan_amount": {"min_amount": 10_000, "max_amount": 100_000},
                    "geographic": {"excluded_states": ["CA", "NV"]},
                },
            }
        ]
        result = evaluate_application(
            business=business,
            guarantor=guarantor,
            business_credit=business_credit,
            loan_request=loan_request,
            lender_id="l1",
            lender_name="No CA",
            programs=programs,
        )
        self.assertFalse(result.eligible)
        self.assertTrue(any("state" in r.lower() or "CA" in r for r in result.rejection_reasons))

    def test_best_program_highest_fit(self):
        """Two programs: Tier B ineligible (revenue too low), Tier A eligible -> best is Tier A."""
        business = _base_application()["business"]
        guarantor = _base_application()["guarantor"]
        business_credit = _base_application()["business_credit"]
        loan_request = _base_application()["loan_request"]
        programs = [
            {
                "id": "p1",
                "name": "Tier B",
                "tier": "B",
                "criteria": {
                    "fico": {"min_score": 650},
                    "loan_amount": {"min_amount": 10_000, "max_amount": 100_000},
                    "time_in_business": {"min_years": 2},
                    "min_revenue": 2_000_000,
                },
            },
            {
                "id": "p2",
                "name": "Tier A",
                "tier": "A",
                "criteria": {
                    "fico": {"min_score": 680},
                    "paynet": {"min_score": 65},
                    "loan_amount": {"min_amount": 10_000, "max_amount": 100_000},
                    "time_in_business": {"min_years": 2},
                    "min_revenue": 1_000_000,
                },
            },
        ]
        result = evaluate_application(
            business=business,
            guarantor=guarantor,
            business_credit=business_credit,
            loan_request=loan_request,
            lender_id="l1",
            lender_name="Multi-Tier",
            programs=programs,
        )
        self.assertTrue(result.eligible)
        self.assertIsNotNone(result.best_program)
        self.assertEqual(result.best_program.name, "Tier A")


if __name__ == "__main__":
    unittest.main()
