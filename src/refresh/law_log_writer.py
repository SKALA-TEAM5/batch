"""law_log INSERT helpers for refresh runs."""

from __future__ import annotations

import uuid
from typing import Any, Literal

ChangeType = Literal["added", "updated", "deleted", "none"]


def new_run_id() -> str:
    return str(uuid.uuid4())


def build_log_row(
    *,
    run_id: str,
    master_id: str,
    source_name: str,
    article_no: str | None,
    paragraph_no: str | None,
    item_no: str | None,
    prev_hash: str | None,
    new_hash: str | None,
    change_type: ChangeType,
) -> dict[str, Any]:
    return {
        "log_id": str(uuid.uuid4()),
        "run_id": run_id,
        "master_id": master_id,
        "source_name": source_name,
        "article_no": article_no,
        "paragraph_no": paragraph_no,
        "item_no": item_no,
        "prev_hash": prev_hash,
        "new_hash": new_hash,
        "change_type": change_type,
    }


def insert_sentinel_log(cur: Any, run_id: str) -> None:
    """변경 없는 배치 실행도 law_log에 기록해 백엔드가 마지막 실행 시각을 알 수 있게 한다."""
    cur.execute(
        """
        INSERT INTO legal_rag.law_log
          (log_id, run_id, master_id, source_name,
           article_no, paragraph_no, item_no,
           prev_hash, new_hash, change_type)
        VALUES
          (%(log_id)s, %(run_id)s, NULL, '__sentinel__',
           NULL, NULL, NULL,
           NULL, NULL, 'none')
        """,
        {"log_id": str(uuid.uuid4()), "run_id": run_id},
    )


def insert_law_log(cur: Any, row: dict[str, Any]) -> None:
    cur.execute(
        """
        INSERT INTO legal_rag.law_log
          (log_id, run_id, master_id, source_name,
           article_no, paragraph_no, item_no,
           prev_hash, new_hash, change_type)
        VALUES
          (%(log_id)s, %(run_id)s, %(master_id)s, %(source_name)s,
           %(article_no)s, %(paragraph_no)s, %(item_no)s,
           %(prev_hash)s, %(new_hash)s, %(change_type)s)
        """,
        row,
    )
