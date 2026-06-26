# SLA Test Runner Operations Guide

이 문서는 배포된 SLA Test Runner를 운영할 때 필요한 설정, 릴리즈 확인, 백업, 복구 절차를 정리합니다.

## 운영 환경 변수

`.env.example`을 복사해서 배포 환경에 맞게 수정합니다.

```bash
cp .env.example .env
```

필수 축:

| Variable | Purpose |
| --- | --- |
| `SLA_ENV` | `production`, `staging`, `local` 같은 실행 환경 이름 |
| `SLA_APP_HOME` | `suites/`, `artifacts/`가 들어갈 데이터 루트 |
| `SLA_DB_PATH` | SQLite 파일 경로 |
| `SLA_BUILD_SHA` | 배포한 git commit 또는 이미지 digest |
| `SLA_PROXY_HEADERS` | trusted proxy의 `X-Forwarded-*` 헤더를 반영할지 여부 |
| `SLA_FORWARDED_ALLOW_IPS` | forwarded header를 신뢰할 프록시 IP, CIDR, 또는 쉼표 목록 |
| `SLA_ROOT_PATH` | 리버스 프록시가 서브패스에 붙일 때의 ASGI root path |
| `SLA_GRACEFUL_SHUTDOWN_TIMEOUT` | 종료 시 실행 중 요청을 기다릴 최대 초 |
| `SLA_CONTAINER_STOP_GRACE_PERIOD` | Compose가 SIGTERM 이후 강제 종료 전 기다릴 시간, 기본 `45s` |
| `SLA_LOG_LEVEL` | 컨테이너 stdout/stderr에 남기는 Uvicorn 및 앱 로그 레벨 |
| `SLA_MIN_FREE_DISK_MB` | `/readyz`에서 요구할 데이터/DB 볼륨 최소 여유 공간(MB), `0`이면 비활성 |
| `SLA_READY_CHECK_APPIUM` | `true`면 `/readyz`에서 `APPIUM_URL/status` 연결까지 확인 |
| `SLA_BASIC_AUTH_USER` / `SLA_BASIC_AUTH_PASSWORD` | 공유 환경 접근 보호 |
| `SLA_CSRF_SECRET` | POST 폼 CSRF 토큰 서명 secret |
| `SLA_TRUSTED_ORIGINS` | 리버스 프록시/도메인 뒤에서 허용할 브라우저 origin 목록 |
| `SLA_ALLOWED_HOSTS` | 허용할 HTTP Host 헤더 목록 |
| `SLA_RUN_WORKERS` | 동시에 실행할 백그라운드 SLA 작업자 수 |
| `SLA_RUN_QUEUE_LIMIT` | 실행 중/대기 중 작업 최대 개수 |
| `SLA_RECOVER_INCOMPLETE_RUNS` | 서버 시작 시 남은 `QUEUED`/`RUNNING` 실행을 `ERROR`로 회수할지 여부 |
| `SLA_MCP_TRANSPORT` | MCP 서버 transport, 기본 `stdio` |
| `SLA_MCP_LOG_LEVEL` | MCP SDK 로그 레벨, 기본 `WARNING` |
| `SLA_MCP_ALLOW_WRITES` | MCP의 suite YAML 저장 도구 허용 여부 |
| `SLA_MCP_ALLOW_RUNS` | MCP의 Appium 실행/화면 요소 스캔 도구 허용 여부 |
| `APPIUM_URL` | Appium 서버 URL |

`/healthz`와 `/readyz`는 인증 없이 열려 있습니다. 실제 UI와 운영 API는 `SLA_BASIC_AUTH_USER`, `SLA_BASIC_AUTH_PASSWORD`를 둘 다 설정하면 Basic Auth로 보호됩니다.

Docker 이미지와 Compose healthcheck는 모두 `/readyz`를 기준으로 상태를 판단합니다. production readiness가 실패하면 컨테이너는 살아 있어도 트래픽에 붙일 준비가 안 된 상태로 보이므로, healthcheck 실패 원인은 `/readyz` 응답의 `checks` 항목에서 먼저 확인합니다.

Compose 서비스는 `init: true`, `restart: unless-stopped`, `stop_grace_period`를 사용합니다. `SLA_CONTAINER_STOP_GRACE_PERIOD`는 앱의 `SLA_GRACEFUL_SHUTDOWN_TIMEOUT`보다 길게 둬야 Uvicorn의 정상 종료와 큐 정리 로그가 Docker 강제 종료 전에 끝날 수 있습니다. 컨테이너는 non-root 사용자로 실행하고, root filesystem은 읽기 전용이며, 쓰기 경로는 `/data` 볼륨과 `/tmp` tmpfs로 제한합니다. Linux capabilities는 모두 제거하고 `no-new-privileges`를 켭니다.

