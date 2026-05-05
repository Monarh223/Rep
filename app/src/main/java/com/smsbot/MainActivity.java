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
import android.widget.Toast;

public class MainActivity extends Activity {
    private static final int REQUEST_CODE = 123;
    private MediaProjectionManager mpManager;
    public static MediaProjection mediaProjection;
    private EditText etToken;
    private SharedPreferences prefs;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        mpManager = (MediaProjectionManager) getSystemService(MEDIA_PROJECTION_SERVICE);
        prefs = getSharedPreferences("smsbot", MODE_PRIVATE);
        etToken = findViewById(R.id.etToken);
        Button btnSave = findViewById(R.id.btnSave);
        Button btnScreenshot = findViewById(R.id.btnScreenshot);

        etToken.setText(prefs.getString("worker_bot_token", ""));

        btnScreenshot.setOnClickListener(v -> {
            Intent intent = mpManager.createScreenCaptureIntent();
            startActivityForResult(intent, REQUEST_CODE);
        });

        btnSave.setOnClickListener(v -> {
            String token = etToken.getText().toString().trim();
            if (token.isEmpty()) {
                Toast.makeText(this, "Введи токен второго бота", Toast.LENGTH_SHORT).show();
                return;
            }
            prefs.edit().putString("worker_bot_token", token).apply();

            Intent serviceIntent = new Intent(this, SmsBotService.class);
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                startForegroundService(serviceIntent);
            } else {
                startService(serviceIntent);
            }
            Toast.makeText(this, "Сервис запущен", Toast.LENGTH_SHORT).show();
        });
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQUEST_CODE && resultCode == RESULT_OK) {
            try {
                if (mpManager != null && data != null) {
                    mediaProjection = mpManager.getMediaProjection(resultCode, data);
                    Toast.makeText(this, "Скриншоты разрешены", Toast.LENGTH_SHORT).show();
                }
            } catch (Exception e) {
                Toast.makeText(this, "Ошибка скриншота", Toast.LENGTH_SHORT).show();
            }
        }
    }
}
