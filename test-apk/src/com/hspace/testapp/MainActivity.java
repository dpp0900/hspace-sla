package com.hspace.testapp;

import android.app.Activity;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Switch;
import android.widget.TextView;

public class MainActivity extends Activity {
    private static final int COLOR_PAGE = Color.parseColor("#F8FAFC");
    private static final int COLOR_PANEL = Color.WHITE;
    private static final int COLOR_TEXT = Color.parseColor("#111827");
    private static final int COLOR_MUTED = Color.parseColor("#64748B");
    private static final int COLOR_PRIMARY = Color.parseColor("#0F766E");
    private static final int COLOR_WARNING = Color.parseColor("#B45309");
    private static final int COLOR_DANGER = Color.parseColor("#B91C1C");
    private static final int COLOR_SUCCESS = Color.parseColor("#047857");

    private ScrollView scroll;
    private TextView statusText;
    private TextView loginErrorBanner;
    private TextView searchResultText;
    private TextView detailBodyText;
    private TextView alertStatusText;
    private LinearLayout dashboardPanel;
    private LinearLayout checkoutDetailPanel;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        scroll = new ScrollView(this);
        scroll.setFillViewport(false);
        scroll.setBackgroundColor(COLOR_PAGE);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER_HORIZONTAL);
        root.setPadding(dp(20), dp(28), dp(20), dp(40));
        root.setBackgroundColor(COLOR_PAGE);

        root.addView(buildHeaderPanel());
        root.addView(buildDiagnosticPanel());
        root.addView(buildLoginPanel());

        dashboardPanel = buildDashboardPanel();
        dashboardPanel.setVisibility(View.GONE);
        root.addView(dashboardPanel);

        root.addView(buildFooter());

        scroll.addView(root);
        setContentView(scroll);
    }

    private LinearLayout buildHeaderPanel() {
        LinearLayout panel = panel();

        TextView eyebrow = text("Controlled SLA Demo APK", 13f, COLOR_PRIMARY, Typeface.BOLD);
        eyebrow.setGravity(Gravity.CENTER);

        TextView title = text("HSPACE Appium Test", 28f, COLOR_TEXT, Typeface.BOLD);
        title.setGravity(Gravity.CENTER);
        title.setContentDescription("app_title");

        TextView body = text(
                "A reproducible Android app for login, search, detail, settings, and runtime metric SLA validation.",
                15f,
                COLOR_MUTED,
                Typeface.NORMAL);
        body.setGravity(Gravity.CENTER);
        body.setPadding(0, dp(8), 0, 0);

        statusText = text("Status: Ready", 20f, COLOR_TEXT, Typeface.BOLD);
        statusText.setContentDescription("status_text");
        statusText.setGravity(Gravity.CENTER);
        statusText.setPadding(0, dp(20), 0, 0);

        panel.addView(eyebrow);
        panel.addView(title);
        panel.addView(body);
        panel.addView(statusText);
        return panel;
    }

    private LinearLayout buildDiagnosticPanel() {
        LinearLayout panel = panel();

        TextView title = text("Diagnostic Console", 20f, COLOR_TEXT, Typeface.BOLD);
        TextView helper = text(
                "Legacy controls remain available so the original smoke suite still works.",
                14f,
                COLOR_MUTED,
                Typeface.NORMAL);
        helper.setPadding(0, dp(6), 0, dp(4));

        EditText input = input("Type SLA message", "message_input");

        Button echoButton = button("Echo Input", "echo_button");
        echoButton.setOnClickListener(view -> statusText.setText("Echo: " + input.getText().toString()));

        Button successButton = button("Mark Success", "success_button");
        successButton.setOnClickListener(view -> statusText.setText("Action Complete"));

        panel.addView(title);
        panel.addView(helper);
        panel.addView(input);
        panel.addView(echoButton);
        panel.addView(successButton);
        return panel;
    }

    private LinearLayout buildLoginPanel() {
        LinearLayout panel = panel();

        TextView title = text("Operator Login", 20f, COLOR_TEXT, Typeface.BOLD);
        TextView helper = text(
                "Use any non-empty email and password to enter the SLA dashboard.",
                14f,
                COLOR_MUTED,
                Typeface.NORMAL);
        helper.setPadding(0, dp(6), 0, dp(4));

        loginErrorBanner = banner("Login Error: credentials required", COLOR_DANGER);
        loginErrorBanner.setContentDescription("login_error_banner");
        loginErrorBanner.setVisibility(View.GONE);

        EditText emailInput = input("operator@hspace.local", "email_input");
        emailInput.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_EMAIL_ADDRESS);

        EditText passwordInput = input("password", "password_input");
        passwordInput.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);

        Button loginButton = button("Sign In", "login_button");
        loginButton.setOnClickListener(view -> {
            boolean hasCredentials = emailInput.getText().toString().trim().length() > 0
                    && passwordInput.getText().toString().trim().length() > 0;
            if (!hasCredentials) {
                loginErrorBanner.setVisibility(View.VISIBLE);
                dashboardPanel.setVisibility(View.GONE);
                checkoutDetailPanel.setVisibility(View.GONE);
                statusText.setText("Login Error");
                return;
            }
            loginErrorBanner.setVisibility(View.GONE);
            dashboardPanel.setVisibility(View.VISIBLE);
            checkoutDetailPanel.setVisibility(View.GONE);
            searchResultText.setText("Result: Ready for search");
            statusText.setText("Login Complete - Dashboard Ready");
            scrollTo(dashboardPanel);
        });

        panel.addView(title);
        panel.addView(helper);
        panel.addView(loginErrorBanner);
        panel.addView(emailInput);
        panel.addView(passwordInput);
        panel.addView(loginButton);
        return panel;
    }

    private LinearLayout buildDashboardPanel() {
        LinearLayout panel = panel();
        panel.setContentDescription("dashboard_panel");

        TextView title = text("Field Ops Dashboard", 22f, COLOR_TEXT, Typeface.BOLD);
        title.setContentDescription("dashboard_title");

        TextView summary = text(
                "Critical: 2   Healthy: 8   SLA Candidate: checkout latency p95 under 250 ms",
                15f,
                COLOR_MUTED,
                Typeface.BOLD);
        summary.setContentDescription("dashboard_summary_text");
        summary.setPadding(0, dp(8), 0, dp(12));

        EditText searchInput = input("Search service or incident", "search_input");
        Button searchButton = button("Search", "search_button");
        searchButton.setOnClickListener(view -> {
            String query = searchInput.getText().toString().trim().toLowerCase();
            if (query.contains("checkout") || query.contains("payment")) {
                searchResultText.setText("Result: Checkout API - Degraded");
            } else if (query.length() == 0) {
                searchResultText.setText("Result: Empty search");
            } else {
                searchResultText.setText("Result: No matching service");
            }
        });

        Button filterButton = button("Critical Only", "filter_critical_button");
        filterButton.setOnClickListener(view -> {
            searchResultText.setText("Filter: Critical Only");
            statusText.setText("Critical services filtered");
        });

        searchResultText = text("Result: Ready for search", 15f, COLOR_TEXT, Typeface.BOLD);
        searchResultText.setContentDescription("search_result_text");
        searchResultText.setPadding(0, dp(12), 0, dp(10));

        panel.addView(title);
        panel.addView(summary);
        panel.addView(searchInput);
        panel.addView(searchButton);
        panel.addView(filterButton);
        panel.addView(searchResultText);
        panel.addView(buildCheckoutCard());
        panel.addView(buildInventoryCard());

        checkoutDetailPanel = buildCheckoutDetailPanel();
        checkoutDetailPanel.setVisibility(View.GONE);
        panel.addView(checkoutDetailPanel);

        panel.addView(buildSettingsPanel());
        panel.addView(buildDrillPanel());
        return panel;
    }

    private LinearLayout buildCheckoutCard() {
        LinearLayout card = card();
        card.setContentDescription("checkout_card");

        TextView title = text("P1 Checkout API", 18f, COLOR_DANGER, Typeface.BOLD);
        TextView body = text(
                "Latency p95: 238 ms\nError rate: 0.8%\nOwner: Payments\nRecommended SLA: p95 under 250 ms, errors under 1%",
                14f,
                COLOR_TEXT,
                Typeface.NORMAL);
        body.setPadding(0, dp(8), 0, 0);

        Button detailButton = button("Open Checkout Detail", "open_checkout_detail");
        detailButton.setOnClickListener(view -> {
            checkoutDetailPanel.setVisibility(View.VISIBLE);
            statusText.setText("Detail Open - Checkout API");
            scrollTo(checkoutDetailPanel);
        });

        Button dispatchButton = button("Schedule Dispatch", "dispatch_button");
        dispatchButton.setOnClickListener(view -> statusText.setText("Dispatch Scheduled - Payments"));

        card.addView(title);
        card.addView(body);
        card.addView(detailButton);
        card.addView(dispatchButton);
        return card;
    }

    private LinearLayout buildInventoryCard() {
        LinearLayout card = card();
        card.setContentDescription("inventory_card");

        TextView title = text("P2 Inventory Sync", 18f, COLOR_WARNING, Typeface.BOLD);
        TextView body = text(
                "Backlog: 17 jobs\nOldest retry: 4 min\nRecommended SLA: sync queue under 25 jobs",
                14f,
                COLOR_TEXT,
                Typeface.NORMAL);
        body.setPadding(0, dp(8), 0, 0);

        card.addView(title);
        card.addView(body);
        return card;
    }

    private LinearLayout buildCheckoutDetailPanel() {
        LinearLayout panel = card();
        panel.setContentDescription("checkout_detail_panel");

        TextView title = text("Checkout Detail", 20f, COLOR_TEXT, Typeface.BOLD);
        title.setContentDescription("checkout_detail_title");

        detailBodyText = text(
                "Risk: Degraded\nLatency p95: 238 ms\nError budget: 84% remaining\nRunbook: Payment fallback armed",
                14f,
                COLOR_TEXT,
                Typeface.NORMAL);
        detailBodyText.setContentDescription("checkout_detail_body");
        detailBodyText.setPadding(0, dp(10), 0, 0);

        Button ackButton = button("Acknowledge Incident", "ack_button");
        ackButton.setOnClickListener(view -> {
            detailBodyText.setText(
                    "Risk: Degraded\nLatency p95: 238 ms\nRunbook: Payment fallback armed\nOwner: Payments");
            ackButton.setText("Incident Acknowledged");
            statusText.setText("Acknowledged: Checkout API");
        });

        panel.addView(title);
        panel.addView(detailBodyText);
        panel.addView(ackButton);
        return panel;
    }

    private LinearLayout buildSettingsPanel() {
        LinearLayout panel = card();
        panel.setContentDescription("settings_panel");

        TextView title = text("Notification Settings", 18f, COLOR_TEXT, Typeface.BOLD);

        Switch alertsToggle = new Switch(this);
        alertsToggle.setText("Push Alerts");
        alertsToggle.setTextSize(16f);
        alertsToggle.setTextColor(COLOR_TEXT);
        alertsToggle.setContentDescription("alerts_toggle");
        alertsToggle.setChecked(true);
        alertsToggle.setPadding(0, dp(10), 0, 0);
        alertsToggle.setLayoutParams(fullWidthLayoutParams(dp(8)));

        alertStatusText = text("Alerts: On", 14f, COLOR_SUCCESS, Typeface.BOLD);
        alertStatusText.setContentDescription("alert_status_text");
        alertStatusText.setPadding(0, dp(8), 0, 0);

        alertsToggle.setOnCheckedChangeListener((buttonView, isChecked) -> {
            alertStatusText.setText(isChecked ? "Alerts: On" : "Alerts: Off");
            statusText.setText(isChecked ? "Alerts Enabled" : "Alerts Muted");
        });

        panel.addView(title);
        panel.addView(alertsToggle);
        panel.addView(alertStatusText);
        return panel;
    }

    private LinearLayout buildDrillPanel() {
        LinearLayout panel = card();
        panel.setContentDescription("drill_panel");

        TextView title = text("Disaster Recovery Drill", 18f, COLOR_TEXT, Typeface.BOLD);
        title.setContentDescription("dr_drill_label");
        TextView body = text(
                "Last run: 2026-06-26\nRecovery target: under 10 min\nEvidence: screenshot and command timing metrics",
                14f,
                COLOR_TEXT,
                Typeface.NORMAL);
        body.setPadding(0, dp(8), 0, 0);

        Button drillButton = button("Complete Drill", "run_drill_button");
        drillButton.setOnClickListener(view -> {
            drillButton.setText("Drill Complete");
            statusText.setText("Drill Complete");
        });

        panel.addView(title);
        panel.addView(body);
        panel.addView(drillButton);
        return panel;
    }

    private TextView buildFooter() {
        TextView footer = text("Package: " + getPackageName(), 13f, COLOR_PRIMARY, Typeface.BOLD);
        footer.setGravity(Gravity.CENTER);
        footer.setPadding(0, dp(18), 0, 0);
        footer.setContentDescription("package_footer");
        return footer;
    }

    private LinearLayout panel() {
        LinearLayout panel = new LinearLayout(this);
        panel.setOrientation(LinearLayout.VERTICAL);
        panel.setPadding(dp(18), dp(18), dp(18), dp(18));
        panel.setBackground(rounded(COLOR_PANEL, dp(14), Color.parseColor("#E2E8F0")));
        panel.setLayoutParams(fullWidthLayoutParams(dp(14)));
        return panel;
    }

    private LinearLayout card() {
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setPadding(dp(14), dp(14), dp(14), dp(14));
        card.setBackground(rounded(Color.parseColor("#F8FAFC"), dp(10), Color.parseColor("#CBD5E1")));
        card.setLayoutParams(fullWidthLayoutParams(dp(12)));
        return card;
    }

    private TextView text(String value, float size, int color, int style) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextColor(color);
        view.setTextSize(size);
        view.setTypeface(Typeface.DEFAULT, style);
        view.setLineSpacing(dp(2), 1.0f);
        view.setLayoutParams(fullWidthLayoutParams(0));
        return view;
    }

    private TextView banner(String value, int color) {
        TextView view = text(value, 14f, Color.WHITE, Typeface.BOLD);
        view.setPadding(dp(12), dp(10), dp(12), dp(10));
        view.setBackground(rounded(color, dp(8), color));
        view.setLayoutParams(fullWidthLayoutParams(dp(10)));
        return view;
    }

    private EditText input(String hint, String contentDescription) {
        EditText input = new EditText(this);
        input.setHint(hint);
        input.setContentDescription(contentDescription);
        input.setSingleLine(true);
        input.setInputType(InputType.TYPE_CLASS_TEXT);
        input.setTextColor(COLOR_TEXT);
        input.setHintTextColor(Color.parseColor("#94A3B8"));
        input.setTextSize(16f);
        input.setPadding(dp(12), dp(10), dp(12), dp(10));
        input.setBackground(rounded(Color.WHITE, dp(8), Color.parseColor("#CBD5E1")));
        input.setLayoutParams(fullWidthLayoutParams(dp(12)));
        return input;
    }

    private Button button(String label, String contentDescription) {
        Button button = new Button(this);
        button.setText(label);
        button.setContentDescription(contentDescription);
        button.setAllCaps(false);
        button.setTextSize(15f);
        button.setMinHeight(dp(44));
        button.setLayoutParams(fullWidthLayoutParams(dp(10)));
        return button;
    }

    private GradientDrawable rounded(int color, int radius, int strokeColor) {
        GradientDrawable drawable = new GradientDrawable();
        drawable.setColor(color);
        drawable.setCornerRadius(radius);
        drawable.setStroke(dp(1), strokeColor);
        return drawable;
    }

    private LinearLayout.LayoutParams fullWidthLayoutParams(int topMargin) {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT);
        params.setMargins(0, topMargin, 0, 0);
        return params;
    }

    private void scrollTo(View target) {
        scroll.post(() -> scroll.smoothScrollTo(0, target.getTop()));
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }
}
