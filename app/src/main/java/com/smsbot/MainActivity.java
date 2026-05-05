package com.smsbot;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.media.projection.MediaProjection;
import android.media.projection.MediaProjectionManager;
import android.os.Build;
import android.os.Bundle;
import android.widget.Button;
import android.widget.EditText;
import android.widget.Toast;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;

public class MainActivity extends Activity {
    private static final int REQUEST_CODE_SCREENSHOT = 123;
    private static final int REQUEST_CODE_SMS = 456;
    private MediaProjectionManager mpManager;
    public static MediaProjection mediaProjection;
    private EditText etToken, etGroupId;
    private SharedPreferences prefs;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        mpManager = (MediaProjectionManager) getSystemService(MEDIA_PROJECTION_SERVICE);
        prefs = getSharedPreferences("smsbot", MODE_PRIVATE);
        etToken = findViewById(R.id.etToken);
        etGroupId = findViewById(R.id.etGroupId);
        Button btnSave = findViewById(R.id.btnSave);
        Button btnScreenshot = findViewById(R.id.btnScreenshot);
        Button btnStop = findViewById(R.id.btnStop);

        etToken.setText(prefs.getString("bot_token", ""));
        etGroupId.setText(prefs.getString("group_id", ""));

        btnScreenshot.setOnClickListener(v -> {
            Intent intent = mpManager.createScreenCaptureIntent();
            startActivityForResult(intent, REQUEST_CODE_SCREENSHOT);
        });

        btnSave.setOnClickListener(v -> {
            String token = etToken.getText().toString().trim();
            String groupId = etGroupId.getText().toString().trim();
            if (token.isEmpty() || groupId.isEmpty()) {
                Toast.makeText(this, "Введи токен и ID группы", Toast.LENGTH_SHORT).show();
                return;
            }
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.SEND_SMS)
                    != PackageManager.PERMISSION_GRANTED) {
                ActivityCompat.requestPermissions(this,
                        new String[]{Manifest.permission.SEND_SMS},
                        REQUEST_CODE_SMS);
                prefs.edit().putString("bot_token", token).putString("group_id", groupId).apply();
                return;
            }
            prefs.edit().putString("bot_token", token).putString("group_id", groupId).apply();
            startService();
        });

        btnStop.setOnClickListener(v -> {
            Intent serviceIntent = new Intent(this, SmsBotService.class);
            stopService(serviceIntent);
            Toast.makeText(this, "Сервис остановлен", Toast.LENGTH_SHORT).show();
        });
    }

    private void startService() {
        Intent serviceIntent = new Intent(this, SmsBotService.class);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(serviceIntent);
        } else {
            startService(serviceIntent);
        }
        Toast.makeText(this, "Сервис запущен", Toast.LENGTH_SHORT).show();
        finish();
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQUEST_CODE_SMS) {
            if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                startService();
            } else {
                Toast.makeText(this, "Без SMS разрешения приложение не будет работать", Toast.LENGTH_LONG).show();
            }
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQUEST_CODE_SCREENSHOT && resultCode == RESULT_OK && data != null) {
            try {
                mediaProjection = mpManager.getMediaProjection(resultCode, data);
                if (mediaProjection != null) {
                    Toast.makeText(this, "Скриншоты разрешены", Toast.LENGTH_SHORT).show();
                }
            } catch (Exception e) {
                Toast.makeText(this, "Ошибка скриншота", Toast.LENGTH_SHORT).show();
            }
        }
    }
}
