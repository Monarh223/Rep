package com.smsbot;

import android.app.Activity;
import android.content.*;
import android.media.projection.*;
import android.os.*;
import android.widget.*;
import android.view.View;

public class MainActivity extends Activity {
    private static final int REQUEST_CODE = 123;
    private MediaProjectionManager mpManager;
    public static MediaProjection mediaProjection;
    private SmsBotService botService;
    private boolean bound = false;

    private ServiceConnection connection = new ServiceConnection() {
        @Override
        public void onServiceConnected(ComponentName name, IBinder binder) {
            SmsBotService.LocalBinder localBinder = (SmsBotService.LocalBinder) binder;
            botService = localBinder.getService();
            bound = true;
        }
        @Override
        public void onServiceDisconnected(ComponentName name) {
            bound = false;
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        mpManager = (MediaProjectionManager) getSystemService(MEDIA_PROJECTION_SERVICE);
        Button btnScreenshot = findViewById(R.id.btnScreenshot);
        Button btnActivate = findViewById(R.id.btnActivate);
        EditText etChatId = findViewById(R.id.etChatId);
        TextView tvStatus = findViewById(R.id.tvStatus);

        Intent serviceIntent = new Intent(this, SmsBotService.class);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(serviceIntent);
        } else {
            startService(serviceIntent);
        }
        bindService(serviceIntent, connection, Context.BIND_AUTO_CREATE);

        btnScreenshot.setOnClickListener(v -> {
            Intent intent = mpManager.createScreenCaptureIntent();
            startActivityForResult(intent, REQUEST_CODE);
        });

        btnActivate.setOnClickListener(v -> {
            String chatId = etChatId.getText().toString().trim();
            if (!chatId.isEmpty() && bound && botService != null) {
                botService.setPhoneChatId(chatId);
                tvStatus.setText("✅ Активирован. Chat ID: " + chatId);
                tvStatus.setVisibility(View.VISIBLE);
            }
        });
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQUEST_CODE && resultCode == RESULT_OK) {
            mediaProjection = mpManager.getMediaProjection(resultCode, data);
            Toast.makeText(this, "Скриншоты разрешены", Toast.LENGTH_SHORT).show();
        }
    }

    @Override
    protected void onDestroy() {
        if (bound) unbindService(connection);
        super.onDestroy();
    }
}
