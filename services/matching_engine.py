"""
Evaluates a loan application against lender program criteria.
Produces eligibility, fit score, best program, rejection reasons, and per-criterion results.
All inputs are normalized to snake_case at entry; internal logic uses snake_case only.
"""
from __future__ import annotations

from typing import Any

from schemas.lender import CriterionResultSchema, LenderMatchResultSchema
from utils.case import dict_keys_to_snake


def evaluate_application(
    business: dict[str, Any],
    guarantor: dict[str, Any],
    business_credit: dict[str, Any] | None,
    loan_request: dict[str, Any],
    lender_id: str,
    lender_name: str,
    programs: list[dict[str, Any]],
) -> LenderMatchResultSchema:
    """
    Evaluate application against all programs of one lender.
    Returns the best eligible program (highest fit score) or ineligible with reasons.
    Accepts business/guarantor/loan_request/criteria in either snake_case or camelCase; normalizes to snake_case.
    """
    business = dict_keys_to_snake(business) if business else {}
    guarantor = dict_keys_to_snake(guarantor) if guarantor else {}
    business_credit = dict_keys_to_snake(business_credit) if business_credit else None
    loan_request = dict_keys_to_snake(loan_request) if loan_request else {}
    programs = [dict_keys_to_snake({**p, "criteria": p.get("criteria") or {}}) for p in programs]

    best: LenderMatchResultSchema | None = None
    all_rejection_reasons: list[str] = []

    for program in programs:
        result = _evaluate_program(
            business,
            guarantor,
            business_credit,
            loan_request,
            lender_id,
            lender_name,
            program,
        )
        if result.eligible and (best is None or result.fit_score > best.fit_score):
            best = result
        if not result.eligible:
            all_rejection_reasons.extend(result.rejection_reasons)

    if best is not None:
        return best
    # No eligible program: return first program's result with combined rejection reasons
    first = _evaluate_program(
        business,
        guarantor,
        business_credit,
        loan_request,
        lender_id,
        lender_name,
        programs[0],
    )
    return LenderMatchResultSchema(
        lender_id=first.lender_id,
        lender_name=first.lender_name,
        eligible=False,
        fit_score=first.fit_score,
        best_program=None,
        rejection_reasons=list(dict.fromkeys(all_rejection_reasons)),
        criteria_results=first.criteria_results,
    )


