# Batch

법령/RAG 데이터를 PostgreSQL과 Qdrant에 적재하거나 갱신하는 배치 프로젝트입니다.

## Kubernetes 연결

배치 Pod는 같은 namespace 안의 내부 Service로 접속합니다.

```env
QDRANT_URL=http://team5-qdrant:6333
POSTGRES_HOST=team5-postgres
POSTGRES_PORT=5432
POSTGRES_DB=safety
```

`DATABASE_URL`은 Kubernetes Job 시작 시 `team5-postgres-secret`의 `LAW_APP_USER`와 `LAW_APP_PASSWORD`로 조립합니다.

초기 적재(`ingest`)는 MinIO의 `safety-files/data/` prefix에서 PDF 파일을 내려받아 `data/` 디렉토리에 동기화한 뒤 처리합니다.

```env
APP_MINIO_ENDPOINT=http://team5-minio:9000
APP_MINIO_BUCKET=safety-files
BATCH_MINIO_DATA_PREFIX=data/
```

## 주요 명령

초기 적재:

```bash
python -m src.ingestion_service --collection legal_documents --force
```

증분 갱신:

```bash
python -m src.refresh_service --collection legal_documents
```

## 로컬 확인

```bash
kubectl port-forward svc/team5-postgres 5433:5432 -n skala3-finalproj-class2-team5
kubectl port-forward svc/team5-qdrant 6333:6333 -n skala3-finalproj-class2-team5
```

`.env` 예시:

```env
QDRANT_URL=http://localhost:6333
DATABASE_URL=postgresql://safety_law_app:<password>@localhost:5433/safety
APP_MINIO_ENDPOINT=http://localhost:9000
APP_MINIO_BUCKET=safety-files
APP_MINIO_ACCESS_KEY=minioadmin
APP_MINIO_SECRET_KEY=minioadmin
BATCH_MINIO_DATA_PREFIX=data/
```

## 배포/실행

GitHub Actions에서 이미지를 빌드한 뒤, 수동 실행으로 Kubernetes Job을 생성합니다.

- `ingest`: 전체 초기 적재
- `ingest-pdfs`: MinIO PDF를 파일별 Kubernetes Job으로 분리 실행
- `refresh`: 변경분 갱신

Actions는 Job을 생성한 뒤 종료합니다. PDF 변환은 Kubernetes에서 계속 실행되므로 로컬에서 로그를 확인합니다.

```bash
kubectl get jobs,pods -n skala3-finalproj-class2-team5 -l app=team5-batch
kubectl logs -f job/team5-qdrant-ingest-pdf-1 -n skala3-finalproj-class2-team5
```

`ingest-pdfs`를 선택할 때는 `pdf_objects`에 MinIO object name을 쉼표로 구분해 입력합니다.

```text
data/example-a.pdf,data/example-b.pdf,data/example-c.pdf
```

각 PDF는 아래처럼 별도 Job으로 실행됩니다.

```text
team5-qdrant-ingest-pdf-1
team5-qdrant-ingest-pdf-2
team5-qdrant-ingest-pdf-3
```

Actions Secret에 아래 값을 등록해야 합니다.

```text
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
HARBOR_REGISTRY
HARBOR_PROJECT
HARBOR_USERNAME
HARBOR_PASSWORD
LAW_API_KEY
```

`LAW_API_KEY`는 workflow 실행 시 `team5-batch-secret` Kubernetes Secret으로 반영되고,
배치 Job은 이 Secret을 환경변수로 읽습니다.
