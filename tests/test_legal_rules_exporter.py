"""
batch/src/repositories/legal_rules_exporter.py 유닛 테스트

대상 함수:
  - _infer_allowed_from_answer
  - _split_mixed_answer
  - _is_valid_segment
  - _infer_rule_type
  - _extract_qa_keyword

DB / Qdrant / 외부 의존성 없이 순수 함수 레벨에서 검증한다.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from src.repositories.legal_rules_exporter import (
    _infer_allowed_from_answer,
    _is_valid_segment,
    _infer_rule_type,
    _extract_qa_keyword,
    _split_mixed_answer,
)


# ── _infer_allowed_from_answer ────────────────────────────────────────────────

class TestInferAllowedFromAnswer:

    def test_allow_only(self):
        text = "안전모 구입은 보호구 항목으로 사용이 가능함."
        allowed, mode = _infer_allowed_from_answer(text)
        assert allowed is True
        assert mode == "allow_only"

    def test_disallow_only(self):
        text = "사무실 집기 구입은 산업안전보건관리비 사용이 불가함."
        allowed, mode = _infer_allowed_from_answer(text)
        assert allowed is False
        assert mode == "disallow_only"

    def test_mixed_fire_extinguisher(self):
        """핵심 버그 케이스 — 사무용 소화기"""
        text = (
            "화재 위험작업(용접, 전기, 인화성물질 취급 등) 중 근로자 보호 목적이 아닌 "
            "분전반, 사무실 등에 설치하기 위해 구입하는 소화기에 대해서는 안전시설비 "
            "항목으로 사용이 불가할 것이나,\n"
            "- 용접작업 등 화재 위험작업 시 사용하는 소화기의 구입·임대 비용은 "
            "안전시설비 항목으로 사용이 가능함"
        )
        allowed, mode = _infer_allowed_from_answer(text)
        assert allowed is None
        assert mode == "mixed"

    def test_mixed_container(self):
        """허용 선행 → 불허 후행"""
        text = "교육장 사용 목적으로 임대하는 컨테이너 임대 비용은 사용 가능하나, 컨테이너 구매에 소요되는 비용은 사용 불가"
        allowed, mode = _infer_allowed_from_answer(text)
        assert allowed is None
        assert mode == "mixed"

    def test_mixed_salary_with_daman(self):
        """가능함. - 다만, 불가함 패턴"""
        text = (
            "임금 전액이 해당되므로 안전보건관리자 임금 항목으로 사용이 가능함.\n"
            "- 다만, 제세공과금의 사업주 부담분은 임금이 아니므로 사용이 불가함."
        )
        allowed, mode = _infer_allowed_from_answer(text)
        assert allowed is None
        assert mode == "mixed"

    def test_mixed_inspection_bulgahamy(self):
        """불가하며 → 가능 패턴"""
        text = (
            "기계장치의 원활한 작동 등 다른 목적을 포함하고 있는 검사는 불가하며,\n"
            "- 건설현장 근로자의 산재예방을 목적으로 추가 실시하는 검사는 사용이 가능함."
        )
        allowed, mode = _infer_allowed_from_answer(text)
        assert allowed is None
        assert mode == "mixed"

    def test_mixed_principle_disallow_exception_allow(self):
        """원칙불가 + 예외허용 패턴"""
        text = (
            "원칙적으로 산업안전보건관리비로 사용이 불가하나, "
            "위험성 평가 등을 통해 노사협의체에서 결정한 경우에는 예외적으로 사용이 가능함"
        )
        allowed, mode = _infer_allowed_from_answer(text)
        assert allowed is None
        assert mode == "mixed"

    def test_mixed_regulation_clause_then_disallow(self):
        """가능하다고 규정하고 있으나 → 불가 패턴"""
        text = (
            "산업재해 예방이 주된 목적인 교육을 실시하기 위해 소요되는 비용은 "
            "안전보건교육비로 사용이 가능하다고 규정하고 있으나,\n"
            "- 간호사 보수교육의 경우 자격유지 목적으로 판단되어 사용이 불가함."
        )
        allowed, mode = _infer_allowed_from_answer(text)
        assert allowed is None
        assert mode == "mixed"

    def test_undetermined(self):
        text = "귀 질의만으로 구체적인 사실관계를 알 수 없어 정확한 답변을 드리기 어려우나"
        allowed, mode = _infer_allowed_from_answer(text)
        assert allowed is None
        assert mode == "undetermined"

    def test_disallow_bulgahamy_token(self):
        """불가하며 단독 불허 케이스"""
        text = "해당 항목은 다른 법령에서 규정된 의무사항으로 산업안전보건관리비 사용이 불가하며 이를 중복 계상할 수 없다."
        allowed, mode = _infer_allowed_from_answer(text)
        assert allowed is False
        assert mode == "disallow_only"

    def test_disallow_cannot_use_token(self):
        """사용할 수 없 토큰"""
        text = "해당 비용은 공사원가로 계상되므로 산업안전보건관리비로 사용할 수 없도록 규정하고 있음."
        allowed, mode = _infer_allowed_from_answer(text)
        assert allowed is False
        assert mode == "disallow_only"

    def test_disallow_not_허용_token(self):
        """허용하지 않고 있음 토큰"""
        text = "피복비용은 원칙적으로 산업안전보건관리비 사용을 허용하지 않고 있음."
        allowed, mode = _infer_allowed_from_answer(text)
        assert allowed is False
        assert mode == "disallow_only"


# ── _split_mixed_answer ───────────────────────────────────────────────────────

class TestSplitMixedAnswer:

    def test_fire_extinguisher_split(self):
        """불가할 것이나 → 분리 후 disallow/allow 순서"""
        text = (
            "분전반, 사무실 등에 설치하기 위해 구입하는 소화기에 대해서는 "
            "안전시설비 항목으로 사용이 불가할 것이나,\n"
            "- 용접작업 등 화재 위험작업 시 사용하는 소화기의 구입·임대 비용은 "
            "안전시설비 항목으로 사용이 가능함"
        )
        segs = _split_mixed_answer(text)
        assert len(segs) == 2
        a0, _ = _infer_allowed_from_answer(segs[0])
        a1, _ = _infer_allowed_from_answer(segs[1])
        assert a0 is False
        assert a1 is True

    def test_container_split(self):
        """가능하나 → 분리 후 allow/disallow 순서"""
        text = "임대 비용은 사용 가능하나, 구매 비용은 사용 불가"
        segs = _split_mixed_answer(text)
        assert len(segs) == 2
        a0, _ = _infer_allowed_from_answer(segs[0])
        a1, _ = _infer_allowed_from_answer(segs[1])
        assert a0 is True
        assert a1 is False

    def test_daman_split(self):
        """\n- 다만 패턴 분리"""
        text = (
            "안전보건관리자 임금 항목으로 사용이 가능함.\n"
            "- 다만, 사업주 부담분은 임금이 아니므로 사용이 불가함."
        )
        segs = _split_mixed_answer(text)
        assert len(segs) == 2
        a0, _ = _infer_allowed_from_answer(segs[0])
        a1, _ = _infer_allowed_from_answer(segs[1])
        assert a0 is True
        assert a1 is False

    def test_bulgahamy_split(self):
        """불가하며 패턴 분리"""
        text = (
            "의무사항 이행을 위해 수행되는 검사는 불가하며,\n"
            "- 산재예방 목적으로 추가 실시하는 검사는 사용이 가능함."
        )
        segs = _split_mixed_answer(text)
        assert len(segs) == 2
        a0, _ = _infer_allowed_from_answer(segs[0])
        a1, _ = _infer_allowed_from_answer(segs[1])
        assert a0 is False
        assert a1 is True

    def test_no_connector_returns_empty(self):
        """역접 접속사 없으면 빈 리스트"""
        text = "안전모 구입은 보호구 항목으로 사용이 가능함."
        segs = _split_mixed_answer(text)
        assert segs == []

    def test_linebreak_in_connector(self):
        """줄바꿈이 접속사 중간에 끼는 경우 (qa:52 패턴) — normalize 후 매칭"""
        text = (
            "교육 진행 중 제공하는 음료·중식비는 사용이 가능할\n"
            "것이나, 그 외 경우는 사용이 불가함."
        )
        segs = _split_mixed_answer(text)
        assert len(segs) == 2
        a0, _ = _infer_allowed_from_answer(segs[0])
        a1, _ = _infer_allowed_from_answer(segs[1])
        assert a0 is True
        assert a1 is False

    def test_asterisk_note_split(self):
        """별표 주석 구분자 패턴 (qa:16 패턴: 가능함 * 단서는 불가함)"""
        text = (
            "도로 등 작업 중 근로자를 보호하기 위한 목적의 교통안전시설물 등은 "
            "산업안전보건관리비(안전시설비 항목)로 사용이 가능함\n"
            "* 공사금액에 안전관리비가 반영되어 있는 경우라면 해당 시설 설치비용에 "
            "대해서는 산업안전보건관리비 사용이 불가함"
        )
        segs = _split_mixed_answer(text)
        assert len(segs) == 2
        a0, _ = _infer_allowed_from_answer(segs[0])
        a1, _ = _infer_allowed_from_answer(segs[1])
        assert a0 is True
        assert a1 is False


# ── _is_valid_segment ─────────────────────────────────────────────────────────

class TestIsValidSegment:

    def test_valid_allow_segment(self):
        assert _is_valid_segment("용접작업 시 소화기 구입 비용은 안전시설비 항목으로 사용이 가능함") is True

    def test_valid_disallow_segment(self):
        assert _is_valid_segment("사무실 소화기 구입은 안전시설비 항목으로 사용이 불가함") is True

    def test_too_short(self):
        assert _is_valid_segment("가능함") is False

    def test_undetermined_phrase_skip(self):
        assert _is_valid_segment("귀 질의만으로 정확한 답변을 드리기 어려우나 사용이 가능함") is False

    def test_pure_legal_citation(self):
        """판정 토큰 없는 순수 법령 인용 → 스킵"""
        assert _is_valid_segment("건설업 산업안전보건관리비 계상 및 사용기준 제7조제1항제2호에 따르면") is False


# ── _infer_rule_type ──────────────────────────────────────────────────────────

class TestInferRuleType:

    def test_allowed(self):
        rule_type, allowed, limit_pct = _infer_rule_type("안전난간 설치는 안전시설비로 사용이 가능함.")
        assert rule_type == "rule_like_allowed"
        assert allowed is True
        assert limit_pct is None

    def test_disallowed(self):
        rule_type, allowed, limit_pct = _infer_rule_type("사무용 집기는 산업안전보건관리비 사용이 불가함.")
        assert rule_type == "rule_like_disallowed"
        assert allowed is False

    def test_mixed_returns_mixed(self):
        """혼재 텍스트 → rule_like_mixed, allowed=None"""
        text = (
            "화재 위험작업 시 소화기는 사용이 가능하나 "
            "사무실 소화기는 사용이 불가함."
        )
        rule_type, allowed, limit_pct = _infer_rule_type(text)
        assert rule_type == "rule_like_mixed"
        assert allowed is None

    def test_undetermined(self):
        rule_type, allowed, limit_pct = _infer_rule_type("법 제73조에 따른 건설재해예방전문지도기관의 지도에 대한 대가.")
        assert rule_type == "rule_like"
        assert allowed is None

    def test_limit(self):
        rule_type, allowed, limit_pct = _infer_rule_type(
            "스마트 안전장비는 산안비 총액의 100분의 5를 초과할 수 없다."
        )
        assert rule_type == "rule_like_limit"
        assert limit_pct is not None


# ── _extract_qa_keyword ───────────────────────────────────────────────────────

class TestExtractQaKeyword:

    def test_allow_direction(self):
        q = "안전모 구입비를 보호구 항목으로 사용 가능한지"
        assert _extract_qa_keyword(q) == "안전모 구입비를 보호구 항목으로"

    def test_disallow_direction(self):
        q = "사무용 소화기를 안전시설비 항목으로 사용 불가한지"
        result = _extract_qa_keyword(q)
        assert "사무용 소화기" in result
        assert "사용 불가한지" not in result

    def test_cannot_use_direction(self):
        q = "컨테이너 구매 비용을 교육비 항목으로 사용할 수 없는지"
        result = _extract_qa_keyword(q)
        assert "컨테이너 구매 비용" in result

    def test_80char_limit(self):
        q = "매우 긴 질문으로서 안전보건관리비 항목 중 특정 장비의 구입비용을 보호구 항목으로 사용 가능한지 여부에 대해 문의드립니다"
        result = _extract_qa_keyword(q)
        assert len(result) <= 80

    def test_empty_question(self):
        assert _extract_qa_keyword("") == ""

    def test_no_marker(self):
        """마커 없으면 전체 반환 (80자 제한)"""
        q = "안전관리자 임금 관련 질문"
        result = _extract_qa_keyword(q)
        assert result == q
