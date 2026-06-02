# --------------------------------------------------------------------------
# 작성자   : 송상민(ss19801)
# 작성일   : 2026-05-04
#
# [ 주요 함수 정의 ]
#
# 1. convert_pdf_to_markdown() : pdfplumber 기반 PDF → 최종 마크다운 변환
# --------------------------------------------------------------------------
from src.ingestion.pdfplumber_converter import convert_pdf_to_final_markdown


def convert_pdf_to_markdown(pdf_path: str) -> str:
    """PDF → final markdown 변환. restructure + breadcrumb 포함된 완성본 반환."""
    return convert_pdf_to_final_markdown(pdf_path)
