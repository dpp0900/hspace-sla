# SLA YAML Guide

이 문서는 SLA Test Runner에서 사용할 수 있는 YAML 스키마와 액션을 정리합니다. 현재 버전은 Android Appium 실행을 지원합니다.

## 기본 구조

```yaml
name: Android Smoke
app:
  platform: android
  apk: test-apk/build/hspace-test-app-debug.apk
thresholds:
  max_duration_ms: 30000
  max_assertion_failures: 0
  max_metric_violations: 0
  required_assertions: 0
scenarios:
  - name: launch and capture
    steps:
      - action: launch_app
      - action: wait
        timeout_ms: 1000
      - action: screenshot
        name: launch
```

루트 필드:

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| `name` | Yes | string | 테스트 스위트 이름입니다. 웹 UI와 실행 결과에 표시됩니다. |
| `app` | Yes | mapping | Android 앱 실행 대상입니다. |
| `thresholds` | No | mapping | 스위트 전체에 적용할 SLA 기준입니다. |
| `scenarios` | Yes | list | 실행할 시나리오 목록입니다. 최소 1개가 필요합니다. |

## App Target

`app.platform`은 현재 `android`만 지원합니다.

APK를 설치해서 실행하는 방식:

```yaml
app:
  platform: android
  apk: test-apk/build/hspace-test-app-debug.apk
```

이미 설치된 앱을 package/activity로 실행하는 방식:

```yaml
app:
  platform: android
  app_package: com.example.myapp
  app_activity: .MainActivity
  app_wait_activity: com.example.myapp.*
  app_wait_package: com.example.myapp
  no_reset: true
```

`app` 필드:

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| `platform` | No | string | 기본값은 `android`입니다. 다른 값은 현재 거부됩니다. |
| `apk` | Conditional | string | 설치 후 실행할 APK 경로입니다. `app_package`/`app_activity` 대신 사용할 수 있습니다. |
| `app_package` | Conditional | string | 이미 설치된 앱의 package 이름입니다. |
| `app_activity` | Conditional | string | 이미 설치된 앱의 launch activity입니다. |
| `app_wait_activity` | No | string | splash activity가 있을 때 Appium `appWaitActivity`로 전달됩니다. |
| `app_wait_package` | No | string | 앱 실행 후 다른 package 화면으로 전환될 수 있을 때 Appium `appWaitPackage`로 전달됩니다. Google 로그인/권한 화면까지 허용하려면 `*`를 사용할 수 있습니다. |
| `no_reset` | No | boolean | `true`면 앱 데이터를 유지합니다. 기본값은 `false`입니다. |

`apk` 상대 경로는 먼저 YAML 파일이 있는 디렉터리 기준으로 해석하고, 해당 파일이 없으면 현재 작업 디렉터리 기준으로 해석합니다.

## Thresholds

`thresholds`는 스위트 루트와 각 시나리오에 둘 수 있습니다.

```yaml
thresholds:
  max_duration_ms: 30000
  max_assertion_failures: 0
  max_metric_violations: 0
  required_assertions: 1
  metrics:
    memory_mb:
      max: 256
```

지원 필드:

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `max_duration_ms` | integer | none | 시나리오 최대 실행 시간입니다. 초과하면 `FAIL`입니다. |
| `max_assertion_failures` | integer | `0` | 허용할 assertion 실패 수입니다. |
| `max_metric_violations` | integer | `0` | 허용할 metric 위반 수입니다. |
| `required_assertions` | integer | `0` | 성공해야 하는 assertion step 최소 개수입니다. |
| `metrics` | mapping | `{}` | 수집된 metric에 적용할 `min`/`max` 제한입니다. |

Metric limit 형식:

```yaml
thresholds:
  metrics:
    memory_mb:
      min: 1
      max: 256
    launch_time_ms:
      max: 5000
    appium_command_max_ms:
      max: 500
    appium_command_avg_ms:
      max: 200
    appium_new_session_ms:
      max: 5000
    cpu_percent:
      max: 80
    logcat_error_count:
      max: 0
```

주의:

- `required_assertions`는 성공한 assertion 계열 step을 셉니다.
- `thresholds.metrics`는 `collect_metrics`로 수집된 metric을 평가합니다.
- 시나리오에 `thresholds`를 지정하면 해당 시나리오 기준으로 병합됩니다. 현재 구현에서 `max_assertion_failures`와 `max_metric_violations`는 생략 시 기본값 `0`이 적용되므로, 시나리오별로 완화된 값을 쓰려면 명시하세요.

## Scenarios

