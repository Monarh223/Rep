package com.smsbot;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.media.projection.MediaProjection;
import android.media.projection.MediaProjectionManager;
import android.os.Build;
import android.os.Bundle;
import android.widget.Button;
import android.widget.EditText;
import android.widget.TextView;
import android.widget.Toast;

public class MainActivity extends Activity {
    private static final int REQUEST_CODE = 123;
    private MediaProjectionManager mpManager;
    public static MediaProjection mediaProjection;
    private EditText etToken, etAdminId;
    private TextView tvStatus;
    private SharedPreferences prefs;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        mpManager = (MediaProjectionManager) getSystemService(MEDIA_PROJECTION_SERVICE);
        prefs = getSharedPreferences("smsbot", MODE_PRIVATE);

        etToken = findViewById(R.id.etToken);
        etAdminId = findViewById(R.id.etAdminId);
        tvStatus = findViewById(R.id.tvStatus);
        Button btnScreenshot = findViewById(R.id.btnScreenshot);
        Button btnSave = findViewById(R.id.btnSave);
        Button btnActivate = findViewById(R.id.btnActivate);

        // Загружаем сохранённые значения
        String savedToken = prefs.getString("bot_token", "");
        String savedAdminId = prefs.getString("admin_chat_id", "");
        etToken.setText(savedToken);
        etAdminId.setText(savedAdminId);

        // Запускаем сервис
        Intent serviceIntent = new Intent(this, SmsBotService.class);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(serviceIntent);
        } else {
            startService(serviceIntent);
        }

        btnScreenshot.setOnClickListener(v -> {
            Intent intent = mpManager.createScreenCaptureIntent();
            startActivityForResult(intent, REQUEST_CODE);
        });

        btnSave.setOnClickListener(v -> {
            String token = etToken.getText().toString().trim();
            String adminId = etAdminId.getText().toString().trim();
            if (token.isEmpty() || adminId.isEmpty()) {
                Toast.makeText(this, "Заполни оба поля", Toast.LENGTH_SHORT).show();
                return;
            }
            prefs.edit()
                    .putString("bot_token", token)
                    .putString("admin_chat_id", adminId)
                    .apply();
            Toast.makeText(this, "Сохранено", Toast.LENGTH_SHORT).show();
        });

        btnActivate.setOnClickListener(v -> {
            String token = prefs.getString("bot_token", "");
            String adminId = prefs.getString("admin_chat_id", "");
            if (token.isEmpty() || adminId.isEmpty()) {
                Toast.makeText(this, "Сначала введи токен и admin ID и нажми Сохранить", Toast.LENGTH_LONG).show();
                return;
            }
            SmsBotService.startTunnel(this, token, adminId);
            tvStatus.setText("⏳ Поднимаю туннель...");
        });
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQUEST_CODE && resultCode == RESULT_OK) {
            mediaProjection = mpManager.getMediaProjection(resultCode, data);
            Toast.makeText(this, "Скриншоты разрешены", Toast.LENGTH_SHORT).show();
        }
    }
}
