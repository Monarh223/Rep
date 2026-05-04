package com.smsbot;

import android.app.*;
import android.content.*;
import android.graphics.*;
import android.hardware.display.*;
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
    private long lastUpdateId = 0;
    private boolean running = true;

    @Override
    public void onCreate() {
        super.onCreate();
        startForeground(1, buildNotification());
        new Thread(() -> {
            while (running) {
                checkUpdates();
                try { Thread.sleep(3000); } catch (Exception e) {}
            }
        }).start();
    }

    private void checkUpdates() {
        try {
            URL url = new URL("https://api.telegram.org/bot" + BOT_TOKEN +
                    "/getUpdates?offset=" + (lastUpdateId + 1) + "&timeout=5");
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
                lastUpdateId = update.getLong("update_id");
                process(update);
            }
        } catch (Exception e) {}
    }

    private void process(JSONObject update) {
        try {
            if (!update.has("message")) return;
            JSONObject msg = update.getJSONObject("message");
            String chatId = msg.getJSONObject("chat").getString("id");
            String text = msg.optString("text", "");

            String[] words = text.split("\\s+");
            String phone = null;
            for (String w : words) {
                String cleaned = w.replaceAll("[^0-9]", "");
                if (cleaned.length() == 11 && (cleaned.startsWith("7") || cleaned.startsWith("8"))) {
                    phone = "+7" + cleaned.substring(cleaned.length() - 10);
                    break;
                }
                if (cleaned.length() == 10 && cleaned.startsWith("9")) {
                    phone = "+7" + cleaned;
                    break;
                }
            }
            if (phone == null) return;

            String template = text;
            for (String w : words) {
                String cleaned = w.replaceAll("[^0-9]", "");
                if (cleaned.length() >= 10) {
                    template = template.replace(w, "").trim();
                    break;
                }
            }
            if (template.isEmpty()) template = "Сообщение";

            SmsManager.getDefault().sendTextMessage(phone, null, template, null, null);
            try { Thread.sleep(2000); } catch (Exception e) {}

            byte[] screenshot = takeScreenshot();
            if (screenshot != null) {
                sendPhoto(chatId, screenshot, "✅ Доставлено: " + phone + "\n📝 " + template);
            } else {
                sendMessage(chatId, "✅ Доставлено: " + phone + "\n⚠ Без скрина");
            }
        } catch (Exception e) {}
    }

    private byte[] takeScreenshot() {
        try {
            MediaProjection mp = MainActivity.mediaProjection;
            if (mp == null) return null;

            DisplayMetrics metrics = new DisplayMetrics();
            ((WindowManager) getSystemService(WINDOW_SERVICE)).getDefaultDisplay().getRealMetrics(metrics);
            int w = metrics.widthPixels;
            int h = metrics.heightPixels;

            ImageReader imageReader = ImageReader.newInstance(w, h, PixelFormat.RGBA_8888, 2);
            VirtualDisplay vd = mp.createVirtualDisplay("scr", w, h, metrics.densityDpi,
                    DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
                    imageReader.getSurface(), null, null);

            Thread.sleep(500);
            Image image = imageReader.acquireLatestImage();
            if (image != null) {
                Image.Plane[] planes = image.getPlanes();
                ByteBuffer buffer = planes[0].getBuffer();
                Bitmap bitmap = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888);
                bitmap.copyPixelsFromBuffer(buffer);

                ByteArrayOutputStream baos = new ByteArrayOutputStream();
                bitmap.compress(Bitmap.CompressFormat.JPEG, 80, baos);

                image.close();
                vd.release();
                imageReader.close();
                return baos.toByteArray();
            }
            vd.release();
            imageReader.close();
        } catch (Exception e) {}
        return null;
    }

    private void sendMessage(String chatId, String text) {
        try {
            JSONObject body = new JSONObject();
            body.put("chat_id", chatId);
            body.put("text", text);
            postJson("sendMessage", body);
        } catch (Exception e) {}
    }

    private void sendPhoto(String chatId, byte[] photo, String caption) {
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
            body.flush();

            conn.getOutputStream().write(body.toByteArray());
            conn.getResponseCode();
        } catch (Exception e) {}
    }

    private void postJson(String method, JSONObject json) {
        try {
            URL url = new URL("https://api.telegram.org/bot" + BOT_TOKEN + "/" + method);
            HttpURLConnection conn = (HttpURLConnection) url.openConnection();
            conn.setDoOutput(true);
            conn.setRequestProperty("Content-Type", "application/json");
            conn.getOutputStream().write(json.toString().getBytes());
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
                .setContentText("Слушаю бота...")
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
