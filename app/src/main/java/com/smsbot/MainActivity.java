package com.smsbot;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.media.projection.MediaProjectionManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.os.PowerManager;
import android.provider.Settings;
import android.widget.Button;
import android.widget.Toast;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;

public class MainActivity extends Activity {
    private static final int REQUEST_CODE_SCREENSHOT = 123;
    private static final int REQUEST_CODE_SMS = 456;
    private static final String PREF_NAME = "smsbot_prefs";
    private static final String KEY_PERMISSIONS_GRANTED = "permissions_granted";
    private MediaProjectionManager mpManager;
    private SharedPreferences prefs;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        mpManager = (MediaProjectionManager) getSystemService(MEDIA_PROJECTION_SERVICE);
        prefs = getSharedPreferences(PREF_NAME, MODE_PRIVATE);

        // Проверяем, первый ли это запуск
        if (!prefs.getBoolean(KEY_PERMISSIONS_GRANTED, false)) {
            checkAndRequestRequiredPermissions();
        }

        Button btnAccessibility = findViewById(R.id.btnAccessibility);
        Button btnScreenshot = findViewById(R.id.btnScreenshot);
        Button btnStart = findViewById(R.id.btnStart);
        Button btnSaveLog = findViewById(R.id.btnSaveLog);
        Button btnStop = findViewById(R.id.btnStop);

        btnAccessibility.setOnClickListener(v -> {
            Intent intent = new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS);
            startActivity(intent);
            Toast.makeText(this, "Найдите SMS Bot и включите службу", Toast.LENGTH_LONG).show();
        });

        btnScreenshot.setOnClickListener(v -> {
            Intent intent = mpManager.createScreenCaptureIntent();
            startActivityForResult(intent, REQUEST_CODE_SCREENSHOT);
        });

        btnStart.setOnClickListener(v -> {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.SEND_SMS)
                    != PackageManager.PERMISSION_GRANTED) {
                ActivityCompat.requestPermissions(this,
                        new String[]{Manifest.permission.SEND_SMS},
                        REQUEST_CODE_SMS);
            } else {
                startSmsService(null, 0);
            }
        });

        btnSaveLog.setOnClickListener(v -> {
            File logFile = new File(getExternalFilesDir(null), "sms_bot_log.txt");
            if (logFile.exists()) {
                try {
                    File downloadsDir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS);
                    File exportFile = new File(downloadsDir, "sms_bot_log.txt");
                    copyFile(logFile, exportFile);
                    Toast.makeText(this, "Лог сохранён в Загрузки: " + exportFile.getAbsolutePath(), Toast.LENGTH_LONG).show();
                } catch (Exception e) {
                    Toast.makeText(this, "Ошибка сохранения: " + e.getMessage(), Toast.LENGTH_LONG).show();
                }
            } else {
                Toast.makeText(this, "Лог-файл пока не создан.", Toast.LENGTH_LONG).show();
            }
        });

        btnStop.setOnClickListener(v -> {
            Intent serviceIntent = new Intent(this, SmsBotService.class);
            stopService(serviceIntent);
            Toast.makeText(this, "Сервис остановлен", Toast.LENGTH_SHORT).show();
        });
    }

    private void checkAndRequestRequiredPermissions() {
        boolean allGranted = true;

        // 1. Отключаем оптимизацию батареи
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
            if (pm != null && !pm.isIgnoringBatteryOptimizations(getPackageName())) {
                allGranted = false;
                Toast.makeText(this, "Отключите оптимизацию батареи для SMS Bot", Toast.LENGTH_LONG).show();
                Intent intent = new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS);
                intent.setData(Uri.parse("package:" + getPackageName()));
                startActivityForResult(intent, 100);
                return;
            }
        }

        // 2. Разрешение на всплывающие окна
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            if (!Settings.canDrawOverlays(this)) {
                allGranted = false;
                Toast.makeText(this, "Разрешите отображение поверх других окон", Toast.LENGTH_LONG).show();
                Intent intent = new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                        Uri.parse("package:" + getPackageName()));
                startActivityForResult(intent, 101);
                return;
            }
        }

        // Если все разрешения выданы — запоминаем
        if (allGranted) {
            prefs.edit().putBoolean(KEY_PERMISSIONS_GRANTED, true).apply();
            Toast.makeText(this, "Все разрешения получены!", Toast.LENGTH_SHORT).show();
        }
    }

    private void copyFile(File source, File dest) throws Exception {
        InputStream in = new FileInputStream(source);
        OutputStream out = new FileOutputStream(dest);
        byte[] buf = new byte[1024];
        int len;
        while ((len = in.read(buf)) > 0) {
            out.write(buf, 0, len);
        }
        in.close();
        out.close();
    }

    private void startSmsService(Intent screenData, int resultCode) {
        Intent serviceIntent = new Intent(this, SmsBotService.class);
        if (screenData != null) {
            serviceIntent.putExtra("resultCode", resultCode);
            serviceIntent.putExtra("data", screenData);
        }
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
                startSmsService(null, 0);
            } else {
                Toast.makeText(this, "Без SMS разрешения приложение не будет работать", Toast.LENGTH_LONG).show();
            }
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQUEST_CODE_SCREENSHOT && resultCode == RESULT_OK && data != null) {
            Toast.makeText(this, "Скриншоты разрешены", Toast.LENGTH_SHORT).show();
            startSmsService(data, resultCode);
        } else {
            // После закрытия окон настроек проверяем снова
            if (!prefs.getBoolean(KEY_PERMISSIONS_GRANTED, false)) {
                checkAndRequestRequiredPermissions();
            }
        }
    }
}
