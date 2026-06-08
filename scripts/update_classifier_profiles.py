"""
seed_legal_rule_profiles.json 기준으로 legal_rag.legal_rule_profiles 테이블에
모든 profile 타입을 UPSERT한다.

- classifier_profiles : 카테고리 분류용 strong/medium/negative/pair_terms
- validator_profiles  : 항목 허용/불허 판정용 allow/disallow_terms
- validator_synonyms  : 동의어 확장 (보호구→안전모/안전화 등)
- generic_item_policies: 일반 품목 예외 정책

스키마 변경 없이 데이터만 갱신 (UPSERT).
"""
import json
import os
import sys
from pathlib import Path

import psycopg

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://safety_user:safety_password@localhost:5432/safety",
)
RULE_CONFIG_PATH = Path("scripts/seed_legal_rule_profiles.json")


def _upsert_rows(cur, rows: list[tuple]) -> int:
    for row in rows:
        cur.execute(
            """
            INSERT INTO legal_rag.legal_rule_profiles
              (profile_id, profile_scope, category_code, profile_key, values_json, metadata)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (profile_scope, category_code, profile_key)
            DO UPDATE SET
              values_json = EXCLUDED.values_json,
              metadata    = EXCLUDED.metadata
            """,
            row,
        )
    return len(rows)


def upsert_classifier_profiles(target_categories: list[str] | None = None) -> None:
    config = json.loads(RULE_CONFIG_PATH.read_text(encoding="utf-8"))
    upserted = 0

    conn = psycopg.connect(DATABASE_URL)
    with conn:
        with conn.cursor() as cur:

            # ── classifier_profiles ─────────────────────────────────
            classifier_profiles: dict = config.get("classifier_profiles", {})
            if target_categories:
                classifier_profiles = {k: v for k, v in classifier_profiles.items() if k in target_categories}
            rows = []
            for category_code, profile in classifier_profiles.items():
                for profile_key, values in profile.items():
                    rows.append((
                        f"profile:classifier:{category_code}:{profile_key}",
                        "category",
                        category_code,
                        profile_key,
                        json.dumps(values, ensure_ascii=False),
                        json.dumps({"original_scope": "classifier_profile"}),
                    ))
                    print(f"  UPSERT [classifier] {category_code} / {profile_key}")
            upserted += _upsert_rows(cur, rows)

            # ── validator_profiles ──────────────────────────────────
            validator_profiles: dict = config.get("validator_profiles", {})
            if target_categories:
                validator_profiles = {k: v for k, v in validator_profiles.items() if k in target_categories}
            rows = []
            for category_code, profile in validator_profiles.items():
                for profile_key, values in profile.items():
                    rows.append((
                        f"profile:validator:{category_code}:{profile_key}",
                        "category",
                        category_code,
                        profile_key,
                        json.dumps(values, ensure_ascii=False),
                        json.dumps({"original_scope": "validator_profile"}),
                    ))
                    print(f"  UPSERT [validator] {category_code} / {profile_key}")
            upserted += _upsert_rows(cur, rows)

            # ── validator_synonyms ──────────────────────────────────
            validator_synonyms: dict = config.get("validator_synonyms", {})
            rows = []
            for synonym_key, values in validator_synonyms.items():
                rows.append((
                    f"profile:synonym:{synonym_key}",
                    "global",
                    None,
                    synonym_key,
                    json.dumps(values, ensure_ascii=False),
                    json.dumps({"original_scope": "validator_synonym"}),
                ))
                print(f"  UPSERT [synonym] {synonym_key}")
            upserted += _upsert_rows(cur, rows)

            # ── generic_item_policies ───────────────────────────────
            generic_item_policies: dict = config.get("generic_item_policies", {})
            rows = []
            for item_key, policy in generic_item_policies.items():
                rows.append((
                    f"profile:generic:{item_key}",
                    "item",
                    None,
                    item_key,
                    json.dumps(policy, ensure_ascii=False),
                    json.dumps({"original_scope": "generic_item_policy"}),
                ))
                print(f"  UPSERT [generic] {item_key}")
            upserted += _upsert_rows(cur, rows)

    conn.close()
    print(f"\n완료: {upserted}개 UPSERT")


if __name__ == "__main__":
    targets = sys.argv[1:] or None
    print(f"대상 카테고리: {targets or '전체'}")
    upsert_classifier_profiles(target_categories=targets)
