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
    private SharedPreferences prefs;

    @Override
    public void onCreate() {
        super.onCreate();
        prefs = getSharedPreferences("smsbot", MODE_PRIVATE);
        botToken = prefs.getString("bot_token", "");
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
            URL url = new URL("https://api.telegram.org/bot" + botToken + "/getUpdates?timeout=2");
            HttpURLConnection conn = (HttpURLConnection) url.openConnection();
            BufferedReader reader = new BufferedReader(new InputStreamReader(conn.getInputStream()));
            StringBuilder sb = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null) sb.append(line);
            reader.close();

            JSONObject j = new JSONObject(sb.toString());
            JSONArray results = j.getJSONArray("result");
            for (int i = 0; i < results.length(); i++) {
                JSONObject update = results.getJSONObject(i);
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

                        // Отправляем SMS
                        SmsManager.getDefault().sendTextMessage(phone, null, message, null, null);
                        try { Thread.sleep(2000); } catch (Exception e) {}

                        // Делаем скриншот
                        byte[] screenshot = takeScreenshot();
                        // Получаем ID целевой группы (предположим, пришло вместе с командой, модифицируем /send)
                        // Пока упрощённо: отправим фото в личку боту, а бот перешлёт
                        String targetGroup = prefs.getString("target_group", "");
                        if (screenshot != null) {
                            sendPhotoToChat(msg.getJSONObject("chat").getString("id"), screenshot, "✅ Доставлено: " + phone);
                        } else {
                            sendMessageToChat(msg.getJSONObject("chat").getString("id"), "✅ Доставлено: " + phone + "\n⚠ Без скрина");
                        }
                    }
                }
            }
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

    private void sendMessageToChat(String chatId, String text) {
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

    private void sendPhotoToChat(String chatId, byte[] photo, String caption) {
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

    private Notification buildNotification() {
        String chId = "smsbot";
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel ch = new NotificationChannel(chId, "SMS Bot", NotificationManager.IMPORTANCE_LOW);
            ((NotificationManager) getSystemService(NOTIFICATION_SERVICE)).createNotificationChannel(ch);
        }
        return new NotificationCompat.Builder(this, chId)
                .setContentTitle("SMS Bot активен")
                .setContentText("Опрашиваю бота...")
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
