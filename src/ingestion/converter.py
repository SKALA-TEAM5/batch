# --------------------------------------------------------------------------
# 작성자   : 송상민(ss19801)
# 작성일   : 2026-05-04
#
# [ 주요 함수 정의 ]
#
# 1. convert_pdf_to_markdown() : Docling을 이용한 PDF → 마크다운 변환
# --------------------------------------------------------------------------
from docling.datamodel.pipeline_options import PdfPipelineOptions, AcceleratorOptions, AcceleratorDevice
from docling.document_converter import DocumentConverter, PdfFormatOption


def convert_pdf_to_markdown(pdf_path: str) -> str:
    print(f"[{pdf_path}] PDF 변환 시작 (Docling)...")
    pipeline_options = PdfPipelineOptions(
        accelerator_options=AcceleratorOptions(device=AcceleratorDevice.CPU)
    )
    converter = DocumentConverter(
        format_options={
            "pdf": PdfFormatOption(pipeline_options=pipeline_options),
        }
    )
    result = converter.convert(pdf_path)
    return result.document.export_to_markdown()
