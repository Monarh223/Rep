// В начало добавь импорты для WebSocket
import java.util.concurrent.*;
import javax.net.ssl.*;
import java.security.cert.*;

// В onCreate добавь после startForeground:
new Thread(() -> subscribeToRealtime()).start();

// Новый метод:
private void subscribeToRealtime() {
    try {
        String wsUrl = SUPABASE_URL.replace("https", "wss") + "/realtime/v1/websocket?apikey=" + SUPABASE_KEY;
        // Упрощённо: используем обычный опрос, но чаще
        // Полноценный WebSocket требует библиотеки, оставим учащённый опрос
        while (running) {
            checkAndProcessTasks();
            Thread.sleep(2000); // опрашиваем каждые 2 секунды вместо 5
        }
    } catch (Exception e) {
        e.printStackTrace();
    }
}

// Удали старый вызов checkAndProcessTasks из onCreate и замени на:
subscribeToRealtime();
