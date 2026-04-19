# Android Emulator + Appium 자동 실행 예제

이 예제는 Android Studio의 Android Emulator를 부팅한 뒤, Python의 `Appium-Python-Client`로 Appium 서버와 앱 세션을 제어해 앱을 자동 실행합니다.

지원 방식:

- `APK` 파일을 설치하고 실행
- 이미 설치된 앱을 `package/activity`로 실행

현재 로컬 환경에서 확인된 값:

- Android SDK: `/Users/dpp/Library/Android/sdk`
- 기본 AVD: `Medium_Phone_API_36_ARM64`
- Python 가상환경: `.venv`
- Python 라이브러리: `Appium-Python-Client==5.3.0` 설치 완료
- Appium 서버 패키지: 사용자 환경에 설치 완료
- Appium Android 드라이버: `uiautomator2` 설치 완료
- 기존 `Medium_Phone_API_36.0` AVD는 `x86_64` 이미지라 Apple Silicon에서 부팅되지 않음

## 1. 사전 준비

### Python 라이브러리 설치

이미 설치해둔 상태이지만, 다시 설치하려면 아래를 사용하면 됩니다.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Appium 서버 준비

`Appium 2`와 `uiautomator2` 드라이버가 필요합니다.

```bash
npm install -g appium
appium driver install uiautomator2
```

이 예제 스크립트는 서버를 직접 셸 명령으로 띄우지 않고, Python의 `AppiumService`로 Appium을 시작합니다. 단, 내부적으로는 설치된 Appium 서버 패키지가 필요합니다.

## 2. 파일 설명

- [launch_android_app.py](/Users/dpp/Desktop/HSPACE/SLA/launch_android_app.py): 에뮬레이터 부팅, Appium 서버 연결, 앱 실행을 처리하는 메인 스크립트
- [requirements.txt](/Users/dpp/Desktop/HSPACE/SLA/requirements.txt): Python 의존성

## 3. 실행 예제

### 3-1. APK를 설치해서 실행

```bash
./.venv/bin/python launch_android_app.py \
  --start-appium \
  --apk /absolute/path/to/app-debug.apk
```

### 3-2. 이미 설치된 앱 실행

```bash
./.venv/bin/python launch_android_app.py \
  --start-appium \
  --app-package com.example.myapp \
  --app-activity .MainActivity
```

### 3-3. 스플래시 Activity가 따로 있는 앱

```bash
./.venv/bin/python launch_android_app.py \
  --start-appium \
  --app-package com.example.myapp \
  --app-activity .SplashActivity \
  --app-wait-activity "com.example.myapp.*"
```

## 4. 자주 쓰는 옵션

- `--avd`: 실행할 AVD 이름. 기본값은 `Medium_Phone_API_36_ARM64`
- `--serial`: 이미 실행 중인 특정 에뮬레이터를 지정
- `--android-sdk-root`: Android SDK 루트 경로 지정
- `--emulator-path`: emulator 실행 파일 경로 지정
- `--adb-path`: adb 실행 파일 경로 지정
- `--node-path`: Node.js 경로를 직접 지정
- `--npm-path`: npm 경로를 직접 지정
- `--appium-main-script`: Appium의 `main.js` 경로를 직접 지정
- `--no-reset`: 앱 데이터를 유지
- `--launch-wait 10`: 앱 실행 후 10초 유지
- `--keep-appium-running`: 스크립트가 띄운 Appium 서버를 종료하지 않음

## 5. 동작 순서

스크립트는 아래 순서로 동작합니다.

1. 실행 중인 Android Emulator가 있는지 확인
2. 없으면 지정한 AVD를 부팅
3. `sys.boot_completed=1`이 될 때까지 대기
4. Python `AppiumService`로 Appium 서버 시작 또는 기존 서버 연결
5. `apk` 또는 `appPackage/appActivity` capability로 세션 생성
6. 앱이 실행되면 잠시 유지 후 세션 종료

## 6. 참고

Appium 자동 탐색이 실패하면 아래처럼 경로를 명시할 수 있습니다.

```bash
./.venv/bin/python launch_android_app.py \
  --start-appium \
  --node-path /opt/homebrew/Cellar/node@22/22.22.2/bin/node \
  --appium-main-script /Users/dpp/node_modules/appium/build/lib/main.js \
  --app-package com.example.myapp \
  --app-activity .MainActivity
```
