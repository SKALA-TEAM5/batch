# Batch

법령/RAG 데이터를 PostgreSQL과 Qdrant에 적재하거나 갱신하는 배치 프로젝트입니다.

## 역할

- `ingest`: MinIO PDF, 법제처 Open API, 산안비 사용기준을 Qdrant/RDB에 초기 적재
- `refresh`: 변경분을 감지해 Qdrant/RDB를 갱신
- `safety-doc-reference`: MinIO의 safety-doc-agent 마크다운을 `safety-guide` Qdrant collection으로 적재

## Kubernetes 연결

배치 Pod는 같은 namespace 안의 내부 Service로 접속합니다.

```env
QDRANT_URL=http://team5-qdrant:6333
POSTGRES_HOST=team5-postgres
POSTGRES_PORT=5432
POSTGRES_DB=safety
APP_MINIO_ENDPOINT=http://team5-minio:9000
APP_MINIO_BUCKET=safety-files
```

`DATABASE_URL`은 Kubernetes Job 시작 시 `team5-postgres-secret`의 `LAW_APP_USER`와 `LAW_APP_PASSWORD`로 조립합니다.

## 주요 명령

초기 적재:

```bash
python -m src.ingestion_service --collection legal_documents --force
```

증분 갱신:

```bash
python -m src.refresh_service --collection legal_documents
```

Safety Doc Agent 참고자료 적재:

```bash
python -m src.safety_doc_reference_ingest \
  --collection safety-guide \
  --prefix safety-doc-agent/ \
  --force
```

## 로컬 확인

Kubernetes의 공유 리소스를 port-forward로 연결합니다.

```bash
kubectl port-forward svc/team5-postgres 5433:5432 -n skala3-finalproj-class2-team5
kubectl port-forward svc/team5-qdrant 6333:6333 -n skala3-finalproj-class2-team5
kubectl port-forward svc/team5-minio 9000:9000 -n skala3-finalproj-class2-team5
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

GitHub Actions에서 이미지를 빌드한 뒤, 선택한 Kubernetes Job을 생성합니다.

- `ingest`: 전체 초기 적재
- `refresh`: 변경분 갱신
- `safety-doc-reference`: MinIO `safety-files/safety-doc-agent/` 마크다운을 `safety-guide` collection으로 적재

Kubernetes Job manifest는 이 레포가 아니라 `SKALA-TEAM5/deploy` 레포의 `k8s/batch`에서 관리합니다.
batch workflow는 deploy 레포를 checkout한 뒤 해당 Job manifest를 적용합니다.

```bash
kubectl get jobs,pods -n skala3-finalproj-class2-team5 -l app=team5-batch
kubectl logs -f job/team5-qdrant-ingest -n skala3-finalproj-class2-team5
kubectl logs -f job/team5-qdrant-refresh -n skala3-finalproj-class2-team5
kubectl logs -f job/team5-safety-doc-reference-ingest -n skala3-finalproj-class2-team5
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
