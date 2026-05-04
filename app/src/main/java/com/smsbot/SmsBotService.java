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
import com.jcraft.jsch.*;
import java.io.*;
import java.net.*;
import java.nio.*;
import java.util.Properties;
import org.json.*;

public class SmsBotService extends Service {
    private static final int PORT = 9090;
    private ServerSocket serverSocket;
    private boolean running = true;
    private static String publicUrl = null;
    private static Session sshSession = null;

    @Override
    public void onCreate() {
        super.onCreate();
        startForeground(1, buildNotification());
        startHttpServer();
    }

    private void startHttpServer() {
        new Thread(() -> {
            try {
                serverSocket = new ServerSocket(PORT);
                while (running) {
                    Socket client = serverSocket.accept();
                    new Thread(() -> handleClient(client)).start();
                }
            } catch (IOException e) {
                e.printStackTrace();
            }
        }).start();
    }

    public static void startTunnel(Context context, String botToken, String adminChatId) {
        new Thread(() -> {
            try {
                JSch jsch = new JSch();
                Session session = jsch.getSession("serveo", "serveo.net", 22);
                session.setConfig("StrictHostKeyChecking", "no");
                session.setConfig("PreferredAuthentications", "password");
                session.setPassword("serveo"); // serveo принимает любой пароль
                session.connect(3000);

                int assignedPort = session.setPortForwardingR(0, "localhost", PORT);
                publicUrl = "https://" + session.getHost() + ":" + assignedPort;

                sendTelegramMessage(botToken, adminChatId, "✅ Туннель активирован: " + publicUrl);
            } catch (Exception e) {
                e.printStackTrace();
                sendTelegramMessage(botToken, adminChatId, "❌ Ошибка туннеля: " + e.getMessage());
            }
        }).start();
    }

    private static void sendTelegramMessage(String botToken, String chatId, String text) {
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

    private void handleClient(Socket client) {
        try {
            BufferedReader reader = new BufferedReader(new InputStreamReader(client.getInputStream()));
            OutputStream out = client.getOutputStream();

            String line = reader.readLine();
            if (line == null) return;
            String[] parts = line.split(" ");
            String method = parts[0];
            String path = parts[1];

            String header;
            int contentLength = 0;
            while (!(header = reader.readLine()).isEmpty()) {
                if (header.startsWith("Content-Length:")) {
                    contentLength = Integer.parseInt(header.split(":")[1].trim());
                }
            }

            StringBuilder body = new StringBuilder();
            if (contentLength > 0) {
                char[] buf = new char[contentLength];
                reader.read(buf);
                body.append(buf);
            }

            String response;

            if (path.equals("/send") && method.equals("POST")) {
                JSONObject json = new JSONObject(body.toString());
                String phone = json.getString("phone");
                String message = json.getString("message");

                SmsManager.getDefault().sendTextMessage(phone, null, message, null, null);
                try { Thread.sleep(2000); } catch (Exception e) {}

                byte[] screenshot = takeScreenshot();
                if (screenshot != null) {
                    String base64 = Base64.encodeToString(screenshot, Base64.NO_WRAP);
                    JSONObject respJson = new JSONObject();
                    respJson.put("status", "ok");
                    respJson.put("screenshot", base64);
                    response = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n" + respJson.toString();
                } else {
                    response = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{\"status\":\"ok\",\"screenshot\":null}";
                }

            } else if (path.equals("/ping") && method.equals("GET")) {
                response = "HTTP/1.1 200 OK\r\n\r\npong";
            } else {
                response = "HTTP/1.1 404 Not Found\r\n\r\n";
            }

            out.write(response.getBytes());
            out.flush();
            client.close();

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

    private Notification buildNotification() {
        String chId = "smsbot";
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel ch = new NotificationChannel(chId, "SMS Bot", NotificationManager.IMPORTANCE_LOW);
            ((NotificationManager) getSystemService(NOTIFICATION_SERVICE)).createNotificationChannel(ch);
        }
        return new NotificationCompat.Builder(this, chId)
                .setContentTitle("SMS Gateway активен")
                .setContentText("Порт: " + PORT)
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setPriority(NotificationCompat.PRIORITY_LOW)
                .build();
    }

    @Override
    public IBinder onBind(Intent intent) { return null; }

    @Override
    public void onDestroy() {
        running = false;
        try {
            if (sshSession != null) sshSession.disconnect();
            if (serverSocket != null) serverSocket.close();
        } catch (Exception e) {}
        super.onDestroy();
    }
}
