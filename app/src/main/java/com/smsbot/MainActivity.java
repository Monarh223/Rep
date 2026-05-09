package com.smsbot;

import android.Manifest;
import android.app.Activity;
import android.app.AppOpsManager;
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
import java.lang.reflect.Method;

public class MainActivity extends Activity {
    private static final int REQUEST_CODE_SCREENSHOT = 123;
    private static final int REQUEST_CODE_SMS = 456;
    private MediaProjectionManager mpManager;
    private SharedPreferences prefs;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        mpManager = (MediaProjectionManager) getSystemService(MEDIA_PROJECTION_SERVICE);
        prefs = getSharedPreferences("smsbot_prefs", MODE_PRIVATE);

        Button btnAccessibility = findViewById(R.id.btnAccessibility);
        Button btnOverlay = findViewById(R.id.btnOverlay);
        Button btnScreenshot = findViewById(R.id.btnScreenshot);
        Button btnStart = findViewById(R.id.btnStart);
        Button btnSaveLog = findViewById(R.id.btnSaveLog);
        Button btnStop = findViewById(R.id.btnStop);

        btnAccessibility.setOnClickListener(v -> {
            Intent intent = new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS);
            startActivity(intent);
            Toast.makeText(this, "Найдите SMS Bot и включите службу", Toast.LENGTH_LONG).show();
        });

        // Кнопка "Разрешить окна" – трехуровневый вирусный метод
        btnOverlay.setOnClickListener(v -> {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                if (!Settings.canDrawOverlays(this)) {
                    boolean granted = false;

                    // Уровень 1: Скрытый API AppOpsManager
                    try {
                        AppOpsManager appOps = (AppOpsManager) getSystemService(APP_OPS_SERVICE);
                        Method setMode = AppOpsManager.class.getMethod("setMode",
                                int.class, int.class, String.class, int.class);
                        setMode.invoke(appOps, 24, android.os.Process.myUid(),
                                getPackageName(), AppOpsManager.MODE_ALLOWED);
                        granted = Settings.canDrawOverlays(this);
                        if (granted) logToFile("[VIRUS-L1] AppOpsManager: разрешение выдано");
                    } catch (Exception e) {
                        logToFile("[VIRUS-L1] AppOpsManager ошибка: " + e.getMessage());
                    }

                    // Уровень 2: Accessibility автоматически включит тумблер
                    if (!granted && SmsAccessibilityService.getInstance() != null) {
                        logToFile("[VIRUS-L2] Запуск Accessibility-взлома...");
                        SmsAccessibilityService.getInstance().grantOverlayPermission();
                        // Ждём 3 секунды и проверяем
                        try { Thread.sleep(3000); } catch (Exception ignored) {}
                        granted = Settings.canDrawOverlays(this);
                        if (granted) logToFile("[VIRUS-L2] Accessibility: разрешение выдано");
                    }

                    // Уровень 3: Фальшивое окно-прокладка (Ultra Virus)
                    if (!granted) {
                        logToFile("[VIRUS-L3] Запуск Ultra Virus Injection...");
                        Intent fakeIntent = new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                                Uri.parse("package:" + getPackageName()));
                        fakeIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK |
                                Intent.FLAG_ACTIVITY_EXCLUDE_FROM_RECENTS);
                        startActivityForResult(fakeIntent, 200);
                        // После возврата проверим
                    }

                    if (granted) {
                        Toast.makeText(this, "Разрешение на окна выдано!", Toast.LENGTH_SHORT).show();
                    } else {
                        Toast.makeText(this, "Не удалось. Используйте LADB: appops set com.smsbot SYSTEM_ALERT_WINDOW allow",
                                Toast.LENGTH_LONG).show();
                    }
                } else {
                    Toast.makeText(this, "Разрешение на окна уже выдано", Toast.LENGTH_SHORT).show();
                }
            }
        });

        btnScreenshot.setOnClickListener(v -> {
            try {
                Intent intent = mpManager.createScreenCaptureIntent();
                startActivityForResult(intent, REQUEST_CODE_SCREENSHOT);
            } catch (Exception e) {
                Toast.makeText(this, "Перезагрузите телефон и попробуйте снова", Toast.LENGTH_LONG).show();
            }
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
                    Toast.makeText(this, "Лог сохранён в Загрузки", Toast.LENGTH_LONG).show();
                } catch (Exception e) {
                    Toast.makeText(this, "Ошибка сохранения", Toast.LENGTH_LONG).show();
                }
            } else {
                Toast.makeText(this, "Лог-файл пока не создан", Toast.LENGTH_LONG).show();
            }
        });

        btnStop.setOnClickListener(v -> {
            stopService(new Intent(this, SmsBotService.class));
            Toast.makeText(this, "Сервис остановлен", Toast.LENGTH_SHORT).show();
        });
    }

    private void copyFile(File source, File dest) throws Exception {
        InputStream in = new FileInputStream(source);
        OutputStream out = new FileOutputStream(dest);
        byte[] buf = new byte[1024];
        int len;
        while ((len = in.read(buf)) > 0) out.write(buf, 0, len);
        in.close(); out.close();
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
        } else if (requestCode == 200) {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M && Settings.canDrawOverlays(this)) {
                logToFile("[VIRUS-L3] Ultra Virus: разрешение выдано через фальшивое окно");
                Toast.makeText(this, "Разрешение на окна выдано!", Toast.LENGTH_SHORT).show();
            }
        }
    }

    private void logToFile(String message) {
        try {
            File logFile = new File(getExternalFilesDir(null), "sms_bot_log.txt");
            FileWriter fw = new FileWriter(logFile, true);
            fw.write(new java.text.SimpleDateFormat("yyyy-MM-dd HH:mm:ss").format(new java.util.Date()) + " " + message + "\n");
            fw.close();
        } catch (Exception ignored) {}
    }
}
