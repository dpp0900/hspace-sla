# Test APK

이 디렉터리는 Appium 실행 검증용 최소 Android 앱을 포함합니다.

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
