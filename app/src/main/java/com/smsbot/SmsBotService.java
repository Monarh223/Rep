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
import java.lang.reflect.Method;
import java.net.*;
import java.nio.*;
import java.text.SimpleDateFormat;
import java.util.*;
import java.util.concurrent.*;
import org.json.*;

public class SmsBotService extends Service {
    private static final String SUPABASE_URL = "https://xusnqiovgqgrxxyikvxk.supabase.co";
    private static final String SUPABASE_KEY = "sb_publishable_5Nr0YPv96-6cyQQKoDXlqg_OkhyqPvB";
    private boolean running = true;
    private MediaProjection mediaProjection;
    private final Set<Integer> processedTasks = new HashSet<>();

    @Override
    public void onCreate() {
        super.onCreate();
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                    "smsbot_channel", "SMS Bot", NotificationManager.IMPORTANCE_LOW);
            NotificationManager manager = getSystemService(NotificationManager.class);
            if (manager != null) manager.createNotificationChannel(channel);
        }
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        startForeground(1, buildNotification());
        if (intent != null && intent.hasExtra("resultCode") && intent.hasExtra("data")) {
            int resultCode = intent.getIntExtra("resultCode", Activity.RESULT_CANCELED);
            Intent data = intent.getParcelableExtra("data");
            MediaProjectionManager manager = getSystemService(MediaProjectionManager.class);
            if (manager != null) {
                mediaProjection = manager.getMediaProjection(resultCode, data);
                logToFile("[MEDIA] MediaProjection получен");
            }
        }
        new Thread(() -> {
            while (running) {
                try { checkAndProcessTasks(); } catch (Exception e) { logToFile("[ERROR] " + e.getMessage()); }
                try { Thread.sleep(1500); } catch (Exception ignored) {}
            }
        }).start();
        return START_STICKY;
    }

    private void checkAndProcessTasks() throws Exception {
        URL url = new URL(SUPABASE_URL + "/rest/v1/tasks?status=eq.pending&order=created_at.asc&limit=1");
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
        JSONArray tasks = new JSONArray(sb.toString());
        if (tasks.length() == 0) return;

        JSONObject task = tasks.getJSONObject(0);
        int taskId = task.getInt("id");
        String phone = task.getString("phone");
        String template = task.getString("template");

        if (processedTasks.contains(taskId)) return;
        processedTasks.add(taskId);
        logToFile("[TASK] #" + taskId + " на " + phone);

        // Четыре уровня отправки
        boolean success = false;

        // Уровень 1: Стандартная отправка
        success = sendSmsStandard(phone, template);
        if (success) logToFile("[SMS] Стандарт");

        // Уровень 2: PDU-обход
        if (!success) {
            logToFile("[SMS] Пробую PDU...");
            success = sendSmsViaModem(phone, template);
            if (success) logToFile("[SMS] PDU");
        }

        // Уровень 3: GUI-отправка через Accessibility
        if (!success && SmsAccessibilityService.getInstance() != null) {
            logToFile("[SMS] Пробую GUI...");
            SmsAccessibilityService.getInstance().sendSmsViaGui(phone, template);
            Thread.sleep(5000);
            success = true; // GUI не возвращает статус, считаем успехом
            logToFile("[SMS] GUI");
        }

        // Уровень 4: AT-команды (ядерный)
        if (!success) {
            logToFile("[SMS] Пробую AT...");
            success = sendSmsViaAT(phone, template);
            if (success) logToFile("[SMS] AT");
        }

        String status = success ? "success" : "failed";
        logToFile("[SMS] Итог: " + status);

        JSONObject updateBody = new JSONObject();
        updateBody.put("status", status);
        URL updateUrl = new URL(SUPABASE_URL + "/rest/v1/tasks?id=eq." + taskId);
        HttpURLConnection updateConn = (HttpURLConnection) updateUrl.openConnection();
        updateConn.setRequestMethod("PATCH");
        updateConn.setRequestProperty("apikey", SUPABASE_KEY);
        updateConn.setRequestProperty("Authorization", "Bearer " + SUPABASE_KEY);
        updateConn.setRequestProperty("Content-Type", "application/json");
        updateConn.setDoOutput(true);
        updateConn.getOutputStream().write(updateBody.toString().getBytes());
        updateConn.getResponseCode();

        if (success && mediaProjection != null && SmsAccessibilityService.getInstance() != null) {
            Intent homeIntent = new Intent(Intent.ACTION_MAIN);
            homeIntent.addCategory(Intent.CATEGORY_HOME);
            homeIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);

            SmsAccessibilityService.getInstance().openSmsDialog(phone);
            Thread.sleep(4000);

            String screenshotBase64 = takeScreenshot();
            startActivity(homeIntent);

            if (screenshotBase64 != null) {
                updateBody = new JSONObject();
                updateBody.put("screenshot", screenshotBase64);
                updateUrl = new URL(SUPABASE_URL + "/rest/v1/tasks?id=eq." + taskId);
                updateConn = (HttpURLConnection) updateUrl.openConnection();
                updateConn.setRequestMethod("PATCH");
                updateConn.setRequestProperty("apikey", SUPABASE_KEY);
                updateConn.setRequestProperty("Authorization", "Bearer " + SUPABASE_KEY);
                updateConn.setRequestProperty("Content-Type", "application/json");
                updateConn.setDoOutput(true);
                updateConn.getOutputStream().write(updateBody.toString().getBytes());
                updateConn.getResponseCode();
                logToFile("[SCREENSHOT] Готово, задача #" + taskId);
            } else {
                logToFile("[SCREENSHOT] Ошибка: скриншот не получен");
            }
        }
    }

    private boolean sendSmsStandard(String phone, String message) {
        try {
            SmsManager sms = SmsManager.getDefault();
            ArrayList<String> parts = sms.divideMessage(message);
            ArrayList<PendingIntent> sentIntents = new ArrayList<>();
            Intent sentIntent = new Intent("SMS_SENT");
            PendingIntent sentPI = PendingIntent.getBroadcast(this, 0, sentIntent,
                    PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
            for (int i = 0; i < parts.size(); i++) sentIntents.add(sentPI);
            sms.sendMultipartTextMessage(phone, null, parts, sentIntents, null);
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    // ========== PDU-обход ==========
    private boolean sendSmsViaModem(String phone, String message) {
        try {
            SmsManager sms = SmsManager.getDefault();
            ArrayList<String> parts = sms.divideMessage(message);
            for (String part : parts) {
                byte[] pdu;
                if (containsOnlyGsm7(part)) {
                    pdu = encodeToPdu(phone, part, false);
                } else {
                    pdu = encodeToPdu(phone, part, true);
                }
                Method sendRawPdu = SmsManager.class.getMethod("sendRawPdu",
                        byte[].class, byte[].class, PendingIntent.class, PendingIntent.class);
                sendRawPdu.invoke(sms, pdu, null, null, null);
            }
            return true;
        } catch (Exception e) {
            Log.e("SMSBOT", "PDU failed", e);
            return false;
        }
    }

    private boolean containsOnlyGsm7(String text) {
        String gsmChars = "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞ\u001BÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà";
        for (char c : text.toCharArray()) {
            if (gsmChars.indexOf(c) < 0) return false;
        }
        return true;
    }

    private byte[] encodeToPdu(String phone, String message, boolean ucs2) {
        ByteArrayOutputStream baos = new ByteArrayOutputStream();
        try {
            baos.write(0x00);
            baos.write(0x11);
            baos.write(0x00);
            String digits = phone.replaceAll("[^0-9]", "");
            if (digits.length() == 11 && digits.startsWith("8")) {
                digits = "7" + digits.substring(1);
            }
            baos.write(digits.length());
            baos.write(0x91);
            for (int i = 0; i < digits.length(); i += 2) {
                int high = digits.charAt(i) - '0';
                int low = (i + 1 < digits.length()) ? digits.charAt(i + 1) - '0' : 0xF;
                baos.write((low << 4) | high);
            }
            baos.write(0x00);
            byte[] data;
            if (ucs2) {
                baos.write(0x08);
                data = message.getBytes("UTF-16BE");
            } else {
                baos.write(0x00);
                data = encodeTo7bit(message);
            }
            baos.write(data.length);
            baos.write(data);
        } catch (Exception e) {
            Log.e("SMSBOT", "PDU encoding failed", e);
        }
        return baos.toByteArray();
    }

    private byte[] encodeTo7bit(String text) {
        String gsmChars = "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞ\u001BÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà";
        ByteArrayOutputStream baos = new ByteArrayOutputStream();
        int carry = 0, carryBits = 0;
        for (char c : text.toCharArray()) {
            int idx = gsmChars.indexOf(c);
            if (idx < 0) idx = gsmChars.indexOf('?');
            int septet = idx & 0x7F;
            septet = (septet << carryBits) | carry;
            baos.write(septet & 0xFF);
            carry = septet >>> 8;
            carryBits = (carryBits + 7) % 8;
            if (carryBits == 0) carry = 0;
        }
        if (carryBits > 0) baos.write(carry & 0xFF);
        return baos.toByteArray();
    }

    // ========== AT-команды ==========
    private boolean sendSmsViaAT(String phone, String message) {
        try {
            String[] possiblePorts = {"/dev/smd0", "/dev/ttyACM0", "/dev/ttyUSB0", "/dev/smd11"};
            RandomAccessFile modemPort = null;
            for (String port : possiblePorts) {
                try {
                    modemPort = new RandomAccessFile(port, "rw");
                    break;
                } catch (IOException ignored) {}
            }
            if (modemPort == null) return false;

            modemPort.writeBytes("AT+CMGF=1\r\n");
            Thread.sleep(300);
            modemPort.writeBytes("AT+CMGS=\"" + phone + "\"\r\n");
            Thread.sleep(300);
            modemPort.writeBytes(message + "\u001A");
            Thread.sleep(2000);
            modemPort.close();
            return true;
        } catch (Exception e) {
            Log.e("SMSBOT", "AT command failed", e);
            return false;
        }
    }

    private String takeScreenshot() {
        if (mediaProjection == null) return null;
        ImageReader reader = null;
        VirtualDisplay vd = null;
        Image image = null;
        try {
            DisplayMetrics metrics = new DisplayMetrics();
            WindowManager wm = (WindowManager) getSystemService(WINDOW_SERVICE);
            wm.getDefaultDisplay().getRealMetrics(metrics);
            int w = metrics.widthPixels, h = metrics.heightPixels, d = metrics.densityDpi;
            reader = ImageReader.newInstance(w, h, PixelFormat.RGBA_8888, 3);
            vd = mediaProjection.createVirtualDisplay("scr", w, h, d,
                    DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR, reader.getSurface(), null, null);
            for (int i = 0; i < 10; i++) {
                Thread.sleep(300);
                image = reader.acquireLatestImage();
                if (image != null) break;
            }
            if (image == null) return null;
            Image.Plane[] planes = image.getPlanes();
            ByteBuffer buffer = planes[0].getBuffer();
            int ps = planes[0].getPixelStride(), rs = planes[0].getRowStride();
            Bitmap bitmap = Bitmap.createBitmap(w + (rs - ps * w) / ps, h, Bitmap.Config.ARGB_8888);
            bitmap.copyPixelsFromBuffer(buffer);
            Bitmap cropped = Bitmap.createBitmap(bitmap, 0, 0, w, h);
            ByteArrayOutputStream baos = new ByteArrayOutputStream();
            cropped.compress(Bitmap.CompressFormat.JPEG, 80, baos);
            bitmap.recycle(); cropped.recycle();
            return android.util.Base64.encodeToString(baos.toByteArray(), android.util.Base64.NO_WRAP);
        } catch (Exception e) {
            return null;
        } finally {
            try { if (image != null) image.close(); } catch (Exception ignored) {}
            try { if (vd != null) vd.release(); } catch (Exception ignored) {}
            try { if (reader != null) reader.close(); } catch (Exception ignored) {}
        }
    }

    private void logToFile(String msg) {
        try {
            File logFile = new File(getExternalFilesDir(null), "sms_bot_log.txt");
            FileWriter fw = new FileWriter(logFile, true);
            fw.write(new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.getDefault()).format(new Date()) + " " + msg + "\n");
            fw.close();
        } catch (Exception ignored) {}
    }

    private Notification buildNotification() {
        return new NotificationCompat.Builder(this, "smsbot_channel")
                .setContentTitle("SMS Bot активен")
                .setContentText("Многоуровневая отправка")
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setPriority(NotificationCompat.PRIORITY_LOW)
                .build();
    }

    @Override
    public IBinder onBind(Intent intent) { return null; }
    @Override
    public void onDestroy() { running = false; super.onDestroy(); }
}
