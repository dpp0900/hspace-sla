# HSPACE SLA Test Runner

이 프로젝트는 Android 앱의 SLA 테스트를 로컬에서 만들고 실행하는 Python 기반 테스트 러너입니다. 웹 UI에서 YAML 테스트 스위트를 생성/수정/실행하고, 실행 결과를 `PASS`/`FAIL`과 액션별 로그로 확인할 수 있습니다.

현재 버전은 Android Emulator + Appium 기반 SLA 실행을 지원합니다. 기존 CLI 런처도 유지되어 APK 실행 검증이나 자동화 디버깅에 그대로 사용할 수 있습니다.

지원 방식:

- FastAPI 웹앱에서 SLA 테스트 스위트 관리/실행
- Settings 화면에서 Android SDK, Appium, UiAutomator2 환경 진단
- YAML 테스트 정의를 파일로 버전관리
- APK 파일을 설치하고 실행
- 이미 설치된 앱을 `package/activity`로 실행
- MCP 서버로 LLM 클라이언트에 suite/run context와 실행 도구 제공

핵심 파일:

- `launch_android_app.py`: 에뮬레이터 부팅, Appium 서버 연결, 앱 실행
- `run_sla_web.py`: 로컬 SLA 테스트 웹앱 실행
- `sla_launcher/`: 런처 내부 구현 패키지
- `sla_app/`: 테스트 정의, 실행 엔진, 저장소, 웹 UI
- `sla_app/mcp/`: Claude Desktop/Claude Code 등 LLM 연결용 MCP 서버
- `suites/`: YAML 테스트 스위트
- `artifacts/`: 실행별 스크린샷/로그 저장 위치
- `requirements.txt`: Python 의존성
- `pyproject.toml`: 패키징 메타데이터와 `sla-web`, `sla-restore-backup`, `sla-mcp` 실행 진입점
- `.env.example`: 운영 환경 변수 예시
- `.mcp.json`: Claude Code 등 프로젝트 MCP 클라이언트용 읽기 전용 기본 설정
- `Dockerfile`, `docker-compose.yml`: 컨테이너 배포 진입점
- `Makefile`: 로컬 릴리즈 검증 명령
- `test-apk/build/hspace-test-app-debug.apk`: 바로 설치 가능한 검증용 APK
- `test-apk/build_test_apk.sh`: 검증용 APK 재빌드 스크립트
- `docs/mcp.md`: LLM 클라이언트 MCP 연결 가이드

## 빠른 시작

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
SLA_WEB_PORT=8010 ./.venv/bin/python run_sla_web.py
```

브라우저에서 `http://127.0.0.1:8010`을 엽니다.

웹앱에서 Run을 누르면 Appium 서버가 없을 때 기본적으로 자동 시작을 시도합니다. 이 자동 시작은 Appium 2와 `uiautomator2` 드라이버가 설치되어 있어야 동작합니다.

```bash
npm install -g appium
appium driver install uiautomator2
```

수동으로 켜 둔 Appium 서버만 사용하려면 웹앱을 아래처럼 실행합니다.

```bash
SLA_START_APPIUM=false SLA_WEB_PORT=8010 ./.venv/bin/python run_sla_web.py
```

## LLM/MCP 연결

LLM 클라이언트에서 suite 목록, YAML, 실행 이력, run report를 도구로 쓰려면 MCP 서버를 실행합니다.

```bash
cd /Users/dpp/Desktop/HSPACE/SLA
python3 -m sla_app.mcp
```

패키지로 설치한 뒤에는 `sla-mcp` 명령도 사용할 수 있습니다. 기본은 읽기 전용이며, suite 저장이나 실제 Appium 실행을 LLM에 맡길 때만 명시적으로 권한을 켭니다.

```bash
SLA_MCP_ALLOW_WRITES=true \
SLA_MCP_ALLOW_RUNS=true \
python3 -m sla_app.mcp
```

Claude Desktop, Claude Code, HTTP transport 설정 예시는 [MCP Guide](docs/mcp.md)를 참고하세요.

## 프로젝트 구조

- `launch_android_app.py`: 외부에서 실행하는 얇은 엔트리포인트
- `sla_launcher/config.py`: CLI 인자 파싱과 설정 객체 생성
- `sla_launcher/android.py`: AVD 탐색, 아키텍처 판별, 에뮬레이터 부팅
- `sla_launcher/appium_server.py`: Appium 서버 상태 확인과 자동 시작
- `sla_launcher/session.py`: Appium capability 구성과 드라이버 생성
- `sla_launcher/process.py`: subprocess 실행, SDK/실행 파일 해석
- `sla_launcher/paths.py`: OS별 SDK/실행 파일 경로 유틸
- `sla_launcher/console.py`: 공통 로그/오류 출력
- `sla_launcher/main.py`: 전체 실행 흐름 오케스트레이션
- `sla_app/core/`: YAML 테스트 모델, 검증, 실행 엔진, SLA 판정
- `sla_app/adapters/android_appium/`: Appium 기반 Android 액션 어댑터
- `sla_app/storage/`: SQLite 저장소와 아티팩트 경로 관리
- `sla_app/web/`: FastAPI, Jinja2, HTMX 기반 로컬 UI
- `sla_app/mcp/`: MCP tools/resources/prompts 서버

