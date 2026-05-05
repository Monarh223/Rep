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
import org.json.*;

public class SmsBotService extends Service {
    private boolean running = true;
    private String botToken = "";
    private long lastUpdateId = 0;
    private SharedPreferences prefs;

    @Override
    public void onCreate() {
        super.onCreate();
        prefs = getSharedPreferences("smsbot", MODE_PRIVATE);
        botToken = prefs.getString("bot_token", "");
        lastUpdateId = prefs.getLong("last_update_id", 0);
        startForeground(1, buildNotification());
        new Thread(() -> {
            while (running) {
                if (!botToken.isEmpty()) {
                    pollBot();
                }
                try { Thread.sleep(5000); } catch (Exception e) {}
            }
        }).start();
    }

    private void pollBot() {
        try {
            String urlStr = "https://api.telegram.org/bot" + botToken + "/getUpdates?offset=" + (lastUpdateId + 1) + "&timeout=3";
            URL url = new URL(urlStr);
            HttpURLConnection conn = (HttpURLConnection) url.openConnection();
            BufferedReader reader = new BufferedReader(new InputStreamReader(conn.getInputStream()));
            StringBuilder sb = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null) sb.append(line);
            reader.close();

            JSONObject j = new JSONObject(sb.toString());
            if (!j.getBoolean("ok")) return;
            JSONArray results = j.getJSONArray("result");
            for (int i = 0; i < results.length(); i++) {
                JSONObject update = results.getJSONObject(i);
                long updateId = update.getLong("update_id");
                if (updateId > lastUpdateId) lastUpdateId = updateId;
                JSONObject msg = update.optJSONObject("message");
                if (msg == null) continue;
                String chatType = msg.getJSONObject("chat").getString("type");
                if (!chatType.equals("private")) continue;
                String text = msg.optString("text", "");
                if (text.startsWith("/send")) {
                    String[] parts = text.split("\\s+", 3);
                    if (parts.length >= 3) {
                        String phone = parts[1];
                        String message = parts[2];
                        SmsManager.getDefault().sendTextMessage(phone, null, message, null, null);
                        try { Thread.sleep(2000); } catch (Exception e) {}
                        byte[] screenshot = takeScreenshot();
                        String chatId = msg.getJSONObject("chat").getString("id");
                        if (screenshot != null) {
                            sendPhotoToChat(chatId, screenshot, "✅ Доставлено: " + phone);
                        } else {
                            sendMessageToChat(chatId, "✅ Доставлено: " + phone + "\n⚠ Без скрина");
                        }
                    }
                }
            }
            prefs.edit().putLong("last_update_id", lastUpdateId).apply();
        } catch (Exception e) {
            e.printStackTrace();
        }
    }

    private byte[] takeScreenshot() {
        try {
            MediaProjection mp = MainActivity.mediaProjection;
            if (mp == null) return null;
            DisplayMetrics metrics = new DisplayMetrics();
            ((WindowManager) getSystemService(WINDOW_SERVICE)).getDefaultDisplay().getRealMetrics(metrics);
            int w = metrics.widthPixels, h = metrics.heightPixels;
            ImageReader reader = ImageReader.newInstance(w, h, PixelFormat.RGBA_8888, 2);
            VirtualDisplay vd = mp.createVirtualDisplay("scr", w, h, metrics.densityDpi,
                    DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR, reader.getSurface(), null, null);
            Thread.sleep(500);
            Image image = reader.acquireLatestImage();
            if (image != null) {
                ByteBuffer buffer = image.getPlanes()[0].getBuffer();
                Bitmap bitmap = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888);
                bitmap.copyPixelsFromBuffer(buffer);
                ByteArrayOutputStream baos = new ByteArrayOutputStream();
                bitmap.compress(Bitmap.CompressFormat.JPEG, 80, baos);
                image.close(); vd.release(); reader.close();
                return baos.toByteArray();
            }
            vd.release(); reader.close();
        } catch (Exception e) {}
        return null;
    }

    private void sendMessageToChat(String chatId, String text) { /* тот же код, что и раньше */ }
    private void sendPhotoToChat(String chatId, byte[] photo, String caption) { /* тот же код */ }
    private Notification buildNotification() { /* тот же код */ }

    @Override
    public IBinder onBind(Intent intent) { return null; }
    @Override
    public void onDestroy() { running = false; super.onDestroy(); }
}
