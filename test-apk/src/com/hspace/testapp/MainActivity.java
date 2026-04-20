package com.hspace.testapp;

import android.app.Activity;
import android.graphics.Color;
import android.os.Bundle;
import android.view.Gravity;
import android.widget.LinearLayout;
import android.widget.TextView;

public class MainActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

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
        body.setText(
                "This APK was built locally without Gradle and launched through Appium on the Android emulator.");
        body.setTextColor(Color.parseColor("#CBD5E1"));
        body.setTextSize(16f);
        body.setGravity(Gravity.CENTER);
        body.setPadding(0, 32, 0, 0);

        TextView footer = new TextView(this);
        footer.setText("Package: " + getPackageName());
        footer.setTextColor(Color.parseColor("#38BDF8"));
        footer.setTextSize(14f);
        footer.setGravity(Gravity.CENTER);
        footer.setPadding(0, 32, 0, 0);

        root.addView(title);
        root.addView(body);
        root.addView(footer);

        setContentView(root);
    }
}