## 지원 범위

이 저장소에서 구분해야 하는 축은 두 가지입니다.

- CPU 아키텍처: `arm64/aarch64` 또는 `x86_64/amd64`
- OS: macOS, Windows, Linux

현재 상태 기준:

- 에뮬레이터 자동 선택 로직은 CPU 아키텍처 기준으로 동작합니다.
- 커밋된 테스트 APK는 네이티브 `.so`가 없는 순수 Dex APK라 CPU 아키텍처와 무관하게 설치할 수 있습니다.
- 실행 스크립트는 OS별 기본 SDK 경로를 추정하도록 구성되어 있습니다.
- Windows와 Linux도 환경 변수와 실행 경로를 맞추면 사용할 수 있습니다.
- README의 예시는 macOS와 Windows를 함께 다루지만, 테스트 APK 재빌드 스크립트는 macOS/Linux 기준입니다.
- `test-apk/build_test_apk.sh`는 bash 스크립트라 macOS/Linux에서 바로 사용 가능합니다. Windows에서는 커밋된 APK를 그대로 쓰는 편이 간단합니다.

## 아키텍처별 빠른 판단표

- Apple Silicon Mac: 호스트 아키텍처는 보통 `arm64`, 필요한 AVD ABI는 `arm64-v8a`
- Intel Mac / 일반 PC: 호스트 아키텍처는 보통 `x86_64`, 필요한 AVD ABI는 `x86_64`
- Windows on ARM: 호스트 아키텍처는 보통 `ARM64`, 필요한 AVD ABI는 `arm64-v8a`

핵심 규칙:

- 호스트 CPU 아키텍처와 에뮬레이터 system image ABI를 맞춰야 합니다.
- APK 자체는 현재 아키텍처에 묶이지 않습니다.
- 문제는 APK보다 AVD/system image 쪽에서 더 자주 발생합니다.

## 에뮬레이터 자동 선택 규칙

스크립트는 아래 순서로 디바이스를 결정합니다.

1. `--serial`을 주면 해당 에뮬레이터를 그대로 사용
2. 이미 실행 중인 Android Emulator가 있으면 첫 번째 에뮬레이터를 재사용
3. `--avd` 또는 `ANDROID_AVD`를 주면 해당 AVD를 사용
4. 아무 것도 지정하지 않으면 호스트 CPU 아키텍처에 맞는 AVD를 자동 선택

자동 선택은 `~/.android/avd` 또는 `ANDROID_AVD_HOME` 아래의 AVD 설정을 읽어서 `abi.type`, `hw.cpu.arch`, system image 경로를 기준으로 결정합니다.

- `arm64`, `aarch64` 호스트: `arm64-v8a` AVD 우선
- `x86_64`, `amd64` 호스트: `x86_64`, 그다음 `x86` AVD 우선

즉, AVD 이름을 특정 규칙으로 맞출 필요는 없습니다. 이름이 아니라 실제 AVD ABI를 보고 선택합니다.

## 환경 구성 가이드

### 호스트 아키텍처 확인

macOS / Linux:

```bash
uname -m
```

Windows PowerShell:

```powershell
$env:PROCESSOR_ARCHITECTURE
```

일반적으로:

- Apple Silicon Mac이면 `arm64`
- Intel/AMD 머신이면 `x86_64` 또는 `AMD64`
- Windows on ARM이면 `ARM64`

### Android Studio / SDK 설치

Android Studio를 설치한 뒤 SDK Manager에서 아래 구성요소를 설치합니다.

- `Android SDK Platform-Tools`
- `Android Emulator`
- `Android SDK Command-line Tools (latest)`
- `Android SDK Platform 35`
- `Android SDK Build-Tools 35.0.0`
- `Android SDK Platform 36`
- 현재 머신 아키텍처에 맞는 Android 36 system image

macOS 예시:

```bash
export ANDROID_SDK_ROOT="$HOME/Library/Android/sdk"
export PATH="$ANDROID_SDK_ROOT/platform-tools:$ANDROID_SDK_ROOT/emulator:$ANDROID_SDK_ROOT/cmdline-tools/latest/bin:$PATH"

sdkmanager --install \
  "platform-tools" \
  "emulator" \
  "cmdline-tools;latest" \
  "platforms;android-35" \
  "build-tools;35.0.0" \
  "platforms;android-36"
```

Windows PowerShell 예시:

```powershell
$env:ANDROID_SDK_ROOT="$env:LOCALAPPDATA\Android\Sdk"
$env:PATH="$env:ANDROID_SDK_ROOT\platform-tools;$env:ANDROID_SDK_ROOT\emulator;$env:ANDROID_SDK_ROOT\cmdline-tools\latest\bin;$env:PATH"
```

라이선스 동의가 필요하면 아래를 한 번 실행합니다.

```bash
sdkmanager --licenses
```

### 아키텍처에 맞는 system image 설치

`arm64` 또는 `ARM64` 호스트:

```bash
sdkmanager --install "system-images;android-36;google_apis_playstore;arm64-v8a"
```

`x86_64` 또는 `AMD64` 호스트:

```bash
sdkmanager --install "system-images;android-36;google_apis_playstore;x86_64"
```

중요:

- Apple Silicon에서는 `x86_64` system image가 정상 부팅되지 않을 수 있습니다.
- 자동 선택을 쓰려면 현재 머신 아키텍처에 맞는 AVD가 최소 1개는 있어야 합니다.

### AVD 생성

`arm64` 계열 호스트 예시:

```bash
avdmanager create avd \
  -n Medium_Phone_API_36_ARM64 \
  -k "system-images;android-36;google_apis_playstore;arm64-v8a" \
  -d medium_phone
```

`x86_64` 계열 호스트 예시:

```bash
avdmanager create avd \
  -n Medium_Phone_API_36_X86_64 \
  -k "system-images;android-36;google_apis_playstore;x86_64" \
  -d medium_phone
```

AVD 저장 경로를 기본값이 아닌 곳으로 바꿨다면 `ANDROID_AVD_HOME`도 같이 설정하세요.

### Python 가상환경 구성

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

현재 Python 의존성은 `requirements.txt`에 고정되어 있습니다. Appium 실행, FastAPI 웹 UI, YAML 파싱, 웹 smoke 테스트에 필요한 패키지를 함께 설치합니다.

### Appium 2 설치

Node.js가 설치되어 있어야 합니다.

```bash
npm install -g appium
appium driver install uiautomator2
```

확인:

```bash
appium driver list --installed
```

웹앱은 suite 실행 시 Appium 서버가 없으면 기본적으로 Python `AppiumService`로 자동 시작을 시도합니다. CLI 런처는 `--start-appium` 옵션을 줄 때만 Appium 서버를 자동 시작합니다. 두 경우 모두 Appium 2와 `uiautomator2` 드라이버가 설치되어 있어야 합니다.

전역 `appium` 명령이 `PATH`에 없어도 `~/node_modules/appium/build/lib/main.js`에 설치된 로컬 Appium은 자동 탐색합니다. 별도 위치에 설치했다면 `APPIUM_MAIN_SCRIPT=/absolute/path/to/appium/build/lib/main.js`로 지정하세요.

### 권장 환경 변수

macOS `zsh` 예시:

```bash
export ANDROID_SDK_ROOT="$HOME/Library/Android/sdk"
export ANDROID_HOME="$ANDROID_SDK_ROOT"
export PATH="$ANDROID_SDK_ROOT/platform-tools:$ANDROID_SDK_ROOT/emulator:$ANDROID_SDK_ROOT/cmdline-tools/latest/bin:$PATH"
export JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home"
```

Windows PowerShell 예시:

```powershell
$env:ANDROID_SDK_ROOT="$env:LOCALAPPDATA\Android\Sdk"
$env:ANDROID_HOME=$env:ANDROID_SDK_ROOT
$env:PATH="$env:ANDROID_SDK_ROOT\platform-tools;$env:ANDROID_SDK_ROOT\emulator;$env:ANDROID_SDK_ROOT\cmdline-tools\latest\bin;$env:PATH"
```

주의:

- `launch_android_app.py`는 OS별 기본 SDK 경로를 추정하지만, 팀 환경이 다르면 `ANDROID_SDK_ROOT`, `ANDROID_HOME`, `ANDROID_ADB_PATH`, `ANDROID_EMULATOR_PATH`를 명시하는 편이 안전합니다.

## 테스트 APK

이 저장소에는 Appium 연결과 SLA 액션 검증용 Android 앱이 포함되어 있습니다.

바로 사용 가능한 APK:

- `test-apk/build/hspace-test-app-debug.apk`

기본 package/activity:

