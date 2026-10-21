package com.gathin.tvhome;

import android.content.Context;
import android.content.SharedPreferences;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.os.SystemClock;
import android.util.AtomicFile;
import org.json.JSONObject;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.URL;
import java.security.MessageDigest;
import javax.net.ssl.HttpsURLConnection;

/** No task URL, no external storage, no redirects, no active wallpaper overwrite. */
final class RemoteWallpaper {
    static void validate(JSONObject a) throws Exception {
        RemoteTasks.exact(a, "sha256", "bytes", "width", "height", "mime");
        if (!(a.get("sha256") instanceof String) || !a.getString("sha256").matches("[0-9a-f]{64}"))
            throw new IllegalArgumentException("hash");
        long size = RemoteTasks.integer(a, "bytes"), w = RemoteTasks.integer(a, "width"), h = RemoteTasks.integer(a, "height");
        if (size < 1 || size > 8 * 1024 * 1024 || w < 1 || w > 4096 || h < 1 || h > 4096 || w * h > 8388608
                || !(a.get("mime") instanceof String) || !("image/jpeg".equals(a.getString("mime")) || "image/png".equals(a.getString("mime"))))
            throw new IllegalArgumentException("image limits");
    }
    private static String hex(byte[] bytes) {
        StringBuilder out = new StringBuilder();
        for (byte b : bytes) out.append(String.format(java.util.Locale.ROOT, "%02x", b & 255));
        return out.toString();
    }
    private static String hash(File file) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream in = new FileInputStream(file)) {
            byte[] bytes = new byte[8192]; int n;
            while ((n = in.read(bytes)) != -1) digest.update(bytes, 0, n);
        }
        return hex(digest.digest());
    }
    static File download(Context c, JSONObject pairing, JSONObject task) throws Exception {
        JSONObject a = task.getJSONObject("args"); validate(a);
        File dir = new File(c.getFilesDir(), "remote-wallpapers");
        if (!dir.isDirectory() && !dir.mkdirs()) throw new IllegalStateException("image storage");
        String name = "remote-" + a.getString("sha256") + (a.getString("mime").equals("image/png") ? ".png" : ".jpg");
        File file = new File(dir, name);
        if (file.isFile() && file.length() == a.getLong("bytes") && hash(file).equals(a.getString("sha256"))) {
            decodeCheck(file, a); return file;
        }
        // Bound retained private images; never delete the owner's existing wallpapers automatically.
        long total = 0; File[] retained = dir.listFiles();
        if (retained != null) for (File f : retained) total += f.length();
        if (total + a.getLong("bytes") > 128 * 1024 * 1024L) throw new IllegalStateException("local wallpaper quota");
        String base = pairing.getString("broker").replaceAll("/$", "");
        HttpsURLConnection conn = (HttpsURLConnection) new URL(base + "/v1/devices/" + pairing.getString("device")
                + "/assets/" + a.getString("sha256")).openConnection();
        conn.setConnectTimeout(10000); conn.setReadTimeout(10000); conn.setInstanceFollowRedirects(false);
        conn.setRequestProperty("Authorization", "Bearer " + pairing.getString("token"));
        AtomicFile atomic = new AtomicFile(file); FileOutputStream out = null;
        try {
            if (conn.getResponseCode() != 200 || !a.getString("mime").equals(conn.getContentType())) throw new IllegalStateException("image HTTP");
            int advertised = conn.getContentLength();
            if (advertised != -1 && advertised != a.getInt("bytes")) throw new IllegalArgumentException("image length");
            out = atomic.startWrite(); MessageDigest digest = MessageDigest.getInstance("SHA-256");
            long start = SystemClock.elapsedRealtime(); int count = 0;
            try (InputStream in = conn.getInputStream()) {
                byte[] buffer = new byte[8192]; int n;
                while ((n = in.read(buffer)) != -1) {
                    if (Thread.currentThread().isInterrupted() || !RemotePairing.enabled(c)) throw new IllegalStateException("revoked");
                    count += n;
                    if (count > a.getInt("bytes") || SystemClock.elapsedRealtime() - start > 60000) throw new IllegalArgumentException("image transfer limit");
                    out.write(buffer, 0, n); digest.update(buffer, 0, n);
                }
            }
            if (count != a.getInt("bytes") || !hex(digest.digest()).equals(a.getString("sha256"))) throw new IllegalArgumentException("image integrity");
            atomic.finishWrite(out); out = null;
            decodeCheck(file, a);
            return file;
        } finally {
            if (out != null) atomic.failWrite(out);
            conn.disconnect();
        }
    }
    private static void decodeCheck(File f, JSONObject a) throws Exception {
        BitmapFactory.Options options = new BitmapFactory.Options(); options.inJustDecodeBounds = true;
        BitmapFactory.decodeFile(f.getPath(), options);
        if (options.outWidth != a.getInt("width") || options.outHeight != a.getInt("height") || !a.getString("mime").equals(options.outMimeType))
            throw new IllegalArgumentException("decoded image metadata");
        options.inJustDecodeBounds = false; options.inSampleSize = 1;
        while (options.outWidth / options.inSampleSize > 1920 || options.outHeight / options.inSampleSize > 1080) options.inSampleSize *= 2;
        options.inPreferredConfig = Bitmap.Config.RGB_565;
        try {
            Bitmap bitmap = BitmapFactory.decodeFile(f.getPath(), options);
            if (bitmap == null) throw new IllegalArgumentException("image decoder refused bytes");
            bitmap.recycle();
        } catch (OutOfMemoryError e) { throw new IllegalStateException("image memory limit", e); }
    }
    static JSONObject evidence(Context c, JSONObject task, File file) throws Exception {
        SharedPreferences p = c.getSharedPreferences("remote_render_state", Context.MODE_PRIVATE);
        long deadline = SystemClock.elapsedRealtime() + 75000;
        boolean visible = false;
        while (SystemClock.elapsedRealtime() < deadline && RemotePairing.enabled(c)) {
            visible = task.getString("id").equals(p.getString("revision", "")) && file.getName().equals(p.getString("file", ""));
            if (visible) break;
            Thread.sleep(500);
        }
        return new JSONObject().put("applied", true).put("wallpaper_sha256", task.getJSONObject("args").getString("sha256"))
                .put("display_confirmed", visible).put("evidence", visible ? "image_view_pre_draw" : "applied_waiting_for_home")
                .put("revision", task.getString("id")).put("sdk", android.os.Build.VERSION.SDK_INT).put("model", android.os.Build.MODEL);
    }
}
