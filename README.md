# batch

법령 데이터 초기 적재 및 주기 갱신 파이프라인

## 개요

SKALA 프로젝트의 법령 데이터를 Qdrant(벡터 DB)와 PostgreSQL(RDB)에 적재하고 최신 상태로 유지합니다.

- **ingestion** : 최초 1회 실행. PDF 변환 + 법제처 API 수집 + 산안비 고시 파싱 후 전체 적재
- **refresh** : 주기적으로 실행(cronjob 등). 변경분만 감지하여 Qdrant + RDB 갱신

## 요구사항

- Python 3.11.9
- [uv](https://github.com/astral-sh/uv)
- Qdrant 서버 (`http://localhost:6333`)
- PostgreSQL (`legal_rag` 스키마)

## 설치

```bash
uv sync
```

## 환경변수

프로젝트 루트(skala/)의 `.env` 파일에 아래 항목이 있어야 합니다.

```
QDRANT_URL=http://localhost:6333
DATABASE_URL=postgresql://...
LAW_API_KEY=<법제처 Open API 키>
```

## 실행

### 초기 적재 (ingestion)

```bash
# 최초 실행
uv run python src/ingestion_service.py

# 강제 재적재 (Qdrant 컬렉션 초기화 후 재실행)
uv run python src/ingestion_service.py --force

# PDF 재변환까지 포함
uv run python src/ingestion_service.py --force --reconvert
```

### 주기 갱신 (refresh)

```bash
uv run python src/refresh_service.py
```

## 디렉토리 구조

```
batch/
├── src/
│   ├── ingestion/          # PDF 변환, 법제처 API, 산안비 고시 수집
│   ├── refresh/            # 변경 감지(diff) 및 갱신
│   ├── repositories/       # RDB 적재 로직
│   ├── core/               # Qdrant 연결, 임베딩
│   ├── ingestion_service.py
│   └── refresh_service.py
├── data/                   # PDF 원본 파일
├── outputs/                # Docling 변환 결과 (마크다운)
└── artifacts/              # 파이프라인 산출물
```
