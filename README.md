# Android Emulator + Appium 자동 실행

이 프로젝트는 Android Emulator를 부팅한 뒤 Python의 `Appium-Python-Client`로 Appium 세션을 만들고 앱을 자동 실행합니다.

지원 방식:

- APK 파일을 설치하고 실행
- 이미 설치된 앱을 `package/activity`로 실행

핵심 파일:

- `launch_android_app.py`: 에뮬레이터 부팅, Appium 서버 연결, 앱 실행
- `requirements.txt`: Python 의존성
- `test-apk/build/hspace-test-app-debug.apk`: 바로 설치 가능한 검증용 APK
- `test-apk/build_test_apk.sh`: 검증용 APK 재빌드 스크립트

## 1. 지원 범위

이 저장소에서 구분해야 하는 축은 두 가지입니다.

- CPU 아키텍처: `arm64/aarch64` 또는 `x86_64/amd64`
- OS: macOS, Windows, Linux

현재 상태 기준:

- 에뮬레이터 자동 선택 로직은 CPU 아키텍처 기준으로 동작합니다.
- 커밋된 테스트 APK는 네이티브 `.so`가 없는 순수 Dex APK라 CPU 아키텍처와 무관하게 설치할 수 있습니다.
- 실행 스크립트와 기본 경로는 macOS 기준으로 작성되어 있습니다.
- Windows와 Linux도 환경 변수와 실행 경로를 맞추면 사용할 수 있지만, README의 기본값은 macOS 기준입니다.
- `test-apk/build_test_apk.sh`는 bash 스크립트라 macOS/Linux에서 바로 사용 가능합니다. Windows에서는 커밋된 APK를 그대로 쓰는 편이 간단합니다.

## 2. 아키텍처별 빠른 판단표

- Apple Silicon Mac: 호스트 아키텍처는 보통 `arm64`, 필요한 AVD ABI는 `arm64-v8a`
- Intel Mac / 일반 PC: 호스트 아키텍처는 보통 `x86_64`, 필요한 AVD ABI는 `x86_64`
- Windows on ARM: 호스트 아키텍처는 보통 `ARM64`, 필요한 AVD ABI는 `arm64-v8a`

핵심 규칙:

- 호스트 CPU 아키텍처와 에뮬레이터 system image ABI를 맞춰야 합니다.
- APK 자체는 현재 아키텍처에 묶이지 않습니다.
- 문제는 APK보다 AVD/system image 쪽에서 더 자주 발생합니다.

## 3. 에뮬레이터 자동 선택 규칙

스크립트는 아래 순서로 디바이스를 결정합니다.

1. `--serial`을 주면 해당 에뮬레이터를 그대로 사용
2. 이미 실행 중인 Android Emulator가 있으면 첫 번째 에뮬레이터를 재사용
3. `--avd` 또는 `ANDROID_AVD`를 주면 해당 AVD를 사용
4. 아무 것도 지정하지 않으면 호스트 CPU 아키텍처에 맞는 AVD를 자동 선택

자동 선택은 `~/.android/avd` 또는 `ANDROID_AVD_HOME` 아래의 AVD 설정을 읽어서 `abi.type`, `hw.cpu.arch`, system image 경로를 기준으로 결정합니다.

- `arm64`, `aarch64` 호스트: `arm64-v8a` AVD 우선
- `x86_64`, `amd64` 호스트: `x86_64`, 그다음 `x86` AVD 우선

즉, AVD 이름을 특정 규칙으로 맞출 필요는 없습니다. 이름이 아니라 실제 AVD ABI를 보고 선택합니다.

## 4. 환경 구성 가이드

### 4-1. 호스트 아키텍처 확인

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

### 4-2. Android Studio / SDK 설치

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

### 4-3. 아키텍처에 맞는 system image 설치

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

### 4-4. AVD 생성

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

### 4-5. Python 가상환경 구성

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

현재 Python 의존성:

```text
Appium-Python-Client==5.3.0
```

### 4-6. Appium 2 설치

Node.js가 설치되어 있어야 합니다.

```bash
npm install -g appium
appium driver install uiautomator2
```

확인:

```bash
appium driver list --installed
```

