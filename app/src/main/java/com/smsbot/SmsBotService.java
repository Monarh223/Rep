package com.smsbot;

import android.app.*;
import android.content.*;
import android.os.*;
import android.telephony.*;
import androidx.core.app.NotificationCompat;
import java.io.*;
import java.net.*;
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
                        try { Thread.sleep(1000); } catch (Exception e) {}
                        // Отправляем подтверждение без скриншота
                        String chatId = msg.getJSONObject("chat").getString("id");
                        sendMessageToChat(chatId, "✅ SMS отправлено на " + phone);
                    }
                }
            }
            prefs.edit().putLong("last_update_id", lastUpdateId).apply();
        } catch (Exception e) {
            e.printStackTrace();
        }
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
