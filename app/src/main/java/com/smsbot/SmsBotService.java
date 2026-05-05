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
import java.util.concurrent.*;
import org.json.*;

public class SmsBotService extends Service {
    private boolean running = true;
    private String serverUrl = "wss://rep-production-730f.up.railway.app/ws";
    private WebSocketClient client;
    private SharedPreferences prefs;
    private int sentCount = 0;
    private int failCount = 0;
    private String groupId = "";

    @Override
    public void onCreate() {
        super.onCreate();
        prefs = getSharedPreferences("smsbot", MODE_PRIVATE);
        startForeground(1, buildNotification());
        connectWebSocket();
    }

    private void connectWebSocket() {
        new Thread(() -> {
            while (running) {
                try {
                    client = new WebSocketClient(new URI(serverUrl)) {
                        @Override
                        public void onOpen(ServerHandshake handshakedata) {
                            sendNotification("Подключено к серверу");
                        }

                        @Override
                        public void onMessage(String message) {
                            processTask(message);
                        }

                        @Override
                        public void onClose(int code, String reason, boolean remote) {
                            sendNotification("Соединение закрыто, переподключение...");
                        }

                        @Override
                        public void onError(Exception ex) {
                            ex.printStackTrace();
                        }
                    };
                    client.connectBlocking();
                    break;
                } catch (Exception e) {
                    e.printStackTrace();
                    try { Thread.sleep(5000); } catch (Exception e2) {}
                }
            }
        }).start();
    }

    private void processTask(String message) {
        try {
            JSONObject task = new JSONObject(message);
            if (!task.optString("type", "").equals("send_sms")) return;
            String phone = task.getString("phone");
            String text = task.getString("message");

            // Отправка SMS
            boolean success = true;
            try {
                SmsManager.getDefault().sendTextMessage(phone, null, text, null, null);
                sentCount++;
                updateNotification();
                Thread.sleep(1500);
            } catch (Exception e) {
                success = false;
                failCount++;
                updateNotification();
            }

            // Скриншот (если есть MediaProjection)
            byte[] screenshotBytes = null;
            try {
                screenshotBytes = takeScreenshot();
            } catch (Exception e) {}

            // Отправляем результат на сервер
            JSONObject result = new JSONObject();
            result.put("type", "sms_result");
            result.put("phone", phone);
            result.put("status", success ? "success" : "failed");
            result.put("target_group", groupId);
            if (screenshotBytes != null) {
                result.put("screenshot", Base64.encodeToString(screenshotBytes, Base64.NO_WRAP));
            }
            if (client != null && client.isOpen()) {
                client.send(result.toString());
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

    private void sendNotification(String text) {
        Notification notification = new NotificationCompat.Builder(this, "smsbot")
                .setContentTitle("SMS Bot")
                .setContentText(text)
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setPriority(NotificationCompat.PRIORITY_LOW)
                .build();
        ((NotificationManager) getSystemService(NOTIFICATION_SERVICE)).notify(2, notification);
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
                .setContentText("Подключение...")
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setPriority(NotificationCompat.PRIORITY_LOW)
                .build();
    }

    @Override
    public IBinder onBind(Intent intent) { return null; }

    @Override
    public void onDestroy() {
        running = false;
        try { if (client != null) client.close(); } catch (Exception e) {}
        super.onDestroy();
    }
}
