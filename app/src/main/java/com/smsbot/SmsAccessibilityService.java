package com.smsbot;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.AccessibilityServiceInfo;
import android.content.Intent;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.view.accessibility.AccessibilityEvent;

public class SmsAccessibilityService extends AccessibilityService {
    private static SmsAccessibilityService instance;
    private Handler handler = new Handler(Looper.getMainLooper());

    public static SmsAccessibilityService getInstance() {
        return instance;
    }

    @Override
    public void onServiceConnected() {
        super.onServiceConnected();
        instance = this;
        AccessibilityServiceInfo info = new AccessibilityServiceInfo();
        info.eventTypes = AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED | AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED;
        info.feedbackType = AccessibilityServiceInfo.FEEDBACK_GENERIC;
        info.notificationTimeout = 500;
        info.packageNames = new String[]{
                "com.google.android.apps.messaging",
                "com.android.mms",
                "com.samsung.android.messaging"
        };
        setServiceInfo(info);
    }

    public void openSmsDialog(String phone) {
        handler.post(() -> {
            try {
                Intent intent = new Intent(Intent.ACTION_SENDTO);
                intent.setData(Uri.parse("smsto:" + Uri.encode(phone)));
                intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                startActivity(intent);
            } catch (Exception e) {
                Log.e("SMS_ACCESS", "Cannot open SMS app", e);
            }
        });
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        // Ничего не делаем, скриншот через MediaProjection
    }

    @Override
    public void onInterrupt() {}
}