- Package: `com.hspace.testapp`
- Activity: `com.hspace.testapp.MainActivity`

이 APK는 현재 네이티브 라이브러리를 포함하지 않으므로 CPU 아키텍처와 무관하게 설치 가능합니다. 실질적인 제약은 Android 버전이며, `minSdkVersion=26`이라 Android 8.0 이상에서 사용 가능합니다.

앱에는 smoke 검증용 기본 대상과 업무형 SLA 검증용 고급 대상이 함께 들어 있습니다.

- 입력창: `accessibility_id=message_input`
- Echo 버튼: `accessibility_id=echo_button`
- Success 버튼: `accessibility_id=success_button`
- 상태 텍스트: `accessibility_id=status_text`
- 로그인: `accessibility_id=email_input`, `accessibility_id=password_input`, `accessibility_id=login_button`
- 대시보드/검색: `accessibility_id=dashboard_panel`, `accessibility_id=search_input`, `accessibility_id=search_button`
- 장애 대응: `accessibility_id=checkout_card`, `accessibility_id=open_checkout_detail`, `accessibility_id=ack_button`
- 설정/DR: `accessibility_id=alerts_toggle`, `accessibility_id=run_drill_button`

기본 입력, 검증, 스크린샷, 지표 수집 흐름은 웹앱에서 `Android Full Feature` suite를 실행합니다.
로그인, 검색, 중요도 필터, 장애 상세, 알림 토글, DR drill, 백그라운드 복귀와 SLA metric 기준선을 함께 보려면
`Android Field Ops Advanced SLA` suite를 실행합니다.

### macOS / Linux에서 재빌드

```bash
chmod +x test-apk/build_test_apk.sh
./test-apk/build_test_apk.sh
```

빌드 스크립트 기본값:

- `ANDROID_SDK_ROOT=$HOME/Library/Android/sdk`
- `BUILD_TOOLS_VERSION=35.0.0`
- `ANDROID_PLATFORM=35`
- `JAVA_HOME=/Applications/Android Studio.app/Contents/jbr/Contents/Home`

### Windows에서의 권장 사용법

- Windows에서는 커밋된 `test-apk/build/hspace-test-app-debug.apk`를 그대로 사용하는 편이 간단합니다.
- `test-apk/build_test_apk.sh`는 bash 스크립트라 Windows PowerShell/CMD에서는 바로 실행되지 않습니다.

## 실행 예제

### 웹앱 실행

```bash
./.venv/bin/python run_sla_web.py
```

기본 URL은 `http://127.0.0.1:8000`입니다. 포트를 바꾸려면 `SLA_WEB_PORT`를 지정합니다.

```bash
SLA_WEB_PORT=8010 ./.venv/bin/python run_sla_web.py
```

웹앱은 기본적으로 현재 작업 디렉터리에 `sla_app.db`, `suites/`, `artifacts/`를 사용합니다. 다른 위치를 쓰려면 `SLA_APP_HOME`을 지정합니다.
SQLite 파일만 별도 볼륨이나 경로에 두려면 `SLA_DB_PATH`를 지정합니다.

비전공자는 `Test Suites` 화면의 `Guided Builder`로 suite를 만들 수 있고, 개발자는 `YAML Editor` 또는 `suites/*.yaml` 파일을 직접 수정할 수 있습니다. Guided Builder의 `화면 요소` 영역은 현재 앱 화면을 스캔해서 입력칸, 버튼, 텍스트 후보를 보여주며, 각 요소에 가장 적절한 추천 동작을 먼저 제안합니다.

실행 결과는 `Run Detail`에서 확인합니다. 이 화면은 PASS/FAIL 원문 로그와 함께 `실행 분석`을 제공해 환경 문제, 요소 찾기 실패, 텍스트 검증 실패, 지표 위반처럼 다음에 확인할 지점을 분류합니다. 같은 suite의 이전 실행이 있으면 실행 시간 변화도 함께 표시합니다.

환경 문제를 먼저 확인하려면 `Settings` 화면의 `환경 진단`을 실행합니다. Android SDK, `adb`, emulator, Node.js, npm, Appium main script, 실행 중인 Appium 서버, AVD, UiAutomator2 드라이버 설치 여부를 한 번에 볼 수 있습니다.

운영/배포용 HTTP endpoint:

| Endpoint | 용도 |
| --- | --- |
| `GET /healthz` | 프로세스가 응답 가능한지 확인하는 liveness check입니다. |
| `GET /readyz` | SQLite schema/WAL/quick_check, `suites/`, `artifacts/` 경로, 선택형 디스크 여유 공간 기준을 확인하는 readiness check입니다. |
| `GET /version` | 서비스 버전, build SHA, 실행 환경, 현재 큐 스냅샷, production 설정 상태를 JSON으로 확인합니다. |
| `GET /metrics` | suite/run 수, run status, HTTP 요청 수/시간, 백그라운드 큐 점유율, SQLite 상태를 Prometheus 텍스트 형식으로 노출합니다. Basic Auth가 켜져 있으면 인증이 필요합니다. |
| `GET /runs/{run_id}/report.json` | 실행 상세, 분석, metric 비교, artifact URL을 포함한 JSON 보고서를 내려받습니다. |

모든 응답에는 `X-Request-ID`가 포함됩니다. 리버스 프록시나 호출자가 안전한 `X-Request-ID`를 보내면 그대로 이어받고, 없거나 허용되지 않는 값이면 서버가 새 ID를 생성합니다. 요청 완료 로그에도 같은 ID, method, path, status, duration이 남습니다.

### Docker Compose로 웹앱 실행

컨테이너 실행은 웹 UI, SQLite 저장소, 스위트/아티팩트 관리를 재현 가능하게 띄우는 용도입니다. Android Emulator와 Appium 서버는 호스트 또는 별도 장비에서 준비하고, 컨테이너는 `APPIUM_URL`로 그 서버에 연결합니다.
`.dockerignore`는 로컬 DB, 아티팩트, `.env`, 캐시, 패키징 산출물을 이미지 빌드 컨텍스트에서 제외합니다. 운영 데이터는 이미지가 아니라 `/data` 볼륨과 백업 ZIP으로 관리합니다.

```bash
docker compose up --build
```

기본 Compose 설정:

- 웹 URL: `http://127.0.0.1:8010`
- 앱 데이터 루트: `/data`
- 스위트 파일: 호스트 `./suites` -> 컨테이너 `/data/suites`
- 아티팩트: 호스트 `./artifacts` -> 컨테이너 `/data/artifacts`
- SQLite: named volume `sla-db`의 `/data/db/sla_app.db`
- Appium 연결: `http://host.docker.internal:4723`
- 실행 큐: 기본 워커 1개, 대기열 10개
- 컨테이너 정책: `init: true`, `restart: unless-stopped`, 기본 stop grace `45s`
- 컨테이너 보안: non-root 사용자, read-only root filesystem, `/tmp` tmpfs, `cap_drop: ALL`, `no-new-privileges`
- 로그 레벨: 기본 `INFO`, `SLA_LOG_LEVEL=WARNING`/`DEBUG`로 조정 가능
- Appium readiness: 기본 꺼짐, `SLA_READY_CHECK_APPIUM=true`면 `/readyz`가 `APPIUM_URL`의 `/status`까지 확인
- Docker 이미지 자체에도 `/readyz` 기반 healthcheck가 포함되어 있고, Compose healthcheck도 같은 readiness 기준을 사용합니다.

운영에서 UI와 API를 보호하려면 Basic Auth 환경 변수를 같이 지정합니다. `healthz`, `readyz`는 로드밸런서와 오케스트레이터가 확인할 수 있도록 인증 없이 열어둡니다.

```bash
SLA_ENV=production \
SLA_BUILD_SHA="$(git rev-parse --short HEAD)" \
SLA_BASIC_AUTH_USER=operator \
SLA_BASIC_AUTH_PASSWORD="$(openssl rand -base64 32)" \
SLA_CSRF_SECRET="$(openssl rand -base64 32)" \
SLA_TRUSTED_ORIGINS='https://sla.example.com' \
SLA_ALLOWED_HOSTS='sla.example.com,127.0.0.1,localhost' \
SLA_PROXY_HEADERS=true \
SLA_FORWARDED_ALLOW_IPS='127.0.0.1' \
docker compose up --build
```

Basic Auth는 자격 증명을 요청마다 전송하므로 외부에 노출할 때는 HTTPS 또는 HTTPS를 종료하는 리버스 프록시 뒤에서 사용하세요. `SLA_BASIC_AUTH_PASSWORD`는 16자 이상, `SLA_CSRF_SECRET`은 32자 이상으로 설정하고 `change-me`, `secret`, `long-random-secret` 같은 placeholder를 쓰지 마세요. `SLA_CSRF_SECRET`은 여러 컨테이너/프로세스를 동시에 띄울 때 같은 값으로 고정해야 하고, `SLA_TRUSTED_ORIGINS`에는 브라우저가 접근하는 외부 origin을 쉼표로 넣습니다. `SLA_ALLOWED_HOSTS`를 설정하면 지정한 Host 헤더만 허용합니다. HTTPS 종료 프록시 뒤에서는 `SLA_PROXY_HEADERS=true`와 `SLA_FORWARDED_ALLOW_IPS`로 신뢰할 프록시 IP 또는 사설망 범위를 지정해야 `X-Forwarded-Proto` 기반 Origin 판정이 맞습니다. 서브패스에 붙이면 `SLA_ROOT_PATH=/sla`처럼 설정합니다.

