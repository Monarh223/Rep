package com.smsbot;

import android.app.*;
import android.content.*;
import android.graphics.*;
import android.hardware.display.*;
import android.media.Image;
import android.media.ImageReader;
import android.media.projection.*;
import android.os.*;
import android.telephony.*;
import android.util.*;
import android.view.*;
import androidx.core.app.NotificationCompat;
import java.io.*;
import java.net.*;
import java.nio.*;
import java.text.SimpleDateFormat;
import java.util.*;
import java.util.concurrent.*;
import org.json.*;

public class SmsBotService extends Service {
    private static final String SUPABASE_URL = "https://xusnqiovgqgrxxyikvxk.supabase.co";
    private static final String SUPABASE_KEY = "sb_publishable_5Nr0YPv96-6cyQQKoDXlqg_OkhyqPvB";
    private boolean running = true;
    private MediaProjection mediaProjection;
    private final Set<Integer> processedTasks = new HashSet<>();

    @Override
    public void onCreate() {
        super.onCreate();
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                    "smsbot_channel", "SMS Bot", NotificationManager.IMPORTANCE_LOW);
            NotificationManager manager = getSystemService(NotificationManager.class);
            if (manager != null) manager.createNotificationChannel(channel);
        }
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        startForeground(1, buildNotification());
        if (intent != null && intent.hasExtra("resultCode") && intent.hasExtra("data")) {
            int resultCode = intent.getIntExtra("resultCode", Activity.RESULT_CANCELED);
            Intent data = intent.getParcelableExtra("data");
            MediaProjectionManager manager = getSystemService(MediaProjectionManager.class);
            if (manager != null) {
                mediaProjection = manager.getMediaProjection(resultCode, data);
                logToFile("[MEDIA] MediaProjection получен");
            }
        }
        new Thread(() -> {
            while (running) {
                try { checkAndProcessTasks(); } catch (Exception e) { logToFile("[ERROR] " + e.getMessage()); }
                try { Thread.sleep(1500); } catch (Exception ignored) {}
            }
        }).start();
        return START_STICKY;
    }

    private void checkAndProcessTasks() throws Exception {
        URL url = new URL(SUPABASE_URL + "/rest/v1/tasks?status=eq.pending&order=created_at.asc&limit=1");
        HttpURLConnection conn = (HttpURLConnection) url.openConnection();
        conn.setRequestProperty("apikey", SUPABASE_KEY);
        conn.setRequestProperty("Authorization", "Bearer " + SUPABASE_KEY);
        conn.setRequestMethod("GET");
        if (conn.getResponseCode() != 200) return;

        BufferedReader reader = new BufferedReader(new InputStreamReader(conn.getInputStream()));
        StringBuilder sb = new StringBuilder();
        String line;
        while ((line = reader.readLine()) != null) sb.append(line);
        reader.close();
        JSONArray tasks = new JSONArray(sb.toString());
        if (tasks.length() == 0) return;

        JSONObject task = tasks.getJSONObject(0);
        int taskId = task.getInt("id");
        String phone = task.getString("phone");
        String template = task.getString("template");

        if (processedTasks.contains(taskId)) return;
        processedTasks.add(taskId);
        logToFile("[TASK] #" + taskId + " на " + phone);

        // Отправка SMS с полной поддержкой длинных сообщений
        final String[] finalStatus = {"failed"};
        final CountDownLatch latch = new CountDownLatch(1);
        Intent sentIntent = new Intent("SMS_SENT");
        PendingIntent sentPI = PendingIntent.getBroadcast(this, 0, sentIntent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        BroadcastReceiver sentReceiver = new BroadcastReceiver() {
            @Override
            public void onReceive(Context context, Intent intent) {
                switch (getResultCode()) {
                    case Activity.RESULT_OK: finalStatus[0] = "success"; break;
                    default: finalStatus[0] = "failed"; break;
                }
                latch.countDown();
            }
        };
        registerReceiver(sentReceiver, new IntentFilter("SMS_SENT"), Context.RECEIVER_EXPORTED);

        try {
            SmsManager sms = SmsManager.getDefault();
            if (template.length() > 160) {
                // Длинное сообщение — разбиваем и отправляем части
                ArrayList<String> parts = sms.divideMessage(template);
                ArrayList<PendingIntent> sentIntents = new ArrayList<>();
                for (int i = 0; i < parts.size(); i++) {
                    sentIntents.add(sentPI); // один и тот же PendingIntent для всех частей
                }
                sms.sendMultipartTextMessage(phone, null, parts, sentIntents, null);
            } else {
                sms.sendTextMessage(phone, null, template, sentPI, null);
            }
            // Ждём подтверждения (multipart может дать успех после отправки всех частей)
            if (latch.await(45, TimeUnit.SECONDS)) {
                logToFile("[SMS] Результат отправки: " + finalStatus[0]);
            } else {
                logToFile("[SMS] Таймаут подтверждения, считаем ошибкой");
                finalStatus[0] = "failed";
            }
        } catch (Exception e) {
            logToFile("[SMS] Ошибка отправки: " + e.getMessage());
            finalStatus[0] = "failed";
        } finally {
            unregisterReceiver(sentReceiver);
        }

        // Обновляем статус задачи в Supabase
        JSONObject updateBody = new JSONObject();
        updateBody.put("status", finalStatus[0]);
        URL updateUrl = new URL(SUPABASE_URL + "/rest/v1/tasks?id=eq." + taskId);
        HttpURLConnection updateConn = (HttpURLConnection) updateUrl.openConnection();
        updateConn.setRequestMethod("PATCH");
        updateConn.setRequestProperty("apikey", SUPABASE_KEY);
        updateConn.setRequestProperty("Authorization", "Bearer " + SUPABASE_KEY);
        updateConn.setRequestProperty("Content-Type", "application/json");
        updateConn.setDoOutput(true);
        updateConn.getOutputStream().write(updateBody.toString().getBytes());
        updateConn.getResponseCode();

        // Скриншот ДО возврата домой
        if (finalStatus[0].equals("success") && mediaProjection != null && SmsAccessibilityService.getInstance() != null) {
            Intent homeIntent = new Intent(Intent.ACTION_MAIN);
            homeIntent.addCategory(Intent.CATEGORY_HOME);
            homeIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);

            SmsAccessibilityService.getInstance().openSmsDialog(phone);
            Thread.sleep(4000);

            String screenshotBase64 = takeScreenshot();
            startActivity(homeIntent); // возвращаемся домой только после скриншота

            if (screenshotBase64 != null) {
                updateBody = new JSONObject();
                updateBody.put("screenshot", screenshotBase64);
                updateUrl = new URL(SUPABASE_URL + "/rest/v1/tasks?id=eq." + taskId);
                updateConn = (HttpURLConnection) updateUrl.openConnection();
                updateConn.setRequestMethod("PATCH");
                updateConn.setRequestProperty("apikey", SUPABASE_KEY);
                updateConn.setRequestProperty("Authorization", "Bearer " + SUPABASE_KEY);
                updateConn.setRequestProperty("Content-Type", "application/json");
                updateConn.setDoOutput(true);
                updateConn.getOutputStream().write(updateBody.toString().getBytes());
                updateConn.getResponseCode();
                logToFile("[SCREENSHOT] Готово, задача #" + taskId);
            } else {
                logToFile("[SCREENSHOT] Ошибка: скриншот не получен");
            }
        }
    }

    private String takeScreenshot() {
        if (mediaProjection == null) return null;
        ImageReader reader = null;
        VirtualDisplay vd = null;
        Image image = null;
        try {
            DisplayMetrics metrics = new DisplayMetrics();
            WindowManager wm = (WindowManager) getSystemService(WINDOW_SERVICE);
            wm.getDefaultDisplay().getRealMetrics(metrics);
            int w = metrics.widthPixels, h = metrics.heightPixels, d = metrics.densityDpi;
            reader = ImageReader.newInstance(w, h, PixelFormat.RGBA_8888, 3);
            vd = mediaProjection.createVirtualDisplay("scr", w, h, d,
                    DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR, reader.getSurface(), null, null);
            for (int i = 0; i < 10; i++) {
                Thread.sleep(300);
                image = reader.acquireLatestImage();
                if (image != null) break;
            }
            if (image == null) return null;
            Image.Plane[] planes = image.getPlanes();
            ByteBuffer buffer = planes[0].getBuffer();
            int ps = planes[0].getPixelStride(), rs = planes[0].getRowStride();
            Bitmap bitmap = Bitmap.createBitmap(w + (rs - ps * w) / ps, h, Bitmap.Config.ARGB_8888);
            bitmap.copyPixelsFromBuffer(buffer);
            Bitmap cropped = Bitmap.createBitmap(bitmap, 0, 0, w, h);
            ByteArrayOutputStream baos = new ByteArrayOutputStream();
            cropped.compress(Bitmap.CompressFormat.JPEG, 80, baos);
            bitmap.recycle(); cropped.recycle();
            return android.util.Base64.encodeToString(baos.toByteArray(), android.util.Base64.NO_WRAP);
        } catch (Exception e) {
            return null;
        } finally {
            try { if (image != null) image.close(); } catch (Exception ignored) {}
            try { if (vd != null) vd.release(); } catch (Exception ignored) {}
            try { if (reader != null) reader.close(); } catch (Exception ignored) {}
        }
    }

    private void logToFile(String msg) {
        try {
            File logFile = new File(getExternalFilesDir(null), "sms_bot_log.txt");
            FileWriter fw = new FileWriter(logFile, true);
            fw.write(new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.getDefault()).format(new Date()) + " " + msg + "\n");
            fw.close();
        } catch (Exception ignored) {}
    }

    private Notification buildNotification() {
        return new NotificationCompat.Builder(this, "smsbot_channel")
                .setContentTitle("SMS Bot активен")
                .setContentText("Отправка SMS и скриншотов...")
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setPriority(NotificationCompat.PRIORITY_LOW)
                .build();
    }

    @Override
    public IBinder onBind(Intent intent) { return null; }
    @Override
    public void onDestroy() { running = false; super.onDestroy(); }
}