POST 폼은 CSRF 토큰과 Origin 검사를 함께 사용합니다. `SLA_BASIC_AUTH_PASSWORD`는 16자 이상, `SLA_CSRF_SECRET`은 32자 이상으로 설정하고 `change-me`, `secret`, `long-random-secret` 같은 placeholder를 쓰지 마세요. 여러 인스턴스를 동시에 운영하면 모든 인스턴스에 같은 `SLA_CSRF_SECRET`을 설정하세요. HTTPS 리버스 프록시 뒤에서 외부 주소가 `https://sla.example.com`이면 아래처럼 허용 origin을 지정합니다.

```bash
SLA_ENV=production
SLA_BUILD_SHA=$(git rev-parse --short HEAD)
SLA_BASIC_AUTH_USER=operator
SLA_BASIC_AUTH_PASSWORD=$(openssl rand -base64 32)
SLA_CSRF_SECRET=$(openssl rand -base64 32)
SLA_TRUSTED_ORIGINS=https://sla.example.com
SLA_ALLOWED_HOSTS=sla.example.com,127.0.0.1,localhost
SLA_PROXY_HEADERS=true
SLA_FORWARDED_ALLOW_IPS=127.0.0.1
```

실행 요청은 백그라운드 큐에 등록되고 즉시 Run Detail로 이동합니다. 기본 `SLA_RUN_WORKERS=1`, `SLA_RUN_QUEUE_LIMIT=10`은 하나의 Android Emulator/Appium 세션을 안정적으로 공유하기 위한 값입니다. 여러 독립 디바이스/서버를 붙이는 구조가 아니라면 워커 수를 무리하게 늘리지 마세요. 큐가 가득 차면 새 실행 요청은 `429`로 거절됩니다.

정상 shutdown에서는 아직 시작하지 못한 `QUEUED` 실행을 즉시 `ERROR`로 닫습니다. 기본 `SLA_RECOVER_INCOMPLETE_RUNS=true`에서는 서버 시작 시 이전 프로세스가 남긴 `QUEUED`/`RUNNING` 실행도 `ERROR`로 회수합니다. 인메모리 실행 큐는 프로세스 재시작 후 이어서 처리할 수 없기 때문에, Run Detail에 중단 사실을 남기는 쪽이 운영자가 판단하기 쉽습니다. 여러 웹 프로세스나 복수 인스턴스가 같은 DB를 공유하는 구성은 아직 지원 대상이 아닙니다.

`SLA_ENV=production`에서는 `/readyz`가 `deployment_config` 체크를 추가로 수행합니다. Basic Auth, `SLA_CSRF_SECRET`, `SLA_ALLOWED_HOSTS`, `SLA_TRUSTED_ORIGINS`, 실제 `SLA_BUILD_SHA`가 빠져 있거나 secret 값이 너무 짧거나 placeholder이면 readiness가 `503`을 반환하므로 트래픽에 붙이기 전에 설정을 보완하세요. HTTPS 종료 프록시 뒤에서는 `SLA_FORWARDED_ALLOW_IPS`를 프록시 IP나 내부 CIDR로 좁혀서 `X-Forwarded-Proto`를 신뢰하게 해야 POST Origin 검사가 외부 `https://...` origin과 일치합니다. 외부 클라이언트가 직접 붙을 수 있는 경로에서는 wildcard `*`를 쓰지 마세요.

기본 `SLA_LOG_LEVEL=INFO`에서는 요청 완료 로그가 `request_id`, method, path, status, duration과 함께 출력됩니다. 평상시 로그량을 줄이려면 `WARNING`, 문제 재현 중에는 `DEBUG`로 조정하세요.
`SLA_MIN_FREE_DISK_MB`를 0보다 크게 설정하면 `/readyz`가 데이터 루트, suite/artifact 경로, DB 경로의 여유 공간을 검사합니다. 임계값보다 낮으면 `disk_free` check가 실패하고 readiness가 `503`을 반환합니다.
`SLA_READY_CHECK_APPIUM=true`를 설정하면 `/readyz`가 `appium_server` check를 추가합니다. Appium 서버를 별도 호스트에서 먼저 띄운 뒤 웹 컨테이너를 트래픽에 붙이는 운영에서는 켜고, 로컬처럼 실행 시점에 Appium을 자동 시작하거나 늦게 연결하는 운영에서는 기본값 `false`를 유지하세요.

## MCP 운영

LLM 클라이언트에 SLA Runner를 붙일 때는 웹 서버와 별도로 MCP 서버를 실행합니다.

```bash
python3 -m sla_app.mcp
```

기본 MCP 모드는 읽기 전용입니다. LLM이 suite YAML을 저장하거나 Appium 실행을 시작해야 하는 환경에서만 아래 권한을 켭니다.

```bash
SLA_MCP_ALLOW_WRITES=true
SLA_MCP_ALLOW_RUNS=true
```

`SLA_MCP_ALLOW_RUNS=true`는 Android Emulator/Appium 세션과 APK 설치, artifact 생성을 유발할 수 있습니다. 공유 디바이스나 원격 MCP transport를 사용할 때는 접근 제어를 별도로 두고, 가능하면 `stdio` 기반 로컬 연결을 우선 사용하세요. 상세 클라이언트 설정은 [MCP Guide](mcp.md)를 참고하세요.

