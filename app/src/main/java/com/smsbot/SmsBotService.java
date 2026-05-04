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
    private static final String BOT_TOKEN = "8452616761:AAE7E-cadqGwikNwn44b-evrzdSCdFsN8Zw";
    private String phoneChatId = null;
    private boolean running = true;

    @Override
    public void onCreate() {
        super.onCreate();
        startForeground(1, buildNotification());
        new Thread(() -> {
            while (running) {
                if (phoneChatId != null) {
                    checkCommands();
                }
                try { Thread.sleep(3000); } catch (Exception e) {}
            }
        }).start();
    }

    public void setPhoneChatId(String chatId) {
        this.phoneChatId = chatId;
        sendMessageToChat(chatId, "✅ Телефон подключен. Ожидаю команды.");
    }

    private void checkCommands() {
        try {
            // Отправляем сообщение-запрос боту
            sendMessageToChat(phoneChatId, "/get_task");

            // Читаем ответ (бот пришлет команду в личку)
            URL url = new URL("https://api.telegram.org/bot" + BOT_TOKEN +
                    "/getUpdates?offset=-1&timeout=3");
            HttpURLConnection conn = (HttpURLConnection) url.openConnection();
            BufferedReader reader = new BufferedReader(new InputStreamReader(conn.getInputStream()));
            StringBuilder json = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null) json.append(line);
            reader.close();

            JSONObject j = new JSONObject(json.toString());
            JSONArray results = j.getJSONArray("result");
            for (int i = 0; i < results.length(); i++) {
                JSONObject update = results.getJSONObject(i);
                JSONObject msg = update.optJSONObject("message");
                if (msg == null) continue;
                
                JSONObject chat = msg.getJSONObject("chat");
                String chatType = chat.getString("type");
                if (!chatType.equals("private")) continue;
                if (!chat.getString("id").equals(phoneChatId)) continue;

                String text = msg.optString("text", "");
                if (text.startsWith("/send")) {
                    String[] parts = text.split("\\s+", 3);
                    if (parts.length >= 3) {
                        String phone = parts[1];
                        String message = parts[2];

                        SmsManager.getDefault().sendTextMessage(phone, null, message, null, null);
                        try { Thread.sleep(2000); } catch (Exception e) {}

                        byte[] screenshot = takeScreenshot();
                        if (screenshot != null) {
                            sendPhotoToChat(phoneChatId, screenshot, "✅ Доставлено: " + phone);
                        } else {
                            sendMessageToChat(phoneChatId, "✅ Доставлено: " + phone + "\n⚠ Без скрина");
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
            URL url = new URL("https://api.telegram.org/bot" + BOT_TOKEN + "/sendMessage");
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
            URL url = new URL("https://api.telegram.org/bot" + BOT_TOKEN + "/sendPhoto");
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
                .setContentText("Ожидаю команды...")
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setPriority(NotificationCompat.PRIORITY_LOW)
                .build();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return new LocalBinder();
    }

    public class LocalBinder extends Binder {
        public SmsBotService getService() {
            return SmsBotService.this;
        }
    }

    @Override
    public void onDestroy() {
        running = false;
        super.onDestroy();
    }
}
