package com.tammi.lab.audio;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.widget.TextView;

public class MainActivity extends Activity {
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getExternalFilesDir(null);
        TextView text=new TextView(this);
        text.setText("Tammi Audio Lab\nThu mic vật lý qua lệnh ADB, tối đa 30 giây/lượt.\nKhông thu nội dung cuộc gọi qua quyền hệ thống.");
        text.setPadding(24,40,24,24);setContentView(text);
        Intent incoming=getIntent();String action=incoming.getStringExtra("action");
        if (action!=null) {
            Intent service=new Intent(this,AudioService.class).putExtras(incoming);
            startForegroundService(service);
        }
    }
}