```yaml
scenarios:
  - name: login smoke
    thresholds:
      max_duration_ms: 15000
    steps:
      - action: launch_app
      - action: assert_text
        text: Login
```

Scenario 필드:

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| `name` | Yes | string | 시나리오 이름입니다. |
| `thresholds` | No | mapping | 이 시나리오에 적용할 SLA 기준입니다. |
| `steps` | Yes | list | 실행할 액션 목록입니다. 최소 1개가 필요합니다. |

Step은 위에서 아래로 순서대로 실행됩니다. 일반 실행 액션이 실패하면 해당 시나리오는 중단됩니다. Assertion과 metric check 실패는 결과에 실패로 기록됩니다.

## Selectors

`tap`, `input`, 요소 검증 액션은 selector를 사용할 수 있습니다.

지원 형식:

| Selector | Meaning |
| --- | --- |
| `id=com.example:id/login` | Appium `ID` locator |
| `resource-id=com.example:id/login` | Appium `ID` locator |
| `accessibility_id=Login` | Appium accessibility id |
| `accessibility-id=Login` | Appium accessibility id |
| `a11y=Login` | Appium accessibility id |
| `xpath=//android.widget.Button[@text="Login"]` | XPath |
| `uiautomator=new UiSelector().text("Login")` | Android UIAutomator |
| `android_uiautomator=new UiSelector().text("Login")` | Android UIAutomator |
| `/hierarchy/...` | XPath로 처리됩니다. |
| `com.example:id/login` | prefix가 없으면 Appium `ID`로 처리됩니다. |

`text`를 사용하는 액션은 내부적으로 text 기반 XPath를 사용합니다. `selector`와 `text`를 동시에 넣으면 현재 Android 어댑터는 `text`를 우선합니다.

## Actions

### `launch_app`

앱 실행 세션을 시작합니다. 에뮬레이터 선택/부팅, Appium 서버 연결 또는 자동 시작, Appium driver 생성이 여기서 일어납니다.

```yaml
- action: launch_app
```

필드:

| Field | Required | Description |
| --- | --- | --- |
| `action` | Yes | `launch_app` |

### `terminate_app`

현재 앱 또는 지정한 package를 종료합니다. cold start, 재시작 복구, 백그라운드 복귀 SLA를 분리해서 볼 때 사용합니다.

```yaml
- action: terminate_app
  package: com.example.myapp
```

필드:

| Field | Required | Description |
| --- | --- | --- |
| `package` | No | 종료할 package입니다. 생략하면 현재 package 또는 suite의 `app_package`를 사용합니다. |

### `activate_app`

현재 앱 또는 지정한 package를 foreground로 활성화합니다. 이 단계의 소요 시간은 이후 `collect_metrics`의 `launch_time_ms`로 반영됩니다.

```yaml
- action: activate_app
  package: com.example.myapp
```

필드:

| Field | Required | Description |
| --- | --- | --- |
| `package` | No | 활성화할 package입니다. 생략하면 현재 package 또는 suite의 `app_package`를 사용합니다. |

### `background_app`

앱을 지정 시간 동안 백그라운드로 보냈다가 복귀합니다.

```yaml
- action: background_app
  timeout_ms: 3000
```

필드:

| Field | Required | Description |
| --- | --- | --- |
| `timeout_ms` | No | 백그라운드에 머무를 시간입니다. 기본값은 `1000`입니다. |

### `tap`

요소를 찾아 탭합니다.

```yaml
- action: tap
  selector: id=com.example:id/login
  timeout_ms: 5000
```

또는 text로 찾을 수 있습니다.

```yaml
- action: tap
  text: Login
```

필드:

| Field | Required | Description |
| --- | --- | --- |
| `selector` | Conditional | `selector` 또는 `text` 중 하나가 필요합니다. |
| `text` | Conditional | 표시 텍스트로 요소를 찾습니다. |
| `timeout_ms` | No | 요소 탐색 제한 시간입니다. 기본값은 `5000`입니다. |

### `input`

요소를 찾아 값을 입력합니다. 입력 전 `clear()`를 시도합니다.

```yaml
- action: input
  selector: id=com.example:id/email
  value: user@example.com
  timeout_ms: 5000
```

필드:

| Field | Required | Description |
| --- | --- | --- |
| `selector` | Yes | 입력할 요소 selector입니다. |
| `value` | Yes | 입력할 값입니다. 문자열/숫자/boolean을 사용할 수 있으며 문자열로 변환됩니다. |
| `timeout_ms` | No | 요소 탐색 제한 시간입니다. 기본값은 `5000`입니다. |

### `back`

