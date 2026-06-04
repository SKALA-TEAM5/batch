from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import uuid
from pathlib import Path
from urllib.parse import urlparse

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from minio import Minio

from src.core.storage import reset_collection, upsert_with_ids


DEFAULT_COLLECTION = "safety-guide"
DEFAULT_PREFIX = "safety-doc-agent/"
DEFAULT_DATA_DIR = "data/safety-doc-agent"
_POINT_NAMESPACE = uuid.UUID("4a8be956-3238-4e02-b05a-5d384135270d")


def run_ingest(
    *,
    collection: str = DEFAULT_COLLECTION,
    prefix: str = DEFAULT_PREFIX,
    data_dir: str = DEFAULT_DATA_DIR,
    force: bool = False,
) -> dict[str, int | str]:
    """MinIO의 safety-doc-agent 마크다운 자료를 Qdrant collection으로 적재한다."""

    local_files = sync_markdown_files_from_minio(prefix=prefix, data_dir=data_dir)
    documents = build_documents(local_files)
    ids = [make_point_id(doc) for doc in documents]

    if force:
        reset_collection(collection)

    upsert_with_ids(collection_name=collection, documents=documents, ids=ids)
    result = {
        "collection": collection,
        "source_files": len(local_files),
        "chunks": len(documents),
        "prefix": prefix,
    }
    print(result)
    return result


def sync_markdown_files_from_minio(*, prefix: str, data_dir: str) -> list[Path]:
    client, bucket = get_minio_client()
    target_dir = Path(data_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    downloaded: list[Path] = []
    for obj in client.list_objects(bucket, prefix=prefix, recursive=True):
        object_name = obj.object_name
        if not object_name.lower().endswith((".md", ".markdown")):
            continue

        target_path = safe_download_path(target_dir, object_name)
        response = client.get_object(bucket, object_name)
        try:
            with target_path.open("wb") as file:
                shutil.copyfileobj(response, file)
        finally:
            response.close()
            response.release_conn()

        print(f"[MinIO -> safety-doc-agent] {object_name} -> {target_path}")
        downloaded.append(target_path)

    if not downloaded:
        raise RuntimeError(f"No markdown files found in bucket={bucket}, prefix={prefix}")

    return downloaded


def build_documents(paths: list[Path]) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=900,
        chunk_overlap=120,
        separators=["\n## ", "\n### ", "\n#### ", "\n\n", "\n", " ", ""],
    )

    documents: list[Document] = []
    for path in sorted(paths):
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            continue

        sections = split_markdown_sections(text)
        for section_index, section in enumerate(sections, start=1):
            section_title = section["title"]
            chunks = splitter.split_text(section["body"])
            for chunk_index, chunk in enumerate(chunks, start=1):
                page_content = chunk.strip()
                if not page_content:
                    continue
                documents.append(
                    Document(
                        page_content=page_content,
                        metadata={
                            "source": path.name,
                            "source_path": str(path),
                            "source_type": "safety_doc_agent_reference",
                            "collection_role": "safety_doc_agent",
                            "section_title": section_title,
                            "section_index": section_index,
                            "chunk_index": chunk_index,
                        },
                    )
                )

    if not documents:
        raise RuntimeError("No chunks generated from markdown files.")
    return documents


def split_markdown_sections(markdown: str) -> list[dict[str, str]]:
    sections: list[dict[str, str]] = []
    current_title = "document"
    current_lines: list[str] = []

    for line in markdown.splitlines():
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading and current_lines:
            sections.append({"title": current_title, "body": "\n".join(current_lines).strip()})
            current_lines = []
        if heading:
            current_title = heading.group(2).strip()
        current_lines.append(line)

    if current_lines:
        sections.append({"title": current_title, "body": "\n".join(current_lines).strip()})

    return [section for section in sections if section["body"]]


def make_point_id(document: Document) -> str:
    source = document.metadata.get("source", "")
    section = document.metadata.get("section_index", "")
    chunk = document.metadata.get("chunk_index", "")
    raw = f"safety-guide:{source}:{section}:{chunk}:{document.page_content}"
    return str(uuid.uuid5(_POINT_NAMESPACE, raw))


def get_minio_client() -> tuple[Minio, str]:
    endpoint = os.getenv("BATCH_MINIO_ENDPOINT") or os.getenv("APP_MINIO_ENDPOINT")
    bucket = os.getenv("BATCH_MINIO_BUCKET") or os.getenv("APP_MINIO_BUCKET")
    access_key = os.getenv("BATCH_MINIO_ACCESS_KEY") or os.getenv("APP_MINIO_ACCESS_KEY")
    secret_key = os.getenv("BATCH_MINIO_SECRET_KEY") or os.getenv("APP_MINIO_SECRET_KEY")

    missing = [
        name
        for name, value in {
            "APP_MINIO_ENDPOINT": endpoint,
            "APP_MINIO_BUCKET": bucket,
            "APP_MINIO_ACCESS_KEY": access_key,
            "APP_MINIO_SECRET_KEY": secret_key,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError(f"Missing MinIO settings: {', '.join(missing)}")

    parsed = urlparse(endpoint)
    secure = parsed.scheme == "https"
    host = parsed.netloc if parsed.netloc else parsed.path
    return Minio(host, access_key=access_key, secret_key=secret_key, secure=secure), bucket


def safe_download_path(target_dir: Path, object_name: str) -> Path:
    original_name = Path(object_name).name
    stem = re.sub(r"[^0-9A-Za-z가-힣._-]+", "-", Path(original_name).stem).strip("-")
    suffix = Path(original_name).suffix or ".md"
    digest = hashlib.sha1(object_name.encode("utf-8")).hexdigest()[:10]
    return target_dir / f"{stem[:80]}-{digest}{suffix}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="safety-doc-agent 참고 마크다운을 Qdrant에 적재합니다.")
    parser.add_argument("--collection", default=os.getenv("SAFETY_DOC_COLLECTION", DEFAULT_COLLECTION))
    parser.add_argument("--prefix", default=os.getenv("BATCH_SAFETY_DOC_PREFIX", DEFAULT_PREFIX))
    parser.add_argument("--data-dir", default=os.getenv("BATCH_SAFETY_DOC_DATA_DIR", DEFAULT_DATA_DIR))
    parser.add_argument("--force", action="store_true")
    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    run_ingest(
        collection=args.collection,
        prefix=args.prefix,
        data_dir=args.data_dir,
        force=args.force,
    )
