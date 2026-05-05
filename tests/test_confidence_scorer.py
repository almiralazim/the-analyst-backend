"""Unit tests for the confidence scoring module."""

from app.helpers.confidence_scorer import (
    ConfidenceResult,
    compute_confidence,
    _score_layer,
    _score_to_grade,
)


class TestScoreToGrade:
    def test_grade_a_at_boundary(self):
        assert _score_to_grade(0.9) == "A"

    def test_grade_a_perfect(self):
        assert _score_to_grade(1.0) == "A"

    def test_grade_b(self):
        assert _score_to_grade(0.85) == "B"

    def test_grade_b_at_boundary(self):
        assert _score_to_grade(0.8) == "B"

    def test_grade_c(self):
        assert _score_to_grade(0.75) == "C"

    def test_grade_c_at_boundary(self):
        assert _score_to_grade(0.7) == "C"

    def test_grade_d(self):
        assert _score_to_grade(0.65) == "D"

    def test_grade_d_at_boundary(self):
        assert _score_to_grade(0.6) == "D"

    def test_grade_f(self):
        assert _score_to_grade(0.59) == "F"

    def test_grade_f_zero(self):
        assert _score_to_grade(0.0) == "F"


class TestScoreLayer:
    def test_pass_returns_one(self):
        layer = {"status": "pass", "checks": 5, "failures": 0, "warnings": 0}
        assert _score_layer(layer) == 1.0

    def test_fail_returns_zero(self):
        layer = {"status": "fail", "checks": 5, "failures": 2, "warnings": 0}
        assert _score_layer(layer) == 0.0

    def test_warn_proportional_reduction(self):
        layer = {"status": "warn", "checks": 10, "failures": 0, "warnings": 2}
        # 1.0 - (2/10) * 0.5 = 1.0 - 0.1 = 0.9
        assert _score_layer(layer) == 0.9

    def test_warn_all_warnings(self):
        layer = {"status": "warn", "checks": 4, "failures": 0, "warnings": 4}
        # 1.0 - (4/4) * 0.5 = 0.5
        assert _score_layer(layer) == 0.5

    def test_warn_zero_checks_uses_one(self):
        layer = {"status": "warn", "checks": 0, "failures": 0, "warnings": 1}
        # 1.0 - (1/1) * 0.5 = 0.5
        assert _score_layer(layer) == 0.5

    def test_missing_status_defaults_to_pass(self):
        layer = {"checks": 3, "failures": 0, "warnings": 0}
        assert _score_layer(layer) == 1.0

    def test_empty_dict_defaults_to_pass(self):
        assert _score_layer({}) == 1.0


class TestComputeConfidence:
    def _all_pass_result(self):
        """Helper: all layers pass."""
        layer = {
            "status": "pass",
            "checks": 5,
            "failures": 0,
            "warnings": 0,
            "details": [],
        }
        return {
            "structural": dict(layer),
            "logical": dict(layer),
            "business_rules": dict(layer),
            "simpsons_paradox": dict(layer),
        }

    def test_all_pass_gives_perfect_score(self):
        result = compute_confidence(self._all_pass_result())
        assert result.score == 1.0
        assert result.grade == "A"

    def test_all_fail_gives_zero(self):
        layer = {
            "status": "fail",
            "checks": 5,
            "failures": 3,
            "warnings": 0,
            "details": [],
        }
        vr = {
            "structural": dict(layer),
            "logical": dict(layer),
            "business_rules": dict(layer),
            "simpsons_paradox": dict(layer),
        }
        result = compute_confidence(vr)
        assert result.score == 0.0
        assert result.grade == "F"

    def test_single_layer_fail_reduces_score(self):
        vr = self._all_pass_result()
        vr["logical"] = {
            "status": "fail",
            "checks": 5,
            "failures": 3,
            "warnings": 0,
            "details": [],
        }
        result = compute_confidence(vr)
        # logical weight is 0.30, so score = 1.0 - 0.30 = 0.70
        assert result.score == 0.7
        assert result.grade == "C"

    def test_warnings_reduce_proportionally(self):
        vr = self._all_pass_result()
        vr["structural"] = {
            "status": "warn",
            "checks": 10,
            "failures": 0,
            "warnings": 2,
            "details": [],
        }
        result = compute_confidence(vr)
        # structural layer score = 0.9, weight = 0.20
        # other layers = 1.0
        # overall = 0.9*0.20 + 1.0*0.30 + 1.0*0.30 + 1.0*0.20
        #         = 0.18 + 0.30 + 0.30 + 0.20 = 0.98
        assert abs(result.score - 0.98) < 1e-9
        assert result.grade == "A"

    def test_breakdown_contains_all_layers(self):
        result = compute_confidence(self._all_pass_result())
        assert set(result.breakdown.keys()) == {
            "structural",
            "logical",
            "business_rules",
            "simpsons_paradox",
        }

    def test_missing_layers_default_to_pass(self):
        result = compute_confidence({})
        assert result.score == 1.0
        assert result.grade == "A"

    def test_result_is_confidence_result(self):
        result = compute_confidence(self._all_pass_result())
        assert isinstance(result, ConfidenceResult)

    def test_score_clamped_to_unit_interval(self):
        result = compute_confidence(self._all_pass_result())
        assert 0.0 <= result.score <= 1.0

    def test_fail_produces_lower_score_than_warn(self):
        """A layer with critical failures scores lower than one
        with only warnings."""
        base = self._all_pass_result()

        warn_vr = dict(base)
        warn_vr["logical"] = {
            "status": "warn",
            "checks": 10,
            "failures": 0,
            "warnings": 5,
            "details": [],
        }

        fail_vr = dict(base)
        fail_vr["logical"] = {
            "status": "fail",
            "checks": 10,
            "failures": 5,
            "warnings": 0,
            "details": [],
        }

        warn_result = compute_confidence(warn_vr)
        fail_result = compute_confidence(fail_vr)
        assert fail_result.score < warn_result.score

    def test_non_dict_layer_treated_as_pass(self):
        vr = self._all_pass_result()
        vr["structural"] = "invalid"
        result = compute_confidence(vr)
        # structural treated as empty dict → pass → 1.0
        assert result.score == 1.0
