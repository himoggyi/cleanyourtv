package com.gathin.tvhome;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.os.IBinder;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.net.URL;
import javax.net.ssl.HttpsURLConnection;

/** Outbound HTTPS only. Durable claim before side effects; crash means unknown, never blind replay. */
public class RemoteTaskService extends Service {
    private volatile boolean running;
    private Thread worker;
    private SQLiteDatabase db;
    @Override public void onCreate() {
        super.onCreate();
        NotificationManager nm = getSystemService(NotificationManager.class);
        nm.createNotificationChannel(new NotificationChannel("remote", "Remote tasks", NotificationManager.IMPORTANCE_LOW));
        notification("Starting; APK installation disabled");
        db = openOrCreateDatabase("remote-journal.db", 0, null);
        db.execSQL("CREATE TABLE IF NOT EXISTS journal (id TEXT NOT NULL, device TEXT NOT NULL, result TEXT, sent INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(device,id))");
        // A null result means the process died after claiming. Never execute that ID again.
        db.execSQL("UPDATE journal SET result=? WHERE result IS NULL",
                new Object[]{"{\"status\":\"unknown\",\"data\":{\"reason\":\"process interrupted; inspect device before resubmitting\"}}"});
    }
    private void notification(String text) {
        Intent settings = new Intent(this, RemotePairingActivity.class);
        PendingIntent pi = PendingIntent.getActivity(this, 0, settings, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        Notification n = new Notification.Builder(this, "remote").setContentTitle("CleanYourTV remote prototype")
                .setContentText(text).setSmallIcon(android.R.drawable.stat_notify_sync).setContentIntent(pi).setOngoing(true).build();
        startForeground(7601, n);
    }
    @Override public synchronized int onStartCommand(Intent intent, int flags, int startId) {
        if (!RemotePairing.enabled(this)) { stopSelf(); return START_NOT_STICKY; }
        if (!running) {
            running = true; worker = new Thread(this::loop, "tvhome-remote"); worker.start();
            RemoteWatchdog.schedule(this);
        }
        return START_STICKY;
    }
    private JSONObject request(JSONObject c, String suffix, JSONObject body) throws Exception {
        String origin = c.getString("broker");
        if (origin.endsWith("/")) origin = origin.substring(0, origin.length() - 1);
        HttpsURLConnection conn = (HttpsURLConnection) new URL(origin + "/v1/devices/" + c.getString("device") + suffix).openConnection();
        conn.setConnectTimeout(10000); conn.setReadTimeout(10000); conn.setInstanceFollowRedirects(false);
        conn.setRequestProperty("Authorization", "Bearer " + c.getString("token"));
        try {
            if (body != null) {
                conn.setRequestMethod("POST"); conn.setDoOutput(true); conn.setRequestProperty("Content-Type", "application/json");
                byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8); conn.setFixedLengthStreamingMode(bytes.length);
                try (java.io.OutputStream out = conn.getOutputStream()) { out.write(bytes); }
            }
            if (conn.getResponseCode() != 200) throw new IllegalStateException("HTTP failure");
            try (InputStream in = conn.getInputStream()) {
                ByteArrayOutputStream out = new ByteArrayOutputStream(); byte[] buf = new byte[1024]; int n;
                while ((n = in.read(buf)) != -1) { out.write(buf, 0, n); if (out.size() > 16384) throw new IllegalArgumentException("response size"); }
                return new JSONObject(new String(out.toByteArray(), StandardCharsets.UTF_8));
            }
        } finally { conn.disconnect(); }
    }
    private void flush(JSONObject pairing) throws Exception {
        try (Cursor rows = db.rawQuery("SELECT id,result FROM journal WHERE sent=0 AND result IS NOT NULL AND device=?", new String[]{pairing.getString("device")})) {
            while (rows.moveToNext()) {
                request(pairing, "/results/" + rows.getString(0), new JSONObject(rows.getString(1)));
                db.execSQL("UPDATE journal SET sent=1 WHERE device=? AND id=?", new Object[]{pairing.getString("device"), rows.getString(0)});
            }
        }
    }
    private void poll(JSONObject pairing) throws Exception {
        flush(pairing);
        JSONObject response = request(pairing, "/next", null);
        if (response.isNull("task")) return;
        JSONObject task = RemoteTasks.verify(response.getJSONObject("task"), pairing);
        String id = task.getString("id");
        try (Cursor row = db.rawQuery("SELECT result FROM journal WHERE device=? AND id=?", new String[]{pairing.getString("device"), id})) {
            if (row.moveToFirst()) {
                // Broker may have lost its receipt. Re-send cached result, never repeat side effect.
                if (!row.isNull(0)) request(pairing, "/results/" + id, new JSONObject(row.getString(0)));
                return;
            }
        }
        db.execSQL("INSERT INTO journal(id,device) VALUES (?,?)", new Object[]{id, pairing.getString("device")});
        JSONObject result;
        try {
            if (!running || !RemotePairing.enabled(this)) throw new IllegalStateException("revoked");
            result = new JSONObject().put("status", "succeeded").put("data", RemoteTasks.execute(this, task));
        } catch (Exception e) {
            result = new JSONObject().put("status", "failed").put("data", new JSONObject().put("reason", "execution rejected or failed"));
        }
        db.execSQL("UPDATE journal SET result=? WHERE device=? AND id=?", new Object[]{result.toString(), pairing.getString("device"), id});
        flush(pairing);
    }
    private void loop() {
        long delay = 60000;
        try {
            while (running && RemotePairing.enabled(this)) {
                try {
                    poll(RemotePairing.load(this)); notification("Connected; polling every 60 seconds"); delay = 60000;
                } catch (Exception e) {
                    notification("Offline or task rejected; retrying safely"); delay = Math.min(delay * 2, 900000);
                }
                try { Thread.sleep(delay); } catch (InterruptedException e) { break; }
            }
        } finally { db.close(); }
    }
    @Override public synchronized void onDestroy() {
        running = false; if (worker != null) worker.interrupt(); else if (db != null) db.close();
        super.onDestroy();
    }
    @Override public IBinder onBind(Intent intent) { return null; }
}