Android 뒤로가기 동작을 실행합니다.

```yaml
- action: back
```

필드:

| Field | Required | Description |
| --- | --- | --- |
| `action` | Yes | `back` |

### `swipe`

화면 전체 또는 지정한 요소 영역에서 스와이프합니다. 요소를 지정하지 않으면 현재 화면의 안전 영역을 사용합니다.

```yaml
- action: swipe
  direction: up
  percent: 0.75
```

필드:

| Field | Required | Description |
| --- | --- | --- |
| `selector` | No | 특정 요소 영역에서 제스처를 실행할 때 사용합니다. |
| `text` | No | 표시 텍스트로 요소 영역을 찾을 때 사용합니다. |
| `direction` | No | `up`, `down`, `left`, `right` 중 하나입니다. 기본값은 `up`입니다. |
| `percent` | No | 스와이프 비율입니다. `0`보다 크고 `1` 이하여야 합니다. 기본값은 `0.75`입니다. |

### `scroll`

화면 전체 또는 지정한 요소 영역에서 스크롤합니다.

```yaml
- action: scroll
  direction: down
  percent: 1.0
```

필드:

| Field | Required | Description |
| --- | --- | --- |
| `selector` | No | 특정 요소 영역에서 스크롤할 때 사용합니다. |
| `text` | No | 표시 텍스트로 요소 영역을 찾을 때 사용합니다. |
| `direction` | No | `up`, `down`, `left`, `right` 중 하나입니다. 기본값은 `down`입니다. |
| `percent` | No | 스크롤 비율입니다. 기본값은 `1.0`입니다. |

### `scroll_to_text`

스크롤 가능한 영역에서 특정 텍스트가 보일 때까지 이동합니다.

```yaml
- action: scroll_to_text
  text: Terms
  timeout_ms: 8000
```

필드:

| Field | Required | Description |
| --- | --- | --- |
| `text` | Yes | 찾을 텍스트입니다. |
| `timeout_ms` | No | 탐색 제한 시간입니다. 기본값은 `8000`입니다. |

### `wait`

지정한 시간만큼 대기합니다.

```yaml
- action: wait
  timeout_ms: 1000
```

필드:

| Field | Required | Description |
| --- | --- | --- |
| `timeout_ms` | No | 대기 시간입니다. 기본값은 `1000`입니다. |

### `assert_text`

현재 page source에 특정 텍스트가 포함되어 있는지 확인합니다.

```yaml
- action: assert_text
  text: Welcome
```

필드:

| Field | Required | Description |
| --- | --- | --- |
| `text` | Yes | 찾을 텍스트입니다. |

### `assert_not_text`

지정한 시간 안에 특정 텍스트가 현재 page source에서 사라졌는지 확인합니다. 에러 문구, 로딩 문구, 실패 배너가 남아 있지 않은지 검증할 때 사용합니다.

```yaml
- action: assert_not_text
  text: Error
  timeout_ms: 5000
```

필드:

| Field | Required | Description |
| --- | --- | --- |
| `text` | Yes | 없어야 하는 텍스트입니다. |
| `timeout_ms` | No | 텍스트가 사라질 때까지 기다릴 제한 시간입니다. 기본값은 `5000`입니다. |

### `assert_exists`

요소가 존재하는지 확인합니다.

```yaml
- action: assert_exists
  selector: id=com.example:id/home
  timeout_ms: 5000
```

또는 text로 확인할 수 있습니다.

```yaml
- action: assert_exists
  text: Home
```

필드:

| Field | Required | Description |
| --- | --- | --- |
| `selector` | Conditional | `selector` 또는 `text` 중 하나가 필요합니다. |
| `text` | Conditional | 표시 텍스트로 요소를 찾습니다. |
| `timeout_ms` | No | 요소 탐색 제한 시간입니다. 기본값은 `5000`입니다. |

### `assert_not_exists`

지정한 시간 안에 요소가 사라졌는지 확인합니다. 로딩 spinner, 에러 다이얼로그, 차단 overlay가 남아 있지 않은지 검증할 때 사용합니다.

```yaml
- action: assert_not_exists
  selector: id=com.example:id/error
  timeout_ms: 5000
```

필드:

| Field | Required | Description |
| --- | --- | --- |
| `selector` | Conditional | `selector` 또는 `text` 중 하나가 필요합니다. |
| `text` | Conditional | 표시 텍스트로 요소를 찾습니다. |
| `timeout_ms` | No | 요소가 사라질 때까지 기다릴 제한 시간입니다. 기본값은 `5000`입니다. |

### `assert_visible`

