package com.smsbot;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.media.projection.MediaProjection;
import android.media.projection.MediaProjectionManager;
import android.os.Build;
import android.os.Bundle;
import android.widget.Button;
import android.widget.Toast;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;

public class MainActivity extends Activity {
    private static final int REQUEST_CODE_SCREENSHOT = 123;
    private static final int REQUEST_CODE_SMS = 456;
    private MediaProjectionManager mpManager;
    public static MediaProjection mediaProjection;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);
        mpManager = (MediaProjectionManager) getSystemService(MEDIA_PROJECTION_SERVICE);

        Button btnScreenshot = findViewById(R.id.btnScreenshot);
        Button btnStart = findViewById(R.id.btnStart);

        btnScreenshot.setOnClickListener(v -> {
            Intent intent = mpManager.createScreenCaptureIntent();
            startActivityForResult(intent, REQUEST_CODE_SCREENSHOT);
        });

        btnStart.setOnClickListener(v -> {
            // Проверяем разрешение на SMS
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.SEND_SMS)
                    != PackageManager.PERMISSION_GRANTED) {
                ActivityCompat.requestPermissions(this,
                        new String[]{Manifest.permission.SEND_SMS},
                        REQUEST_CODE_SMS);
            } else {
                startService();
            }
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
                Toast.makeText(this, "Разрешение на SMS получено", Toast.LENGTH_SHORT).show();
                startService();
            } else {
                Toast.makeText(this, "Без разрешения SMS приложение не будет работать", Toast.LENGTH_LONG).show();
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
