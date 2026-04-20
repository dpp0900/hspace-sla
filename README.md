# Android Emulator + Appium 자동 실행

이 프로젝트는 Android Emulator를 부팅한 뒤 Python의 `Appium-Python-Client`로 Appium 세션을 만들고 앱을 자동 실행합니다.

지원 방식:

- APK 파일을 설치하고 실행
- 이미 설치된 앱을 `package/activity`로 실행

핵심 파일:

- `launch_android_app.py`: 에뮬레이터 부팅, Appium 서버 연결, 앱 실행
- `requirements.txt`: Python 의존성
- `test-apk/build_test_apk.sh`: 로컬 검증용 테스트 APK 빌드 스크립트

## 1. 에뮬레이터 자동 선택 규칙

스크립트는 아래 순서로 디바이스를 결정합니다.

1. `--serial`을 주면 해당 에뮬레이터를 그대로 사용
2. 이미 실행 중인 Android Emulator가 있으면 첫 번째 에뮬레이터를 재사용
3. `--avd` 또는 `ANDROID_AVD`를 주면 해당 AVD를 사용
4. 아무 것도 지정하지 않으면 호스트 CPU 아키텍처에 맞는 AVD를 자동 선택

자동 선택은 `~/.android/avd` 또는 `ANDROID_AVD_HOME` 아래의 AVD 설정을 읽어서 `abi.type`, `hw.cpu.arch`, system image 경로를 기준으로 결정합니다.

- `arm64`, `aarch64` 호스트: `arm64-v8a` AVD 우선
- `x86_64`, `amd64` 호스트: `x86_64`, 그다음 `x86` AVD 우선

즉, AVD 이름을 특정 규칙으로 맞출 필요는 없습니다. 이름이 아니라 실제 AVD ABI를 보고 선택합니다.

## 2. 환경 구성 가이드

아래 순서대로 준비하면 새 머신에서도 바로 실행할 수 있습니다. 기준 OS는 macOS이며, SDK 경로가 다르면 환경 변수나 CLI 옵션으로 덮어쓰면 됩니다.

### 2-1. Android Studio / SDK 설치

Android Studio를 설치한 뒤 SDK Manager에서 아래 구성요소를 설치합니다.

- `Android SDK Platform-Tools`
- `Android Emulator`
- `Android SDK Command-line Tools (latest)`
- `Android SDK Platform 35`
- `Android SDK Build-Tools 35.0.0`
- `Android SDK Platform 36`
- 본인 CPU 아키텍처에 맞는 Android 36 system image

CLI로 설치하려면:

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

라이선스 동의가 필요하면 아래를 한 번 실행합니다.

```bash
sdkmanager --licenses
```

### 2-2. 호스트 아키텍처 확인

```bash
uname -m
```

- Apple Silicon Mac이면 보통 `arm64`
- Intel/AMD 머신이면 보통 `x86_64`

### 2-3. 아키텍처에 맞는 system image 설치

Apple Silicon:

```bash
sdkmanager --install "system-images;android-36;google_apis_playstore;arm64-v8a"
```

Intel/AMD:

```bash
sdkmanager --install "system-images;android-36;google_apis_playstore;x86_64"
```

### 2-4. AVD 생성

Apple Silicon 예시:

```bash
avdmanager create avd \
  -n Medium_Phone_API_36_ARM64 \
  -k "system-images;android-36;google_apis_playstore;arm64-v8a" \
  -d medium_phone
```

Intel/AMD 예시:

```bash
avdmanager create avd \
  -n Medium_Phone_API_36_X86_64 \
  -k "system-images;android-36;google_apis_playstore;x86_64" \
  -d medium_phone
```

중요:

- Apple Silicon에서는 `x86_64` system image가 정상 부팅되지 않을 수 있습니다.
- 자동 선택을 쓰려면 현재 머신 아키텍처에 맞는 AVD가 최소 1개는 있어야 합니다.
- AVD 저장 경로를 기본값이 아닌 곳으로 바꿨다면 `ANDROID_AVD_HOME`을 같이 설정하세요.

### 2-5. Python 가상환경 구성

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

현재 Python 의존성은 아래 한 개입니다.

```text
Appium-Python-Client==5.3.0
```

### 2-6. Appium 2 설치

Node.js가 설치되어 있어야 합니다.

