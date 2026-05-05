btnSave.setOnClickListener(v -> {
    String token = etToken.getText().toString().trim();
    if (token.isEmpty()) return;
    prefs.edit().putString("bot_token", token).apply();
    Intent serviceIntent = new Intent(this, SmsBotService.class);
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
        startForegroundService(serviceIntent);
    } else {
        startService(serviceIntent);
    }
    Toast.makeText(this, "Запущено", Toast.LENGTH_SHORT).show();
});