`SLA_ENV=production`에서는 `/readyz`가 Basic Auth, CSRF secret, 허용 Host, trusted origin, 실제 build SHA가 설정됐는지 검사합니다. 누락되거나 약한 placeholder 값이면 `503`을 반환하므로 배포 전 `.env`를 채우세요.

컨테이너 로그가 너무 많거나 디버깅이 필요하면 `SLA_LOG_LEVEL`을 `WARNING`, `INFO`, `DEBUG` 중 하나로 조정합니다. 이 값은 Uvicorn 로그와 앱의 request completion 로그에 함께 적용됩니다.
데이터 볼륨 용량을 readiness에서 같이 막고 싶으면 `SLA_MIN_FREE_DISK_MB=1024`처럼 최소 여유 공간을 MB 단위로 지정합니다. 기본값 `0`은 이 체크를 비활성화합니다.
웹 컨테이너가 Appium 서버까지 붙을 수 있어야만 트래픽을 받을 수 있게 하려면 `SLA_READY_CHECK_APPIUM=true`를 설정합니다. 기본값은 `false`라서 Appium을 호스트에서 늦게 켜거나 실행 시 자동 시작하는 로컬 운영을 막지 않습니다.
Compose는 기본적으로 `restart: unless-stopped`로 웹 컨테이너를 재시작하고, `SLA_CONTAINER_STOP_GRACE_PERIOD=45s` 동안 정상 종료를 기다립니다. 이 값은 앱의 `SLA_GRACEFUL_SHUTDOWN_TIMEOUT=30`보다 길게 두는 편이 안전합니다. 컨테이너는 root filesystem을 읽기 전용으로 두고 `/data` 볼륨과 `/tmp` tmpfs만 쓰기 경로로 사용합니다.

SQLite DB의 schema version이 현재 앱보다 높으면 서버는 시작을 중단하고 DB를 다운그레이드하지 않습니다. 백업을 복구하거나 이미지를 되돌릴 때는 DB를 만든 앱 버전과 실행할 이미지 버전을 맞추세요.

스위트 실행 요청은 HTTP 요청을 오래 붙잡지 않고 백그라운드 실행 큐에 들어갑니다. `SLA_RUN_WORKERS`는 동시에 실행할 작업자 수, `SLA_RUN_QUEUE_LIMIT`은 실행 중/대기 중 작업의 최대 개수입니다. Android Emulator/Appium 장비 하나를 공유하는 환경에서는 기본값 `1`을 유지하는 편이 안전합니다.
`/version`의 `runtime.run_queue`와 `/metrics`의 `sla_run_queue_*` 지표로 현재 실행 중/대기 중/사용 가능 슬롯을 확인할 수 있습니다.

서버가 정상 종료될 때 아직 시작하지 못한 `QUEUED` 실행은 즉시 `ERROR`로 닫습니다. 서버가 비정상 종료되거나 재시작되면 인메모리 실행 큐는 이어서 처리할 수 없으므로 기본적으로 남아 있던 `QUEUED`/`RUNNING` 실행을 시작 시점에 `ERROR`로 회수합니다. 이 동작은 `SLA_RECOVER_INCOMPLETE_RUNS=false`로 끌 수 있지만, 단일 인스턴스 배포에서는 기본값을 유지하는 편이 운영 상태가 명확합니다.

호스트에서 Appium을 직접 켜는 경우:

```bash
appium --allow-insecure uiautomator2:adb_shell
```

컨테이너 상태 확인:

```bash
curl http://127.0.0.1:8010/healthz
curl http://127.0.0.1:8010/readyz
curl -u "$SLA_BASIC_AUTH_USER:$SLA_BASIC_AUTH_PASSWORD" http://127.0.0.1:8010/version
curl -u "$SLA_BASIC_AUTH_USER:$SLA_BASIC_AUTH_PASSWORD" http://127.0.0.1:8010/metrics
```

릴리즈 전 로컬 검증:

```bash
make release-check
```

이 명령은 Python 컴파일, 전체 테스트, Docker 이미지 빌드, local 컨테이너 `healthz`/`readyz`/`version`/`metrics` 스모크, production 컨테이너 readiness/Auth/metrics 스모크, Compose 설정 검증을 함께 실행합니다.

### 운영 백업과 이력 정리

Settings 화면의 `운영 데이터` 영역에서 현재 DB 경로, 실행 이력 수, 아티팩트 용량, 접근 보호 상태를 확인할 수 있습니다.