```bash
npm install -g appium
appium driver install uiautomator2
```

확인:

```bash
appium driver list --installed
```

이 스크립트는 `--start-appium` 옵션을 주면 Python의 `AppiumService`로 Appium 서버를 띄웁니다. 다만 내부적으로는 위처럼 Appium 2와 `uiautomator2` 드라이버가 설치되어 있어야 합니다.

### 2-7. 쉘 환경 변수 권장값

`~/.zshrc` 같은 셸 설정에 아래를 넣어두면 편합니다.

```bash
export ANDROID_SDK_ROOT="$HOME/Library/Android/sdk"
export ANDROID_HOME="$ANDROID_SDK_ROOT"
export PATH="$ANDROID_SDK_ROOT/platform-tools:$ANDROID_SDK_ROOT/emulator:$ANDROID_SDK_ROOT/cmdline-tools/latest/bin:$PATH"
export JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home"
```

SDK 위치가 다르면 `ANDROID_SDK_ROOT`만 본인 환경에 맞게 바꾸면 됩니다.

## 3. 테스트 APK 빌드

이 저장소에는 Appium 연결 검증용 최소 Android 앱이 포함되어 있습니다.

```bash
chmod +x test-apk/build_test_apk.sh
./test-apk/build_test_apk.sh
```

생성물:

- `test-apk/build/hspace-test-app-debug.apk`

기본 package/activity:

- Package: `com.hspace.testapp`
- Activity: `com.hspace.testapp.MainActivity`

빌드 스크립트는 기본적으로 아래 값을 사용합니다.

- `ANDROID_SDK_ROOT=$HOME/Library/Android/sdk`
- `BUILD_TOOLS_VERSION=35.0.0`
- `ANDROID_PLATFORM=35`
- `JAVA_HOME=/Applications/Android Studio.app/Contents/jbr/Contents/Home`

필요하면 환경 변수로 덮어쓸 수 있습니다.

## 4. 실행 예제

### 4-1. APK를 설치해서 실행

```bash
./.venv/bin/python launch_android_app.py \
  --start-appium \
  --apk /absolute/path/to/app-debug.apk
```

### 4-2. 이미 설치된 앱 실행

```bash
./.venv/bin/python launch_android_app.py \
  --start-appium \
  --app-package com.example.myapp \
  --app-activity .MainActivity
```

### 4-3. 스플래시 Activity가 따로 있는 앱

```bash
./.venv/bin/python launch_android_app.py \
  --start-appium \
  --app-package com.example.myapp \
  --app-activity .SplashActivity \
  --app-wait-activity "com.example.myapp.*"
```

### 4-4. 테스트 APK로 바로 검증

```bash
./.venv/bin/python launch_android_app.py \
  --start-appium \
  --apk test-apk/build/hspace-test-app-debug.apk
```

## 5. 자주 쓰는 옵션

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

## 6. 동작 순서

1. 실행 중인 Android Emulator가 있는지 확인
2. 없으면 AVD를 직접 사용하거나, 호스트 아키텍처에 맞는 AVD를 자동 선택해 부팅
3. `sys.boot_completed=1`이 될 때까지 대기
4. Python `AppiumService`로 Appium 서버 시작 또는 기존 서버 연결
5. `apk` 또는 `appPackage/appActivity` capability로 세션 생성
6. 앱이 실행되면 잠시 유지 후 세션 종료

## 7. 문제 해결

호스트 아키텍처와 맞는 AVD를 찾지 못했다는 오류가 나오면:

1. `uname -m`으로 현재 머신 아키텍처를 확인합니다.
2. `ls ~/.android/avd`로 실제 AVD가 존재하는지 확인합니다.
3. `~/.android/avd/<name>.avd/config.ini`의 `abi.type`이 현재 머신과 맞는지 확인합니다.
4. 필요한 system image를 다시 설치하고 AVD를 새로 만듭니다.

Appium 자동 탐색이 실패하면 아래처럼 경로를 직접 넘길 수 있습니다.

```bash
./.venv/bin/python launch_android_app.py \
  --start-appium \
  --node-path /absolute/path/to/node \
  --appium-main-script /absolute/path/to/appium/build/lib/main.js \
  --app-package com.example.myapp \
  --app-activity .MainActivity
```
