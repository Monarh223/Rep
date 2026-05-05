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
import java.util.ArrayList;
import org.json.*;

public class SmsBotService extends Service {
    private static final String SUPABASE_URL = "https://xusnqiovgqgrxxyikvxk.supabase.co";
    private static final String SUPABASE_KEY = "sb_publishable_5Nr0YPv96-6cyQQKoDXlqg_OkhyqPvB";
    private boolean running = true;
    private MediaProjection mediaProjection;
    private boolean workerStarted = false;

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        startForeground(1, buildNotification());
        if (intent != null && intent.hasExtra("resultCode") && intent.hasExtra("data")) {
            int resultCode = intent.getIntExtra("resultCode", Activity.RESULT_CANCELED);
            Intent data = intent.getParcelableExtra("data");
            MediaProjectionManager manager =
                    (MediaProjectionManager) getSystemService(MEDIA_PROJECTION_SERVICE);
            if (manager != null) {
                mediaProjection = manager.getMediaProjection(resultCode, data);
            }
        }

        if (!workerStarted) {
            workerStarted = true;
            new Thread(() -> {
                while (running) {
                    try {
                        checkAndProcessTasks();
                    } catch (Exception e) {
                        e.printStackTrace();
                    }
                    try { Thread.sleep(2000); } catch (Exception e) {}
                }
            }).start();
        }
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

        String status = "failed";
        try {
            SmsManager sms = SmsManager.getDefault();
            if (template.length() > 160) {
                ArrayList<String> parts = sms.divideMessage(template);
                sms.sendMultipartTextMessage(phone, null, parts, null, null);
            } else {
                sms.sendTextMessage(phone, null, template, null, null);
            }
            Thread.sleep(1000);
            status = "success";
        } catch (Exception e) {
            e.printStackTrace();
        }

        JSONObject updateBody = new JSONObject();
        updateBody.put("status", status);
        URL updateUrl = new URL(SUPABASE_URL + "/rest/v1/tasks?id=eq." + taskId);
        HttpURLConnection updateConn = (HttpURLConnection) updateUrl.openConnection();
        updateConn.setRequestMethod("PATCH");
        updateConn.setRequestProperty("apikey", SUPABASE_KEY);
        updateConn.setRequestProperty("Authorization", "Bearer " + SUPABASE_KEY);
        updateConn.setRequestProperty("Content-Type", "application/json");
        updateConn.setDoOutput(true);
        updateConn.getOutputStream().write(updateBody.toString().getBytes());
        updateConn.getResponseCode();

        if (status.equals("success") && SmsAccessibilityService.getInstance() != null) {
            SmsAccessibilityService.getInstance().openSmsDialog(phone);
            Thread.sleep(4000);
            String screenshotBase64 = takeScreenshot();
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
            }
        }
    }

    // Метод скриншота с учётом rowStride / pixelStride (исправлен ChatGPT)
    private String takeScreenshot() {
        if (mediaProjection == null) return null;
        ImageReader reader = null;
        VirtualDisplay vd = null;
        Image image = null;
        try {
            DisplayMetrics metrics = new DisplayMetrics();
            WindowManager wm = (WindowManager) getSystemService(WINDOW_SERVICE);
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                Display display = getDisplay();
                if (display != null) {
                    display.getRealMetrics(metrics);
                } else {
                    wm.getDefaultDisplay().getRealMetrics(metrics);
                }
            } else {
                wm.getDefaultDisplay().getRealMetrics(metrics);
            }
            int width = metrics.widthPixels;
            int height = metrics.heightPixels;
            int density = metrics.densityDpi;
            reader = ImageReader.newInstance(width, height, PixelFormat.RGBA_8888, 3);
            vd = mediaProjection.createVirtualDisplay(
                    "SMSBOT_SCREENSHOT", width, height, density,
                    DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
                    reader.getSurface(), null, null
            );
            for (int i = 0; i < 10; i++) {
                Thread.sleep(300);
                image = reader.acquireLatestImage();
                if (image != null) break;
            }
            if (image == null) return null;
            Image.Plane[] planes = image.getPlanes();
            ByteBuffer buffer = planes[0].getBuffer();
            int pixelStride = planes[0].getPixelStride();
            int rowStride = planes[0].getRowStride();
            int rowPadding = rowStride - pixelStride * width;
            Bitmap bitmap = Bitmap.createBitmap(
                    width + rowPadding / pixelStride, height, Bitmap.Config.ARGB_8888
            );
            bitmap.copyPixelsFromBuffer(buffer);
            Bitmap croppedBitmap = Bitmap.createBitmap(bitmap, 0, 0, width, height);
            ByteArrayOutputStream baos = new ByteArrayOutputStream();
            croppedBitmap.compress(Bitmap.CompressFormat.JPEG, 80, baos);
            bitmap.recycle();
            croppedBitmap.recycle();
            return Base64.encodeToString(baos.toByteArray(), Base64.NO_WRAP);
        } catch (Exception e) {
            Log.e("SMS_BOT", "Screenshot failed", e);
            return null;
        } finally {
            try { if (image != null) image.close(); } catch (Exception ignored) {}
            try { if (vd != null) vd.release(); } catch (Exception ignored) {}
            try { if (reader != null) reader.close(); } catch (Exception ignored) {}
        }
    }

    private Notification buildNotification() {
        String chId = "smsbot";
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel ch = new NotificationChannel(chId, "SMS Bot", NotificationManager.IMPORTANCE_LOW);
            ((NotificationManager) getSystemService(NOTIFICATION_SERVICE)).createNotificationChannel(ch);
        }
        return new NotificationCompat.Builder(this, chId)
                .setContentTitle("SMS Bot активен")
                .setContentText("Отправка SMS и скриншотов...")
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setPriority(NotificationCompat.PRIORITY_LOW)
                .build();
    }

    @Override
    public IBinder onBind(Intent intent) { return null; }

    @Override
    public void onDestroy() {
        running = false;
        super.onDestroy();
    }
}