## 릴리즈 확인

로컬 릴리즈 검증:

```bash
make release-check
```

CI와 같은 검증 범위:

- Python 문법 컴파일
- 전체 테스트
- Docker 이미지 빌드
- 컨테이너 `healthz`/`readyz`/`version`/`metrics` 스모크
- production 컨테이너 readiness/Auth/metrics 스모크
- Compose 설정 검증

실행 중인 서버 버전 확인:

```bash
curl -u "$SLA_BASIC_AUTH_USER:$SLA_BASIC_AUTH_PASSWORD" http://127.0.0.1:8010/version
```

`/version`의 `runtime.run_queue`에는 `queue_limit`, `reserved`, `running`, `queued`, `available` 값이 포함됩니다. 장애 대응 중에는 이 JSON으로 즉시 큐 포화 여부를 보고, 장기 모니터링은 `/metrics`의 `sla_run_queue_*` 지표를 사용하세요.

Prometheus 텍스트 형식의 운영 지표 확인:

```bash
curl -u "$SLA_BASIC_AUTH_USER:$SLA_BASIC_AUTH_PASSWORD" http://127.0.0.1:8010/metrics
```

주요 HTTP 지표는 `sla_http_requests_total`과 `sla_http_request_duration_seconds`입니다. label은 method, route path, status로 제한해서 4xx/5xx 증가와 느린 endpoint를 모니터링할 수 있게 했습니다.

모든 HTTP 응답은 `X-Request-ID`를 포함합니다. 프록시가 안전한 `X-Request-ID`를 전달하면 같은 값을 응답에 돌려주고, 없거나 허용되지 않는 값이면 앱이 새 ID를 생성합니다. 로드밸런서, 프록시, 애플리케이션 로그에서 이 값을 같은 추적 키로 사용하세요.

## 백업

Settings 화면의 `운영 데이터`에서 `백업 ZIP 다운로드`를 누릅니다.

CLI로 받을 때:

```bash
curl -u "$SLA_BASIC_AUTH_USER:$SLA_BASIC_AUTH_PASSWORD" \
  -o "sla-backup-$(date -u +%Y%m%dT%H%M%SZ).zip" \
  http://127.0.0.1:8010/settings/backup.zip
```

ZIP에는 아래 항목이 들어 있습니다.

- `manifest.json`
- `database/sla_app.db`
- `suites/`
- `artifacts/`

백업은 `suites/`, `artifacts/` 아래의 일반 파일만 포함합니다. symlink나 데이터 루트 밖으로 해석되는 파일은 ZIP에 넣지 않고 `manifest.json`의 `skipped_unsafe_files`에 개수를 남깁니다.

## 복구

기본 복구는 대상 데이터 디렉터리가 비어 있어야 합니다.

```bash
sla-restore-backup sla-backup.zip \
  --base-dir /data \
  --db-path /data/db/sla_app.db
```

기존 데이터를 교체해야 할 때만 `--force`를 사용합니다.

```bash
sla-restore-backup sla-backup.zip \
  --base-dir /data \
  --db-path /data/db/sla_app.db \
  --force
```

복구 후 확인:

```bash
curl http://127.0.0.1:8010/readyz
curl -u "$SLA_BASIC_AUTH_USER:$SLA_BASIC_AUTH_PASSWORD" http://127.0.0.1:8010/suites
```

`/readyz`의 `database` check는 SQLite schema version, WAL journal mode, `quick_check` 결과를 함께 보여줍니다. `disk_free` check는 설정한 최소 여유 공간을 만족하는지 확인합니다. `deployment_config` check는 production 보안/릴리즈 식별 설정을 확인합니다. `appium_server` check는 opt-in일 때 `APPIUM_URL` 연결 상태를 확인합니다. `status`가 `fail`이면 배포를 트래픽에 붙이기 전에 DB 경로 권한, 파일 손상, schema version 불일치, 디스크 용량 부족, production 설정 누락, Appium 서버 연결을 먼저 확인합니다. 현재 앱보다 높은 SQLite `user_version`을 가진 DB는 시작 단계에서 거부하며 다운그레이드하지 않습니다. 새 버전에서 만든 백업을 이전 이미지로 복구해야 하면 먼저 이미지 버전을 맞추세요. `/version`과 `/metrics`는 HTTP 오류 증가, 실행 실패 증가, 큐 포화, DB 이상 여부를 외부 모니터링에 연결할 때 사용합니다.

## 이력 정리

Settings 화면의 `운영 데이터`에서 최근 실행 보존 수와 일수 기준을 입력하고 `오래된 실행 정리`를 누릅니다.

기본 표시값은 아래 환경 변수로 조정합니다.

```bash
SLA_RETENTION_KEEP_LAST=100
SLA_RETENTION_DAYS=30
```

정리 작업은 자동으로 실행되지 않습니다. 운영자가 화면에서 명시적으로 실행할 때만 삭제됩니다.