이 스크립트는 `--start-appium` 옵션을 주면 Python의 `AppiumService`로 Appium 서버를 띄웁니다. 내부적으로는 Appium 2와 `uiautomator2` 드라이버가 설치되어 있어야 합니다.

### 4-7. 권장 환경 변수

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

- `launch_android_app.py`의 기본 SDK 경로는 macOS 값으로 설정되어 있습니다.
- Windows나 Linux에서는 `ANDROID_SDK_ROOT`, `ANDROID_HOME`, `ANDROID_ADB_PATH`, `ANDROID_EMULATOR_PATH`를 환경 변수로 지정하는 편이 안전합니다.

## 5. 테스트 APK

이 저장소에는 Appium 연결 검증용 최소 Android 앱이 포함되어 있습니다.

바로 사용 가능한 APK:

- `test-apk/build/hspace-test-app-debug.apk`

기본 package/activity:

- Package: `com.hspace.testapp`
- Activity: `com.hspace.testapp.MainActivity`

이 APK는 현재 네이티브 라이브러리를 포함하지 않으므로 CPU 아키텍처와 무관하게 설치 가능합니다. 실질적인 제약은 Android 버전이며, `minSdkVersion=26`이라 Android 8.0 이상에서 사용 가능합니다.

### 5-1. macOS / Linux에서 재빌드

```bash
chmod +x test-apk/build_test_apk.sh
./test-apk/build_test_apk.sh
```

빌드 스크립트 기본값:

- `ANDROID_SDK_ROOT=$HOME/Library/Android/sdk`
- `BUILD_TOOLS_VERSION=35.0.0`
- `ANDROID_PLATFORM=35`
- `JAVA_HOME=/Applications/Android Studio.app/Contents/jbr/Contents/Home`

### 5-2. Windows에서의 권장 사용법

- Windows에서는 커밋된 `test-apk/build/hspace-test-app-debug.apk`를 그대로 사용하는 편이 간단합니다.
- `test-apk/build_test_apk.sh`는 bash 스크립트라 Windows PowerShell/CMD에서는 바로 실행되지 않습니다.

## 6. 실행 예제

### 6-1. macOS / Linux에서 APK 실행

```bash
./.venv/bin/python launch_android_app.py \
  --start-appium \
  --apk test-apk/build/hspace-test-app-debug.apk
```

### 6-2. Windows PowerShell에서 APK 실행

```powershell
.\.venv\Scripts\python.exe .\launch_android_app.py `
  --start-appium `
  --apk .\test-apk\build\hspace-test-app-debug.apk
```

### 6-3. 이미 설치된 앱 실행

```bash
./.venv/bin/python launch_android_app.py \
  --start-appium \
  --app-package com.example.myapp \
  --app-activity .MainActivity
```

### 6-4. 스플래시 Activity가 따로 있는 앱

```bash
./.venv/bin/python launch_android_app.py \
  --start-appium \
  --app-package com.example.myapp \
  --app-activity .SplashActivity \
  --app-wait-activity "com.example.myapp.*"
```

## 7. 자주 쓰는 옵션

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

## 8. 동작 순서

1. 실행 중인 Android Emulator가 있는지 확인
2. 없으면 AVD를 직접 사용하거나, 호스트 아키텍처에 맞는 AVD를 자동 선택해 부팅
3. `sys.boot_completed=1`이 될 때까지 대기
4. Python `AppiumService`로 Appium 서버 시작 또는 기존 서버 연결
5. `apk` 또는 `appPackage/appActivity` capability로 세션 생성
6. 앱이 실행되면 잠시 유지 후 세션 종료

## 9. 문제 해결

호스트 아키텍처와 맞는 AVD를 찾지 못했다는 오류가 나오면:

1. 현재 머신의 CPU 아키텍처를 확인합니다.
2. AVD가 실제로 존재하는지 확인합니다.
3. AVD `config.ini`의 `abi.type`이 현재 머신과 맞는지 확인합니다.
4. 필요한 system image를 다시 설치하고 AVD를 새로 만듭니다.

Appium 자동 탐색이 실패하면 아래처럼 경로를 직접 넘길 수 있습니다.

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
