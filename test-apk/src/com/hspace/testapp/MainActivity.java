package com.hspace.testapp;

import android.app.Activity;
import android.graphics.Color;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

public class MainActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        ScrollView scroll = new ScrollView(this);
        scroll.setBackgroundColor(Color.parseColor("#0F172A"));

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER);
        root.setPadding(80, 120, 80, 120);
        root.setBackgroundColor(Color.parseColor("#0F172A"));

        TextView title = new TextView(this);
        title.setText("HSPACE Appium Test");
        title.setTextColor(Color.WHITE);
        title.setTextSize(28f);
        title.setGravity(Gravity.CENTER);

        TextView body = new TextView(this);
        body.setText("Interactive APK for SLA suite validation.");
        body.setTextColor(Color.parseColor("#CBD5E1"));
        body.setTextSize(16f);
        body.setGravity(Gravity.CENTER);
        body.setPadding(0, 32, 0, 0);

        TextView status = new TextView(this);
        status.setText("Status: Ready");
        status.setContentDescription("status_text");
        status.setTextColor(Color.WHITE);
        status.setTextSize(20f);
        status.setGravity(Gravity.CENTER);
        status.setPadding(0, 44, 0, 0);

        EditText input = new EditText(this);
        input.setHint("Type SLA message");
        input.setContentDescription("message_input");
        input.setSingleLine(true);
        input.setInputType(InputType.TYPE_CLASS_TEXT);
        input.setTextColor(Color.WHITE);
        input.setHintTextColor(Color.parseColor("#94A3B8"));
        input.setTextSize(18f);
        input.setPadding(24, 16, 24, 16);
        input.setLayoutParams(fullWidthLayoutParams(36));

        Button echoButton = new Button(this);
        echoButton.setText("Echo Input");
        echoButton.setContentDescription("echo_button");
        echoButton.setLayoutParams(fullWidthLayoutParams(20));
        echoButton.setOnClickListener(view -> status.setText("Echo: " + input.getText().toString()));

        Button successButton = new Button(this);
        successButton.setText("Mark Success");
        successButton.setContentDescription("success_button");
        successButton.setLayoutParams(fullWidthLayoutParams(16));
        successButton.setOnClickListener(view -> status.setText("Action Complete"));

        TextView footer = new TextView(this);
        footer.setText("Package: " + getPackageName());
        footer.setTextColor(Color.parseColor("#38BDF8"));
        footer.setTextSize(14f);
        footer.setGravity(Gravity.CENTER);
        footer.setPadding(0, 32, 0, 0);

        root.addView(title);
        root.addView(body);
        root.addView(status);
        root.addView(input);
        root.addView(echoButton);
        root.addView(successButton);
        root.addView(footer);

        scroll.addView(root);
        setContentView(scroll);
    }

    private LinearLayout.LayoutParams fullWidthLayoutParams(int topMargin) {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT);
        params.setMargins(0, topMargin, 0, 0);
        return params;
    }
}
