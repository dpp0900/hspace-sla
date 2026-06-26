# HSPACE SLA Runner MCP Guide

이 문서는 SLA Test Runner를 MCP(Model Context Protocol) 서버로 실행해서 Claude Desktop, Claude Code, Cursor, Continue 같은 MCP 호환 LLM 클라이언트에 연결하는 방법을 정리합니다.

## 목적

MCP 서버를 붙이면 LLM이 웹 UI를 직접 열지 않아도 아래 작업을 도구로 수행할 수 있습니다.

- 등록된 SLA suite 목록 조회
- suite YAML 읽기, 검증, 저장
- 최근 실행 이력과 run report 분석
- SQLite 상태 확인
- 권한을 켠 경우 Appium suite 실행과 화면 요소 스캔

MCP는 LLM용 표준 도구 인터페이스입니다. 이 프로젝트는 공식 Python SDK의 `FastMCP` 기반 서버를 제공하며, 기본 transport는 로컬 LLM 클라이언트가 가장 쉽게 붙일 수 있는 `stdio`입니다.

## 실행 명령

개발 체크아웃에서 바로 실행:

```bash
cd /Users/dpp/Desktop/HSPACE/SLA
python3 -m sla_app.mcp
```

패키지 설치 후 실행:

```bash
sla-mcp
```

기본값:

- transport: `stdio`
- data root: `SLA_APP_HOME` 또는 현재 작업 디렉터리
- DB: `SLA_DB_PATH` 또는 `<data root>/sla_app.db`
- write tools: 비활성
- run/device tools: 비활성

쓰기와 실제 Appium 실행까지 허용:

```bash
SLA_MCP_ALLOW_WRITES=true \
SLA_MCP_ALLOW_RUNS=true \
python3 -m sla_app.mcp
```

HTTP 기반 transport로 실행:

```bash
python3 -m sla_app.mcp \
  --transport streamable-http \
  --host 127.0.0.1 \
  --port 8001
```

접속 URL은 기본 `http://127.0.0.1:8001/mcp`입니다.

## 환경 변수

| Variable | Default | Description |
| --- | --- | --- |
| `SLA_APP_HOME` | `.` | `suites/`, `artifacts/`, 기본 DB가 들어 있는 데이터 루트 |
| `SLA_DB_PATH` | `<SLA_APP_HOME>/sla_app.db` | SQLite DB 경로 |
| `SLA_MCP_TRANSPORT` | `stdio` | `stdio`, `sse`, `streamable-http` |
| `SLA_MCP_HOST` | `127.0.0.1` | HTTP transport host |
| `SLA_MCP_PORT` | `8001` | HTTP transport port |
| `SLA_MCP_LOG_LEVEL` | `WARNING` | MCP SDK 로그 레벨 |
| `SLA_MCP_ALLOW_WRITES` | `false` | `save_suite_yaml` 허용 |
| `SLA_MCP_ALLOW_RUNS` | `false` | `run_suite`, `inspect_suite_elements` 허용 |

`run_suite`와 `inspect_suite_elements`는 Android Emulator, Appium, APK 설치/실행에 영향을 줄 수 있습니다. 개인 로컬 환경에서는 켜도 되지만, 공유 MCP 서버나 원격 노출 환경에서는 기본값인 `false`를 유지하세요.

## 제공 Tools

| Tool | Side effect | Description |
| --- | --- | --- |
| `sync_suite_files` | DB index update | `suites/*.yaml`을 SQLite suite index에 등록 |
| `list_suites` | No | suite id, 이름, app target, threshold, scenario/step 수 조회 |
| `get_suite` | No | suite 상세와 YAML 조회 |
| `validate_suite_yaml` | No | YAML 문법과 SLA schema 검증 |
| `save_suite_yaml` | File write | suite YAML 저장, `SLA_MCP_ALLOW_WRITES=true` 필요 |
| `list_runs` | No | 최근 실행 목록 조회 |
| `get_run_report` | No | run 상세 JSON 조회 |
| `database_status` | No | SQLite schema/WAL/quick_check/count 상태 조회 |
| `run_suite` | Device/run | Appium으로 suite 실행, `SLA_MCP_ALLOW_RUNS=true` 필요 |
| `inspect_suite_elements` | Device/run | suite 대상 앱 화면 요소 스캔, `SLA_MCP_ALLOW_RUNS=true` 필요 |

## 제공 Resources

| Resource URI | Description |
| --- | --- |
| `sla://suites` | suite 목록 JSON |
| `sla://suites/{suite_id}` | suite 상세 JSON과 YAML |
| `sla://runs/recent` | 최근 실행 목록 JSON |
| `sla://runs/{run_id}` | run report JSON |
| `sla://docs/yaml-guide` | YAML 작성 가이드 |
| `sla://docs/mcp` | 이 문서 |

