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
        if (mpManager == null) {
            Toast.makeText(this, "Ваше устройство не поддерживает запись экрана", Toast.LENGTH_LONG).show();
            finish();
            return;
        }

        prefs = getSharedPreferences("smsbot", MODE_PRIVATE);
        etToken = findViewById(R.id.etToken);
        Button btnSave = findViewById(R.id.btnSave);
        Button btnScreenshot = findViewById(R.id.btnScreenshot);

        etToken.setText(prefs.getString("bot_token", ""));

        btnScreenshot.setOnClickListener(v -> {
            try {
                Intent intent = mpManager.createScreenCaptureIntent();
                startActivityForResult(intent, REQUEST_CODE);
            } catch (Exception e) {
                Toast.makeText(this, "Ошибка запуска захвата экрана", Toast.LENGTH_SHORT).show();
                e.printStackTrace();
            }
        });

        btnSave.setOnClickListener(v -> {
            String token = etToken.getText().toString().trim();
            if (token.isEmpty()) {
                Toast.makeText(this, "Введи токен", Toast.LENGTH_SHORT).show();
                return;
            }
            prefs.edit().putString("bot_token", token).apply();

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
        if (requestCode == REQUEST_CODE) {
            if (resultCode == RESULT_OK && data != null) {
                try {
                    mediaProjection = mpManager.getMediaProjection(resultCode, data);
                    if (mediaProjection != null) {
                        Toast.makeText(this, "Скриншоты разрешены", Toast.LENGTH_SHORT).show();
                    } else {
                        Toast.makeText(this, "Не удалось получить MediaProjection", Toast.LENGTH_SHORT).show();
                    }
                } catch (Exception e) {
                    Toast.makeText(this, "Ошибка получения MediaProjection", Toast.LENGTH_SHORT).show();
                    e.printStackTrace();
                }
            } else {
                Toast.makeText(this, "Разрешение не получено", Toast.LENGTH_SHORT).show();
            }
        }
    }
}