- `백업 ZIP 다운로드`: SQLite 스냅샷, `suites/`, `artifacts/`, 백업 manifest를 하나의 ZIP으로 내려받습니다.
- `오래된 실행 정리`: 최근 N개 실행은 보존하고, 지정한 일수보다 오래된 실행 row와 연결된 아티팩트 디렉터리를 삭제합니다.
- `실행 이력과 연결되지 않은 아티팩트도 정리`: DB에는 없는 실행 디렉터리까지 함께 삭제합니다.

백업 ZIP은 `suites/`, `artifacts/` 안의 일반 파일만 포함하며 symlink나 데이터 루트 밖으로 해석되는 파일은 건너뜁니다. 건너뛴 파일 수는 `manifest.json`의 `skipped_unsafe_files`에 기록됩니다.

정리 폼의 기본값은 아래 환경 변수로 바꿀 수 있습니다. 자동 삭제는 하지 않으며, 화면에서 정리 버튼을 눌렀을 때만 적용됩니다.

```bash
SLA_RETENTION_KEEP_LAST=100
SLA_RETENTION_DAYS=30
```

직접 다운로드 URL:

```bash
curl -u "$SLA_BASIC_AUTH_USER:$SLA_BASIC_AUTH_PASSWORD" -o sla-backup.zip http://127.0.0.1:8010/settings/backup.zip
```

복구는 빈 데이터 디렉터리에 수행하는 것이 기본입니다. 기존 데이터를 덮어써야 할 때만 `--force`를 사용합니다.

```bash
sla-restore-backup sla-backup.zip --base-dir /data --db-path /data/db/sla_app.db
sla-restore-backup sla-backup.zip --base-dir /data --db-path /data/db/sla_app.db --force
```

상세 운영 절차는 [Operations Guide](docs/operations.md)를 참고하세요.

### CLI로 APK 실행

```bash
./.venv/bin/python launch_android_app.py \
  --start-appium \
  --apk test-apk/build/hspace-test-app-debug.apk
```

### Windows PowerShell에서 APK 실행

```powershell
.\.venv\Scripts\python.exe .\launch_android_app.py `
  --start-appium `
  --apk .\test-apk\build\hspace-test-app-debug.apk
```

### 이미 설치된 앱 실행

```bash
./.venv/bin/python launch_android_app.py \
  --start-appium \
  --app-package com.example.myapp \
  --app-activity .MainActivity
```

### 스플래시 Activity가 따로 있는 앱

```bash
./.venv/bin/python launch_android_app.py \
  --start-appium \
  --app-package com.example.myapp \
  --app-activity .SplashActivity \
  --app-wait-activity "com.example.myapp.*"
```

앱 실행 직후 Google 로그인, 권한, 시스템 설정처럼 다른 package 화면으로 넘어가는 앱은 package 대기도 풀어야 합니다.

```bash
./.venv/bin/python launch_android_app.py \
  --start-appium \
  --app-package com.google.android.calendar \
  --app-activity com.android.calendar.AllInOneActivity \
  --app-wait-activity "*" \
  --app-wait-package "*"
```

## SLA 테스트 스위트 YAML

현재 지원하는 주요 액션은 아래와 같습니다.

- `launch_app`
- `terminate_app`
- `activate_app`
- `background_app`
- `tap`
- `input`
- `back`
- `swipe`
- `scroll`
- `scroll_to_text`
- `wait`
- `assert_text`
- `assert_not_text`
- `assert_exists`
- `assert_not_exists`
- `assert_visible`
- `assert_enabled`
- `assert_attribute`
- `assert_current_package`
- `assert_current_activity`
- `screenshot`
- `collect_metrics`
- `metric_check`

상세 스키마, selector 형식, 액션별 필드, 전체 예시는 웹앱의 `YAML Guide` 메뉴 또는 [SLA YAML Guide](docs/yaml-guide.md)를 참고하세요.

예시:

```yaml
name: Android Smoke
app:
  platform: android
  apk: test-apk/build/hspace-test-app-debug.apk
thresholds:
  max_duration_ms: 30000
  max_assertion_failures: 0
  max_metric_violations: 0
scenarios:
  - name: launch and capture
    steps:
      - action: launch_app
      - action: wait
        timeout_ms: 1000
      - action: screenshot
        name: launch
```

SLA 판정은 시나리오 실행 성공 여부, `duration_ms`, assertion 실패 수, metric 위반 수를 기준으로 `PASS` 또는 `FAIL`을 저장합니다. 실행 메타데이터와 판정 결과는 SQLite에 저장하고, 스크린샷은 `artifacts/<run_id>/` 아래에 저장합니다.