## 제공 Prompts

| Prompt | Description |
| --- | --- |
| `draft_android_sla_suite` | 앱 목표와 APK/package 힌트를 받아 SLA YAML 초안 작성 |
| `analyze_failed_run` | 특정 run id의 실패 원인 분석 지시문 생성 |

## Claude Desktop 연결 예시

Claude Desktop 설정 파일의 `mcpServers`에 아래 항목을 추가합니다. macOS 기준 설정 파일은 보통 `~/Library/Application Support/Claude/claude_desktop_config.json`입니다.

읽기 전용:

```json
{
  "mcpServers": {
    "hspace-sla": {
      "type": "stdio",
      "command": "python3",
      "args": ["-m", "sla_app.mcp"],
      "env": {
        "SLA_APP_HOME": "/Users/dpp/Desktop/HSPACE/SLA"
      }
    }
  }
}
```

suite 저장과 실제 실행까지 허용:

```json
{
  "mcpServers": {
    "hspace-sla": {
      "type": "stdio",
      "command": "python3",
      "args": ["-m", "sla_app.mcp"],
      "env": {
        "SLA_APP_HOME": "/Users/dpp/Desktop/HSPACE/SLA",
        "SLA_MCP_ALLOW_WRITES": "true",
        "SLA_MCP_ALLOW_RUNS": "true",
        "SLA_START_APPIUM": "true",
        "APPIUM_URL": "http://127.0.0.1:4723"
      }
    }
  }
}
```

설정 변경 후 Claude Desktop을 재시작합니다.

## Claude Code 연결 예시

이 저장소에는 읽기 전용 기본값의 프로젝트 MCP 설정인 `.mcp.json`이 포함되어 있습니다. Claude Code가 프로젝트 MCP 설정 사용 여부를 물으면 승인해서 바로 사용할 수 있습니다.

CLI로 직접 추가하려면 프로젝트 루트에서 stdio 서버를 추가합니다.

```bash
claude mcp add hspace-sla \
  --scope project \
  -- python3 -m sla_app.mcp
```

공유 가능한 `.mcp.json` 형태로 관리한다면 아래와 같은 구조를 사용합니다.

```json
{
  "mcpServers": {
    "hspace-sla": {
      "type": "stdio",
      "command": "python3",
      "args": ["-m", "sla_app.mcp"],
      "env": {
        "SLA_APP_HOME": "/Users/dpp/Desktop/HSPACE/SLA"
      }
    }
  }
}
```

HTTP transport를 쓰는 경우:

```bash
python3 -m sla_app.mcp --transport streamable-http --port 8001
claude mcp add --transport http hspace-sla http://127.0.0.1:8001/mcp
```

## 동작 확인

MCP Inspector를 사용할 수 있으면 아래처럼 확인합니다.

```bash
npx -y @modelcontextprotocol/inspector
```

stdio 서버 명령:

```bash
python3 -m sla_app.mcp
```

LLM에서 사용할 첫 요청 예시:

```text
HSPACE SLA MCP에서 list_suites를 호출해서 실행 가능한 suite를 보여줘.
Android Field Ops Advanced SLA의 YAML을 읽고 어떤 SLA 기준을 검증하는지 요약해줘.
최근 실패 run이 있으면 get_run_report로 실패 step과 원인을 한국어로 분석해줘.
```

실제 실행까지 켠 경우:

```text
Android Field Ops Advanced SLA suite를 run_suite로 실행하고,
결과가 FAIL이면 실패 step, screenshot artifact, metric violation을 기준으로 수정안을 제안해줘.
```

## 보안 메모

- `stdio`는 로컬 LLM 클라이언트가 프로세스를 직접 실행하는 방식입니다. 연결한 LLM이 사용할 수 있는 도구 권한을 신뢰할 수 있을 때만 write/run 권한을 켜세요.
- `streamable-http`나 `sse`로 띄울 때는 기본적으로 인증 계층이 없습니다. 로컬 loopback에서만 쓰거나, 별도 프록시/방화벽으로 접근을 제한하세요.
- `save_suite_yaml`은 파일을 씁니다. Git으로 추적되는 `suites/`를 공유 저장소에서 다룰 때는 LLM이 만든 변경을 리뷰하세요.
- `run_suite`는 에뮬레이터/Appium 실행, APK 설치, artifact 생성을 수행합니다. 공유 장비에서는 실행 큐와 디바이스 점유를 고려하세요.
