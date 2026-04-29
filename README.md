# HSPACE SLA Test Runner

이 프로젝트는 Android 앱의 SLA 테스트를 로컬에서 만들고 실행하는 Python 기반 테스트 러너입니다. 웹 UI에서 YAML 테스트 스위트를 생성/수정/실행하고, 실행 결과를 `PASS`/`FAIL`과 액션별 로그로 확인할 수 있습니다.

첫 MVP는 Android Emulator + Appium을 지원합니다. 기존 CLI 런처도 유지되어 APK 실행 검증이나 자동화 디버깅에 그대로 사용할 수 있습니다.

지원 방식:

- FastAPI 웹앱에서 SLA 테스트 스위트 관리/실행
- YAML 테스트 정의를 파일로 버전관리
- APK 파일을 설치하고 실행
- 이미 설치된 앱을 `package/activity`로 실행

핵심 파일:

- `launch_android_app.py`: 에뮬레이터 부팅, Appium 서버 연결, 앱 실행
- `run_sla_web.py`: 로컬 SLA 테스트 웹앱 실행
- `sla_launcher/`: 런처 내부 구현 패키지
- `sla_app/`: 테스트 정의, 실행 엔진, 저장소, 웹 UI
- `suites/`: YAML 테스트 스위트
- `artifacts/`: 실행별 스크린샷/로그 저장 위치
- `requirements.txt`: Python 의존성
- `test-apk/build/hspace-test-app-debug.apk`: 바로 설치 가능한 검증용 APK
- `test-apk/build_test_apk.sh`: 검증용 APK 재빌드 스크립트

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

이 저장소에는 Appium 연결 검증용 최소 Android 앱이 포함되어 있습니다.

바로 사용 가능한 APK:

- `test-apk/build/hspace-test-app-debug.apk`

기본 package/activity:

- Package: `com.hspace.testapp`
- Activity: `com.hspace.testapp.MainActivity`

이 APK는 현재 네이티브 라이브러리를 포함하지 않으므로 CPU 아키텍처와 무관하게 설치 가능합니다. 실질적인 제약은 Android 버전이며, `minSdkVersion=26`이라 Android 8.0 이상에서 사용 가능합니다.

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

비전공자는 `Test Suites` 화면의 `Guided Builder`로 suite를 만들 수 있고, 개발자는 `YAML Editor` 또는 `suites/*.yaml` 파일을 직접 수정할 수 있습니다.

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

## SLA 테스트 스위트 YAML

첫 MVP에서 지원하는 액션은 아래 9개입니다.

- `launch_app`
- `tap`
- `input`
- `wait`
- `assert_text`
- `assert_exists`
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

웹앱 Run Detail에서 `launcher exited with code 1`이 보이면 Android/Appium 실행 준비 단계에서 실패한 것입니다. Settings 화면에서 Android SDK, AVD, Appium 상태를 먼저 확인하세요. Appium 자동 시작이 실패하는 경우에는 `node`, `npm`, Appium main script 경로를 환경 변수로 직접 지정할 수 있습니다.

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