def _evaluate_program(
    business: dict[str, Any],
    guarantor: dict[str, Any],
    business_credit: dict[str, Any] | None,
    loan_request: dict[str, Any],
    lender_id: str,
    lender_name: str,
    program: dict[str, Any],
) -> LenderMatchResultSchema:
    criteria = program.get("criteria") or {}
    criteria_results: list[CriterionResultSchema] = []
    rejection_reasons: list[str] = []
    score_components: list[float] = []

    fico = guarantor.get("fico_score")
    if fico is None:
        fico = 0
    fico_crit = criteria.get("fico")
    if fico_crit:
        min_fico = fico_crit.get("min_score")
        max_fico = fico_crit.get("max_score")
        tiered = fico_crit.get("tiered")
        if tiered:
            met = any((t.get("min_score") or 0) <= fico for t in tiered)
            req_str = "; ".join(f"≥{t.get('min_score')}" for t in tiered)
        else:
            met = (min_fico is None or fico >= min_fico) and (max_fico is None or fico <= max_fico)
            req_str = f"≥ {min_fico}" if min_fico is not None else ""
            if max_fico is not None:
                req_str += f", ≤ {max_fico}"
        criteria_results.append(
            CriterionResultSchema(
                name="FICO Score",
                met=met,
                reason=f"Minimum required score is {min_fico or 'N/A'} but borrower's score is {fico}" if not met else f"Meets minimum {min_fico or 'N/A'}",
                expected=req_str or None,
                actual=str(fico),
            )
        )
        score_components.append(100.0 if met else 0.0)
        if not met:
            rejection_reasons.append(f"FICO score {fico} below minimum required {min_fico}")

    paynet = business_credit.get("paynet_score") if business_credit else None
    paynet_crit = criteria.get("paynet")
    if paynet_crit and paynet is not None:
        min_paynet = paynet_crit.get("min_score")
        max_paynet = paynet_crit.get("max_score")
        met = (min_paynet is None or paynet >= min_paynet) and (max_paynet is None or paynet <= max_paynet)
        req_str = (f"≥ {min_paynet}" if min_paynet is not None else "") + (f", ≤ {max_paynet}" if max_paynet is not None else "")
        criteria_results.append(
            CriterionResultSchema(
                name="PayNet Score",
                met=met,
                reason=f"Required PayNet {req_str}; actual {paynet}" if not met else f"Meets PayNet requirement",
                expected=req_str or None,
                actual=str(paynet),
            )
        )
        score_components.append(100.0 if met else 0.0)
        if not met:
            rejection_reasons.append(f"PayNet score {paynet} does not meet requirement {req_str}")
    elif paynet_crit and paynet is None:
        criteria_results.append(
            CriterionResultSchema(name="PayNet Score", met=False, reason="PayNet score not provided", expected="Required", actual="N/A")
        )
        rejection_reasons.append("PayNet score not provided")
        score_components.append(0.0)

    amount = loan_request.get("amount") or 0
    loan_amt = criteria.get("loan_amount") or {}
    min_amt = loan_amt.get("min_amount") or 0
    max_amt = loan_amt.get("max_amount") or 0
    met = min_amt <= amount <= max_amt
    criteria_results.append(
        CriterionResultSchema(
            name="Loan Amount",
            met=met,
            reason=f"Loan amount ${amount:,} must be between ${min_amt:,} and ${max_amt:,}" if not met else f"Within ${min_amt:,}–${max_amt:,}",
            expected=f"${min_amt:,} – ${max_amt:,}",
            actual=f"${amount:,}",
        )
    )
    score_components.append(100.0 if met else 0.0)
    if not met:
        rejection_reasons.append(f"Loan amount ${amount:,} outside range ${min_amt:,}–${max_amt:,}")

    yib = business.get("years_in_business")
    if yib is None:
        yib = 0
    tib_crit = criteria.get("time_in_business")
    if tib_crit:
        min_years = tib_crit.get("min_years") or 0
        met = yib >= min_years
        criteria_results.append(
            CriterionResultSchema(
                name="Time in Business",
                met=met,
                reason=f"Minimum {min_years} years required; business has {yib} years" if not met else f"{yib} years ≥ {min_years} years",
                expected=f"≥ {min_years} years",
                actual=f"{yib} years",
            )
        )
        score_components.append(100.0 if met else 0.0)
        if not met:
            rejection_reasons.append(f"Time in business {yib} years below minimum {min_years}")

    state = business.get("state") or ""
    geo = criteria.get("geographic")
    if geo:
        allowed = geo.get("allowed_states") or []
        excluded = geo.get("excluded_states") or []
        if allowed:
            met = state in allowed
            criteria_results.append(
                CriterionResultSchema(
                    name="State",
                    met=met,
                    reason=f"State {state} not in allowed list" if not met else f"State {state} allowed",
                    expected=", ".join(allowed),
                    actual=state,
                )
            )
        elif excluded:
            met = state not in excluded
            criteria_results.append(
                CriterionResultSchema(
                    name="State",
                    met=met,
                    reason=f"State {state} is excluded" if not met else f"State {state} not excluded",
                    expected="Excluded: " + ", ".join(excluded),
                    actual=state,
                )
            )
        if allowed or excluded:
            score_components.append(100.0 if met else 0.0)
            if not met:
                rejection_reasons.append(f"Geographic restriction: state {state}")

    industry = business.get("industry") or ""
    ind_crit = criteria.get("industry")
    if ind_crit:
        excluded = ind_crit.get("excluded_industries") or []
        allowed = ind_crit.get("allowed_industries") or []
        if excluded:
            met = industry not in excluded
            criteria_results.append(
                CriterionResultSchema(
                    name="Industry",
                    met=met,
                    reason=f"Industry {industry} is excluded" if not met else f"Industry {industry} not excluded",
                    expected="Excludes: " + ", ".join(excluded),
                    actual=industry,
                )
            )
        elif allowed:
            met = industry in allowed
            criteria_results.append(
                CriterionResultSchema(
                    name="Industry",
                    met=met,
                    reason=f"Industry {industry} not in allowed list" if not met else f"Industry {industry} allowed",
                    expected=", ".join(allowed),
                    actual=industry,
                )
            )
        if excluded or allowed:
            score_components.append(100.0 if met else 0.0)
            if not met:
                rejection_reasons.append(f"Industry {industry} not permitted")

    equip = loan_request.get("equipment") or {}
    equip_type = equip.get("type") or ""
    equip_age = equip.get("age_years")
    equip_crit = criteria.get("equipment")
    if equip_crit:
        max_age = equip_crit.get("max_equipment_age_years")
        excluded = equip_crit.get("excluded_types") or []
        allowed = equip_crit.get("allowed_types") or []
        met = True
        if excluded and equip_type in excluded:
            met = False
            rejection_reasons.append(f"Equipment type {equip_type} is excluded")
        if allowed and equip_type not in allowed:
            met = False
            rejection_reasons.append(f"Equipment type {equip_type} not in allowed list")
        if max_age is not None and equip_age is not None and equip_age > max_age:
            met = False
            rejection_reasons.append(f"Equipment age {equip_age} years exceeds maximum {max_age}")
        reason = "Meets equipment criteria" if met else "Equipment type or age does not meet criteria"
        criteria_results.append(
            CriterionResultSchema(
                name="Equipment",
                met=met,
                reason=reason,
                expected=f"Max age: {max_age} years" if max_age is not None else ("Excluded: " + ", ".join(excluded) if excluded else "Allowed: " + ", ".join(allowed) if allowed else ""),
                actual=f"{equip_type}" + (f", {equip_age} years" if equip_age is not None else ""),
            )
        )
        score_components.append(100.0 if met else 0.0)

    revenue = business.get("annual_revenue") or 0
    min_rev = criteria.get("min_revenue")
    if min_rev is not None:
        met = revenue >= min_rev
        criteria_results.append(
            CriterionResultSchema(
                name="Minimum Revenue",
                met=met,
                reason=f"Annual revenue ${revenue:,} below minimum ${min_rev:,}" if not met else f"Revenue meets minimum ${min_rev:,}",
                expected=f"≥ ${min_rev:,}",
                actual=f"${revenue:,}",
            )
        )
        score_components.append(100.0 if met else 0.0)
        if not met:
            rejection_reasons.append(f"Revenue ${revenue:,} below minimum ${min_rev:,}")

    fit_score = int(sum(score_components) / len(score_components)) if score_components else 0
    eligible = len(rejection_reasons) == 0

    best_program = None
    if eligible:
        best_program = {
            "id": program.get("id", ""),
            "name": program.get("name", ""),
            "tier": program.get("tier"),
        }

    return LenderMatchResultSchema(
        lender_id=lender_id,
        lender_name=lender_name,
        eligible=eligible,
        fit_score=min(100, fit_score),
        best_program=best_program,
        rejection_reasons=rejection_reasons,
        criteria_results=criteria_results,
    )
