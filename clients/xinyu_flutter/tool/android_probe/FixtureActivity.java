package com.xinyu.smoke;

import android.app.Activity;
import android.os.Bundle;
import android.widget.*;
import android.text.InputType;

/** Synthetic controls for accessibility verification; contains no user data. */
public final class FixtureActivity extends Activity {
    @Override public void onCreate(Bundle bundle) {
        super.onCreate(bundle);
        LinearLayout column = new LinearLayout(this);
        column.setOrientation(LinearLayout.VERTICAL);
        column.setPadding(24, 64, 24, 24);
        if (getIntent().getBooleanExtra("screen_chat", false)) {
            TextView title = new TextView(this);
            title.setText("自动化测试夹具 · 合成聊天"); title.setTextSize(20);
            column.addView(title);
            TextView mine = new TextView(this);
            mine.setText("我：今天有点累，想找你说说。"); mine.setTextSize(18); mine.setPadding(0, 48, 0, 24);
            column.addView(mine);
            TextView reply = new TextView(this);
            reply.setText("朋友：不好意思今晚不方便，下次吧。SCREEN_FIXTURE_A"); reply.setTextSize(18);
            column.addView(reply);
            Button change = new Button(this);
            change.setText("切换合成页面");
            change.setOnClickListener(view -> reply.setText("朋友：我终于通过考试了！SCREEN_FIXTURE_B"));
            column.addView(change);
            TextView hidden = new TextView(this); hidden.setText("HIDDEN_SCREEN_CANARY"); hidden.setVisibility(android.view.View.GONE);
            column.addView(hidden);
            if (getIntent().getBooleanExtra("password", false)) {
                EditText secret = new EditText(this);
                secret.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
                secret.setText("SYNTHETIC_SCREEN_SECRET"); column.addView(secret);
            }
            setContentView(column);
            return;
        }
        Button button = new Button(this);
        button.setText("Tap target");
        button.setOnClickListener(view -> button.setText("Tapped successfully"));
        column.addView(button);
        Button hold = new Button(this);
        hold.setText("Long press target");
        hold.setOnLongClickListener(view -> {
            hold.setText("Long press verified");
            return true;
        });
        column.addView(hold);
        EditText input = new EditText(this);
        input.setContentDescription("Input target");
        column.addView(input);
        EditText password = new EditText(this);
        password.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        password.setText("synthetic-secret-0227");
        column.addView(password);
        ScrollView scroll = new ScrollView(this);
        LinearLayout rows = new LinearLayout(this);
        rows.setOrientation(LinearLayout.VERTICAL);
        for (int i = 0; i < 50; i++) {
            TextView row = new TextView(this);
            row.setText("Synthetic row " + i);
            row.setPadding(8, 20, 8, 20);
            rows.addView(row);
        }
        scroll.addView(rows);
        column.addView(scroll);
        setContentView(column);
    }
}
