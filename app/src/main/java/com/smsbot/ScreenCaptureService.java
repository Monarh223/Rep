package com.smsbot;

import android.accessibilityservice.AccessibilityService;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.view.accessibility.AccessibilityEvent;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;

public class ScreenCaptureService extends AccessibilityService {
    public static ScreenCaptureService instance;

    @Override
    public void onServiceConnected() {
        instance = this;
    }

    public byte[] takeScreenshot() {
        // Способ 1: screencap
        try {
            File screenshotFile = new File(getExternalFilesDir(null), "screenshot.png");
            Process process = Runtime.getRuntime().exec(new String[]{
                    "sh", "-c", "screencap -p " + screenshotFile.getAbsolutePath()
            });
            process.waitFor();

            if (screenshotFile.exists()) {
                FileInputStream fis = new FileInputStream(screenshotFile);
                Bitmap bitmap = BitmapFactory.decodeStream(fis);
                fis.close();
                screenshotFile.delete();

                if (bitmap != null) {
                    ByteArrayOutputStream baos = new ByteArrayOutputStream();
                    bitmap.compress(Bitmap.CompressFormat.JPEG, 80, baos);
                    bitmap.recycle();
                    return baos.toByteArray();
                }
            }
        } catch (Exception e) {
            e.printStackTrace();
        }
        return null;
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {}

    @Override
    public void onInterrupt() {}
}
