# --------------------------------------------------------------------------
# Qdrant 적재 상태 진단 스크립트
#
# 실행:
#   uv run python scripts/inspect_qdrant.py
#   uv run python scripts/inspect_qdrant.py --query "안전모"
#   uv run python scripts/inspect_qdrant.py --sample 5
# --------------------------------------------------------------------------
"""
Qdrant 컬렉션 내 청크 현황을 보여줍니다.

출력:
  1. 전체 청크 수 및 소스별 분포
  2. 소스별 샘플 청크 (page_content 앞 200자 + metadata)
  3. --query 지정 시 실제 검색 결과 추적
"""

import argparse
import os
from collections import defaultdict

from dotenv import load_dotenv

load_dotenv()

from qdrant_client import QdrantClient

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
COLLECTION  = os.getenv("QDRANT_COLLECTION", "legal_documents")
BATCH       = 100


def _scroll_all(client: QdrantClient) -> list[dict]:
    """컬렉션 전체 포인트를 페이지네이션으로 수집."""
    points = []
    offset = None
    while True:
        batch, next_offset = client.scroll(
            collection_name=COLLECTION,
            limit=BATCH,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        points.extend(batch)
        if next_offset is None:
            break
        offset = next_offset
    return points


def show_distribution(points: list) -> dict[str, list]:
    """소스별 청크 분포 출력."""
    by_source: dict[str, list] = defaultdict(list)
    by_source_type: dict[str, int] = defaultdict(int)
    no_chunk_id = 0

    for p in points:
        meta    = p.payload.get("metadata", {})
        source  = meta.get("source", p.payload.get("source", "unknown"))
        stype   = meta.get("source_type", "unknown")
        cid     = meta.get("chunk_id", p.payload.get("chunk_id"))
        by_source[source].append(p)
        by_source_type[stype] += 1
        if not cid:
            no_chunk_id += 1

    print(f"\n{'='*70}")
    print(f"  컬렉션: {COLLECTION}  |  총 {len(points)}개 청크")
    print(f"{'='*70}")

    print(f"\n  [ source_type 분포 ]")
    for stype, cnt in sorted(by_source_type.items(), key=lambda x: -x[1]):
        bar = "█" * min(cnt, 40)
        print(f"  {stype:<20} {cnt:>4}개  {bar}")

    print(f"\n  [ 소스별 청크 수 (상위 20개) ]")
    sorted_sources = sorted(by_source.items(), key=lambda x: -len(x[1]))
    for source, pts in sorted_sources[:20]:
        short = source[-60:] if len(source) > 60 else source
        print(f"  {len(pts):>4}개  {short}")

    if no_chunk_id:
        print(f"\n  ⚠ chunk_id 없는 포인트: {no_chunk_id}개")
    else:
        print(f"\n  ✓ 모든 포인트에 chunk_id 존재")

    return by_source


def show_samples(by_source: dict[str, list], n: int = 2) -> None:
    """소스별 샘플 청크 상세 출력."""
    print(f"\n{'='*70}")
    print(f"  소스별 샘플 청크 (각 {n}개)")
    print(f"{'='*70}")

    for source, pts in sorted(by_source.items(), key=lambda x: -len(x[1])):
        print(f"\n  ── {source} ({len(pts)}개) ──")
        for p in pts[:n]:
            meta = p.payload.get("metadata", {})
            content = p.payload.get("page_content", "")
            chunk_id = meta.get("chunk_id", p.payload.get("chunk_id", "?"))
            record_type = meta.get("record_type", "?")
            section_path = meta.get("section_path", "")
            master_id = meta.get("master_id", "")

            print(f"    point_id   : {p.id}")
            print(f"    chunk_id   : {chunk_id}")
            print(f"    master_id  : {master_id}")
            print(f"    record_type: {record_type}")
            if section_path:
                print(f"    section    : {section_path}")
            print(f"    content    : {content[:200].replace(chr(10), ' ')}")
            print()


def show_chunk_id_consistency(points: list) -> None:
    """chunk_id와 point.id 일치 여부 확인."""
    print(f"\n{'='*70}")
    print(f"  chunk_id ↔ point_id 일치 확인 (앞 20개)")
    print(f"{'='*70}")
    mismatch = 0
    for p in points[:20]:
        meta = p.payload.get("metadata", {})
        chunk_id = meta.get("chunk_id", p.payload.get("chunk_id"))
        match = "✓" if str(p.id) == str(chunk_id) else "✗"
        if str(p.id) != str(chunk_id):
            mismatch += 1
        print(f"  {match} point_id={str(p.id)[:36]}  chunk_id={str(chunk_id)[:36]}")
    if mismatch == 0:
        print(f"\n  ✓ 앞 20개 모두 일치 — chunk_id = Qdrant point_id")
    else:
        print(f"\n  ⚠ {mismatch}개 불일치")


def show_query_result(query: str) -> None:
    """실제 검색 쿼리 날려서 소스 추적."""
    print(f"\n{'='*70}")
    print(f"  검색 쿼리: '{query}'")
    print(f"{'='*70}")
    from src.core.storage import load_vectorstore
    from src.core.rag import build_retriever, retrieve, rerank
    from src.schemas.shared import AgenticRAGState

    vs = load_vectorstore(collection_name=COLLECTION)
    retriever = build_retriever(vs, collection_name=COLLECTION, k=5)
    state: AgenticRAGState = {
        "question": query,
        "retrieved_docs": [],
        "judgment": None,
        "retry_count": 0,
    }
    state = retrieve(state, retriever)
    state = rerank(state)

    docs = state["retrieved_docs"]
    print(f"\n  검색 결과: {len(docs)}개\n")
    for i, doc in enumerate(docs, 1):
        meta = doc.metadata
        source = meta.get("source", "?")
        stype  = meta.get("source_type", "?")
        rtype  = meta.get("record_type", "?")
        cid    = meta.get("chunk_id", "?")
        print(f"  [{i}] source_type={stype}  record_type={rtype}")
        print(f"       source   : {source}")
        print(f"       chunk_id : {cid}")
        print(f"       content  : {doc.page_content[:150].replace(chr(10), ' ')}")
        print()


def main() -> None:
    global COLLECTION
    parser = argparse.ArgumentParser(description="Qdrant 청크 진단")
    parser.add_argument("--collection", default=COLLECTION)
    parser.add_argument("--sample", type=int, default=2, help="소스별 샘플 수")
    parser.add_argument("--query", default=None, help="실제 검색 쿼리 테스트")
    parser.add_argument("--no-sample", action="store_true", help="샘플 출력 생략")
    args = parser.parse_args()

    COLLECTION = args.collection

    client = QdrantClient(url=QDRANT_URL)
    print(f"  Qdrant: {QDRANT_URL}  →  컬렉션: {COLLECTION}")

    points = _scroll_all(client)
    by_source = show_distribution(points)
    show_chunk_id_consistency(points)

    if not args.no_sample:
        show_samples(by_source, n=args.sample)

    if args.query:
        show_query_result(args.query)


if __name__ == "__main__":
    main()
