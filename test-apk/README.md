# Test APK

이 디렉터리는 Appium 실행과 SLA 액션 검증용 Android 앱을 포함합니다.

빌드:

```bash
cd /Users/dpp/Desktop/HSPACE/SLA
chmod +x test-apk/build_test_apk.sh
./test-apk/build_test_apk.sh
```

생성물:

- `test-apk/build/hspace-test-app-debug.apk`

패키지/액티비티:

- Package: `com.hspace.testapp`
- Activity: `com.hspace.testapp.MainActivity`

테스트 대상:

- 입력창: `accessibility_id=message_input`
- Echo 버튼: `accessibility_id=echo_button`
- Success 버튼: `accessibility_id=success_button`
- 상태 텍스트: `accessibility_id=status_text`

전체 SLA 액션 검증은 `suites/full_feature_android.yaml`을 실행합니다.