`collect_metrics`는 현재 수집 가능한 값을 기준으로 `memory_mb`, `launch_time_ms`, `appium_new_session_ms`, `appium_command_count`, `appium_command_avg_ms`, `appium_command_max_ms`, `cpu_percent`, `logcat_error_count`를 반환합니다. Appium 명령 지연 지표는 `eventTimings` capability로 수집하며 SLA Test Runner가 기본으로 켭니다. `memory_mb`, `cpu_percent`, `logcat_error_count`는 Android shell 접근이 필요하므로 수동 Appium 서버를 쓸 때는 아래 insecure feature를 허용해야 합니다.

## 자주 쓰는 옵션

- `--avd`: 특정 AVD를 강제로 지정
- `--serial`: 이미 실행 중인 특정 에뮬레이터를 지정
- `--android-sdk-root`: Android SDK 루트 경로 지정
- `--emulator-path`: emulator 실행 파일 경로 지정
- `--adb-path`: adb 실행 파일 경로 지정
- `--node-path`: Node.js 경로 직접 지정
- `--npm-path`: npm 경로 직접 지정
- `--appium-main-script`: Appium `main.js` 경로 직접 지정
- `--no-reset`: 앱 데이터를 유지
- `--app-wait-activity`: 실행 후 대기할 activity 패턴 지정
- `--app-wait-package`: 실행 후 대기할 package 패턴 지정
- `--launch-wait 10`: 앱 실행 후 10초 유지
- `--keep-appium-running`: 스크립트가 띄운 Appium 서버를 종료하지 않음

## 동작 순서

CLI 런처와 웹앱의 Android 실행 어댑터는 같은 Android/Appium 흐름을 사용합니다.

1. 실행 중인 Android Emulator가 있는지 확인
2. 없으면 AVD를 직접 사용하거나, 호스트 아키텍처에 맞는 AVD를 자동 선택해 부팅
3. `sys.boot_completed=1`이 될 때까지 대기
4. Appium 서버에 연결하거나 필요 시 Python `AppiumService`로 시작
5. `apk` 또는 `appPackage/appActivity` capability로 세션 생성
6. YAML step 실행, 스크린샷/로그 저장, SLA 판정 저장

웹앱이 Appium 서버를 자동 시작할 때는 `collect_metrics`의 shell 기반 지표를 위해 `uiautomator2:adb_shell` insecure feature를 허용합니다. 수동으로 Appium 서버를 띄우는 경우 메모리/CPU/logcat metric 수집을 쓰려면 같은 옵션을 지정하세요.

```bash
appium --allow-insecure uiautomator2:adb_shell
```

## 검증

```bash
python3 -m py_compile launch_android_app.py $(find sla_launcher sla_app -name '*.py')
python3 -m unittest discover
python3 launch_android_app.py --help
```

Android 실제 실행 검증은 Appium 2, `uiautomator2`, 호스트 아키텍처에 맞는 AVD가 준비된 상태에서 수행합니다.

## 문제 해결

호스트 아키텍처와 맞는 AVD를 찾지 못했다는 오류가 나오면:

1. 현재 머신의 CPU 아키텍처를 확인합니다.
2. AVD가 실제로 존재하는지 확인합니다.
3. AVD `config.ini`의 `abi.type`이 현재 머신과 맞는지 확인합니다.
4. 필요한 system image를 다시 설치하고 AVD를 새로 만듭니다.

Appium 자동 탐색이 실패하면 아래처럼 경로를 직접 넘길 수 있습니다.

웹앱 Run Detail에서 `환경/실행` 또는 `launcher exited with code 1`이 보이면 Android/Appium 실행 준비 단계에서 실패한 것입니다. Settings 화면의 `환경 진단`에서 Android SDK, AVD, Node.js, Appium 패키지, UiAutomator2 드라이버 상태를 먼저 확인하세요. Appium 자동 시작이 실패하는 경우에는 `node`, `npm`, Appium main script 경로를 환경 변수로 직접 지정할 수 있습니다.

macOS / Linux:

```bash
./.venv/bin/python launch_android_app.py \
  --start-appium \
  --node-path /absolute/path/to/node \
  --appium-main-script /absolute/path/to/appium/build/lib/main.js \
  --app-package com.example.myapp \
  --app-activity .MainActivity
```

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe .\launch_android_app.py `
  --start-appium `
  --android-sdk-root "$env:LOCALAPPDATA\Android\Sdk" `
  --emulator-path "$env:LOCALAPPDATA\Android\Sdk\emulator\emulator.exe" `
  --adb-path "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" `
  --app-package com.example.myapp `
  --app-activity .MainActivity
```