요소가 존재하고 화면에 표시되는지 확인합니다.

```yaml
- action: assert_visible
  selector: id=com.example:id/home
  timeout_ms: 5000
```

필드:

| Field | Required | Description |
| --- | --- | --- |
| `selector` | Conditional | `selector` 또는 `text` 중 하나가 필요합니다. |
| `text` | Conditional | 표시 텍스트로 요소를 찾습니다. |
| `timeout_ms` | No | 요소 탐색 제한 시간입니다. 기본값은 `5000`입니다. |

### `assert_enabled`

요소가 활성화되어 조작 가능한 상태인지 확인합니다.

```yaml
- action: assert_enabled
  selector: id=com.example:id/login
```

필드:

| Field | Required | Description |
| --- | --- | --- |
| `selector` | Conditional | `selector` 또는 `text` 중 하나가 필요합니다. |
| `text` | Conditional | 표시 텍스트로 요소를 찾습니다. |
| `timeout_ms` | No | 요소 탐색 제한 시간입니다. 기본값은 `5000`입니다. |

### `assert_attribute`

요소의 Appium attribute 값이 기대값과 같은지 확인합니다.

```yaml
- action: assert_attribute
  selector: id=com.example:id/login
  attribute: enabled
  value: "true"
```

필드:

| Field | Required | Description |
| --- | --- | --- |
| `selector` | Conditional | `selector` 또는 `text` 중 하나가 필요합니다. |
| `text` | Conditional | 표시 텍스트로 요소를 찾습니다. |
| `attribute` | Yes | 확인할 attribute 이름입니다. 예: `enabled`, `checked`, `selected`. |
| `value` | Yes | 기대값입니다. 실제 attribute 값을 문자열로 비교합니다. |
| `timeout_ms` | No | 요소 탐색 제한 시간입니다. 기본값은 `5000`입니다. |

### `assert_current_package`

현재 foreground package가 기대값과 같은지 확인합니다. `*`, `?` wildcard를 사용할 수 있습니다.

```yaml
- action: assert_current_package
  package: com.example.myapp
```

필드:

| Field | Required | Description |
| --- | --- | --- |
| `package` | Yes | 기대하는 foreground package입니다. |

### `assert_current_activity`

현재 activity가 기대값과 같은지 확인합니다. `*.MainActivity`처럼 wildcard를 사용할 수 있습니다.

```yaml
- action: assert_current_activity
  activity: "*.MainActivity"
```

필드:

| Field | Required | Description |
| --- | --- | --- |
| `activity` | Yes | 기대하는 foreground activity입니다. |

### `screenshot`

현재 화면을 PNG로 저장합니다. 파일은 `artifacts/<run_id>/` 아래에 생성됩니다.

```yaml
- action: screenshot
  name: after-login
```

필드:

| Field | Required | Description |
| --- | --- | --- |
| `name` | No | 스크린샷 파일명에 사용할 이름입니다. 생략하면 timestamp 기반 이름을 씁니다. |

### `collect_metrics`

현재 앱의 기술 지표를 수집합니다. Android 어댑터는 Appium event timing과 `mobile: shell`을 사용해 수집 가능한 지표를 반환합니다.

```yaml
- action: collect_metrics
```

필드:

| Field | Required | Description |
| --- | --- | --- |
| `action` | Yes | `collect_metrics` |

수집 metric:

| Metric | Description |
| --- | --- |
| `memory_mb` | `dumpsys meminfo <package>`의 `TOTAL PSS`를 MB로 변환한 값입니다. |
| `launch_time_ms` | 마지막 `launch_app` 단계의 실행 시간입니다. 설치된 앱 실행은 `am start -W`의 `TotalTime`을 우선 사용합니다. |
| `appium_new_session_ms` | Appium `newSessionRequested`부터 `newSessionStarted`까지의 세션 생성 시간입니다. |
| `appium_command_count` | Appium event timing에 기록된 명령 개수입니다. |
| `appium_command_avg_ms` | Appium 명령 처리 시간 평균입니다. |
| `appium_command_max_ms` | Appium 명령 처리 시간 최댓값입니다. |
| `cpu_percent` | `dumpsys cpuinfo`에서 현재 package와 하위 process CPU 사용률을 합산한 값입니다. |
| `logcat_error_count` | 최근 logcat 500줄 중 현재 앱 PID의 `E`/`F` priority 라인 수입니다. |

