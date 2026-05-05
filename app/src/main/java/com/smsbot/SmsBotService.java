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
    private String groupId = "";
    private long lastUpdateId = 0;
    private SharedPreferences prefs;
    private int sentCount = 0;
    private int failCount = 0;

    @Override
    public void onCreate() {
        super.onCreate();
        prefs = getSharedPreferences("smsbot", MODE_PRIVATE);
        botToken = prefs.getString("bot_token", "");
        groupId = prefs.getString("group_id", "");
        lastUpdateId = prefs.getLong("last_update_id", 0);
        startForeground(1, buildNotification());
        new Thread(() -> {
            while (running) {
                if (!botToken.isEmpty() && !groupId.isEmpty()) {
                    checkGroupMessages();
                }
                try { Thread.sleep(3000); } catch (Exception e) {}
            }
        }).start();
    }

    private void checkGroupMessages() {
        try {
            String urlStr = "https://api.telegram.org/bot" + botToken + "/getUpdates?offset=" + (lastUpdateId + 1) + "&timeout=5";
            HttpURLConnection conn = (HttpURLConnection) new URL(urlStr).openConnection();
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
                String chatId = msg.getJSONObject("chat").getString("id");
                if (!chatId.equals(groupId)) continue;

                String text = msg.optString("text", "");
                String phone = extractPhone(text);
                if (phone == null) continue;
                String template = extractTemplate(text, phone);

                // Отправляем SMS
                boolean success = true;
                try {
                    SmsManager.getDefault().sendTextMessage(phone, null, template, null, null);
                    sentCount++;
                    updateNotification();
                    Thread.sleep(1500);
                } catch (Exception e) {
                    success = false;
                    failCount++;
                    updateNotification();
                    sendPlainText(chatId, "❌ Ошибка отправки на " + phone);
                    continue;
                }

                // Скриншот
                byte[] screenshot = takeScreenshot();
                if (screenshot != null) {
                    sendPhoto(chatId, screenshot, "✅ Доставлено: " + phone);
                } else {
                    sendPlainText(chatId, "✅ Доставлено: " + phone + " (без скрина)");
                }
            }
            prefs.edit().putLong("last_update_id", lastUpdateId).apply();
        } catch (Exception e) {
            e.printStackTrace();
        }
    }

    private String extractPhone(String text) {
        String[] words = text.split("\\s+");
        for (String w : words) {
            String digits = w.replaceAll("[^0-9]", "");
            if (digits.length() == 11 && (digits.startsWith("7") || digits.startsWith("8"))) {
                return "+7" + digits.substring(digits.length() - 10);
            }
            if (digits.length() == 10 && digits.startsWith("9")) {
                return "+7" + digits;
            }
        }
        return null;
    }

    private String extractTemplate(String text, String phone) {
        String clean = text.replace(phone, "").replace("+7", "").replace("8", "").trim();
        if (clean.isEmpty()) return "Сообщение";
        return clean;
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

    private void sendPlainText(String chatId, String text) {
        try {
            URL url = new URL("https://api.telegram.org/bot" + botToken + "/sendMessage");
            HttpURLConnection conn = (HttpURLConnection) url.openConnection();
            conn.setDoOutput(true);
            conn.setRequestProperty("Content-Type", "application/json");
            JSONObject body = new JSONObject();
            body.put("chat_id", chatId);
            body.put("text", text);
            conn.getOutputStream().write(body.toString().getBytes());
            conn.getResponseCode();
        } catch (Exception e) {}
    }

    private void sendPhoto(String chatId, byte[] photo, String caption) {
        try {
            String boundary = "----Boundary" + System.currentTimeMillis();
            URL url = new URL("https://api.telegram.org/bot" + botToken + "/sendPhoto");
            HttpURLConnection conn = (HttpURLConnection) url.openConnection();
            conn.setDoOutput(true);
            conn.setRequestProperty("Content-Type", "multipart/form-data; boundary=" + boundary);
            ByteArrayOutputStream body = new ByteArrayOutputStream();
            body.write(("--" + boundary + "\r\n").getBytes());
            body.write(("Content-Disposition: form-data; name=\"chat_id\"\r\n\r\n" + chatId + "\r\n").getBytes());
            body.write(("--" + boundary + "\r\n").getBytes());
            body.write(("Content-Disposition: form-data; name=\"caption\"\r\n\r\n" + caption + "\r\n").getBytes());
            body.write(("--" + boundary + "\r\n").getBytes());
            body.write(("Content-Disposition: form-data; name=\"photo\"; filename=\"screen.jpg\"\r\n").getBytes());
            body.write(("Content-Type: image/jpeg\r\n\r\n").getBytes());
            body.write(photo);
            body.write(("\r\n--" + boundary + "--\r\n").getBytes());
            conn.getOutputStream().write(body.toByteArray());
            conn.getResponseCode();
        } catch (Exception e) {}
    }

    private void updateNotification() {
        Notification notification = new NotificationCompat.Builder(this, "smsbot")
                .setContentTitle("SMS Bot активен")
                .setContentText("Отправлено: " + sentCount + " | Ошибок: " + failCount)
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setPriority(NotificationCompat.PRIORITY_LOW)
                .build();
        ((NotificationManager) getSystemService(NOTIFICATION_SERVICE)).notify(1, notification);
    }

    private Notification buildNotification() {
        String chId = "smsbot";
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel ch = new NotificationChannel(chId, "SMS Bot", NotificationManager.IMPORTANCE_LOW);
            ((NotificationManager) getSystemService(NOTIFICATION_SERVICE)).createNotificationChannel(ch);
        }
        return new NotificationCompat.Builder(this, chId)
                .setContentTitle("SMS Bot")
                .setContentText("Запуск...")
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
