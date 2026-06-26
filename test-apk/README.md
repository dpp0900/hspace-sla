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

기본 smoke 테스트 대상:

- 입력창: `accessibility_id=message_input`
- Echo 버튼: `accessibility_id=echo_button`
- Success 버튼: `accessibility_id=success_button`
- 상태 텍스트: `accessibility_id=status_text`

고급 SLA 플로우 테스트 대상:

- 로그인: `accessibility_id=email_input`, `accessibility_id=password_input`, `accessibility_id=login_button`
- 대시보드: `accessibility_id=dashboard_panel`, `accessibility_id=dashboard_summary_text`
- 검색/필터: `accessibility_id=search_input`, `accessibility_id=search_button`, `accessibility_id=filter_critical_button`
- 장애 카드: `accessibility_id=checkout_card`, `accessibility_id=open_checkout_detail`, `accessibility_id=dispatch_button`
- 상세/조치: `accessibility_id=checkout_detail_panel`, `accessibility_id=ack_button`
- 설정/DR: `accessibility_id=alerts_toggle`, `accessibility_id=run_drill_button`

기본 액션 검증은 `suites/full_feature_android.yaml`, 실제 업무형 SLA 플로우 검증은
`suites/advanced_field_ops_android.yaml`을 실행합니다.