Appium 명령 지연 지표는 세션 capability의 `eventTimings`가 켜져 있을 때 수집됩니다. SLA Test Runner는 기본으로 이 capability를 켭니다. `memory_mb`, `cpu_percent`, `logcat_error_count`는 Android shell 접근이 막혀 있거나 기기 출력 형식이 다르면 생략될 수 있습니다. 수동 Appium 서버를 사용할 때는 `uiautomator2:adb_shell` insecure feature를 허용해야 합니다.

### `metric_check`

이미 수집된 metric이 범위 안에 있는지 확인합니다. 보통 `collect_metrics` 뒤에 사용합니다.

```yaml
- action: collect_metrics
- action: metric_check
  metric: memory_mb
  max: 256
```

필드:

| Field | Required | Description |
| --- | --- | --- |
| `metric` | Yes | 검사할 metric 이름입니다. 예: `memory_mb`, `launch_time_ms`, `appium_command_max_ms`, `appium_command_avg_ms`, `appium_new_session_ms`, `cpu_percent`, `logcat_error_count`. |
| `min` | Conditional | `min` 또는 `max` 중 하나 이상이 필요합니다. |
| `max` | Conditional | `min` 또는 `max` 중 하나 이상이 필요합니다. |

Metric이 수집되지 않았거나 범위를 벗어나면 step이 실패하고 metric violation으로 기록됩니다.

## Complete Examples

### APK smoke test

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

### Installed app with assertions

```yaml
name: Login Smoke
app:
  platform: android
  app_package: com.example.myapp
  app_activity: .MainActivity
  app_wait_activity: com.example.myapp.*
  app_wait_package: com.example.myapp
  no_reset: false
thresholds:
  max_duration_ms: 20000
  required_assertions: 2
scenarios:
  - name: login screen
    steps:
      - action: launch_app
      - action: assert_exists
        selector: id=com.example.myapp:id/email
      - action: assert_text
        text: Login
      - action: screenshot
        name: login-screen
```

### Metric check

```yaml
name: Runtime Metrics SLA
app:
  platform: android
  apk: test-apk/build/hspace-test-app-debug.apk
thresholds:
  max_duration_ms: 30000
  max_metric_violations: 0
  metrics:
    memory_mb:
      max: 256
    launch_time_ms:
      max: 5000
    appium_command_max_ms:
      max: 500
    appium_command_avg_ms:
      max: 200
    cpu_percent:
      max: 80
    logcat_error_count:
      max: 0
scenarios:
  - name: launch runtime metrics
    steps:
      - action: launch_app
      - action: wait
        timeout_ms: 1000
      - action: collect_metrics
      - action: metric_check
        metric: memory_mb
        max: 256
      - action: metric_check
        metric: launch_time_ms
        max: 5000
      - action: metric_check
        metric: appium_command_max_ms
        max: 500
```

## Validation Rules

YAML 저장 또는 import 시 아래 조건을 검증합니다.

- `name`이 필요합니다.
- `app` mapping이 필요합니다.
- `app.platform`은 `android`여야 합니다.
- `app.apk` 또는 `app.app_package` + `app.app_activity`가 필요합니다.
- `scenarios`는 list여야 하며 최소 1개가 필요합니다.
- 각 scenario는 `name`과 최소 1개 이상의 `steps`가 필요합니다.
- 각 step의 `action`은 지원 액션 목록 중 하나여야 합니다.
- `tap`: `selector` 또는 `text`가 필요합니다.
- `input`: `selector`와 `value`가 필요합니다.
- `assert_text`: `text`가 필요합니다.
- `assert_not_text`: `text`가 필요합니다.
- `assert_exists`, `assert_not_exists`: `selector` 또는 `text`가 필요합니다.
- `scroll_to_text`: `text`가 필요합니다.
- `assert_visible`, `assert_enabled`: `selector` 또는 `text`가 필요합니다.
- `assert_attribute`: `selector`/`text`, `attribute`, `value`가 필요합니다.
- `assert_current_package`: `package`가 필요합니다.
- `assert_current_activity`: `activity`가 필요합니다.
- `metric_check`: `metric`과 `min`/`max` 중 하나 이상이 필요합니다.

## Current Limits

- Android만 지원합니다.
- 브라우저, iOS, 원격 디바이스팜은 아직 지원하지 않습니다.
- 자유 Python 코드 실행은 지원하지 않습니다.
- `collect_metrics`의 Appium event timing 지표는 driver/server 지원에 따라 생략될 수 있고, shell 기반 지표는 Appium 서버의 `uiautomator2:adb_shell` 허용과 기기 출력 형식에 따라 생략될 수 있습니다.
- orientation 변경과 복잡한 multi-touch gesture는 아직 액션으로 제공하지 않습니다.
