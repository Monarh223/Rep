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

                boolean success = true;
                try {
                    SmsManager.getDefault().sendTextMessage(phone, null, template, null, null);
                    sentCount++;
                    Thread.sleep(1000);
                } catch (Exception e) {
                    success = false;
                    failCount++;
                }
                updateNotification();

                if (success) {
                    sendPlainText(chatId, "✅ Доставлено: " + phone);
                } else {
                    sendPlainText(chatId, "❌ Сбой (Не доставлено): " + phone);
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
        String clean = text.replaceFirst(phone.replace("+", "\\+"), "").trim();
        if (clean.isEmpty()) clean = text.replaceFirst("8" + phone.substring(2), "").trim();
        if (clean.isEmpty()) clean = "Сообщение";
        return clean;
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
