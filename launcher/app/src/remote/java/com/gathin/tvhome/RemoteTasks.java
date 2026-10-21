package com.gathin.tvhome;

import android.content.Context;
import android.content.SharedPreferences;
import android.content.pm.PackageInfo;
import android.os.Build;
import android.util.AtomicFile;
import java.util.Base64;
import org.json.JSONObject;
import org.json.JSONArray;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.security.Signature;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Iterator;
import java.util.Set;

/** Device independently verifies signatures, strict schema, TTL and allowlist. */
final class RemoteTasks {
    static final String REVISION = "remote_desktop_revision";
    static void exact(JSONObject o, String... names) throws Exception {
        Set<String> actual = new HashSet<>(); Iterator<String> keys = o.keys();
        while (keys.hasNext()) actual.add(keys.next());
        if (!actual.equals(new HashSet<>(Arrays.asList(names)))) throw new IllegalArgumentException("fields");
    }
    static long integer(JSONObject o, String key) throws Exception {
        Object v = o.get(key);
        if (!(v instanceof Integer || v instanceof Long)) throw new IllegalArgumentException("integer required");
        return ((Number) v).longValue();
    }
    static JSONObject verify(JSONObject e, JSONObject pairing) throws Exception {
        exact(e, "payload", "signature");
        byte[] payload = Base64.getDecoder().decode(e.getString("payload"));
        byte[] sig = Base64.getDecoder().decode(e.getString("signature"));
        if (payload.length > 16384 || sig.length < 256 || sig.length > 512) throw new IllegalArgumentException("size");
        Signature verifier = Signature.getInstance("SHA256withRSA");
        verifier.initVerify(RemotePairing.publicKey(pairing)); verifier.update(payload);
        if (!verifier.verify(sig)) throw new IllegalArgumentException("signature");
        JSONObject t = new JSONObject(new String(payload, StandardCharsets.UTF_8));
        exact(t, "v", "id", "device", "issued_at", "expires_at", "op", "args");
        long now = System.currentTimeMillis() / 1000, issued = integer(t, "issued_at"), expires = integer(t, "expires_at");
        if (integer(t, "v") != 1 || !t.getString("device").equals(pairing.getString("device"))
                || !t.getString("id").matches("[A-Za-z0-9_-]{1,64}") || issued < now - 3600 || issued > now + 60
                || expires <= now || expires <= issued || expires - issued > 3600) throw new IllegalArgumentException("task binding or expiry");
        JSONObject a = t.getJSONObject("args");
        switch (t.getString("op")) {
            case "apply_wallpaper": RemoteWallpaper.validate(a); break;
            case "status": case "list_apps": case "restore_desktop": exact(a); break;
            case "set_layout":
                exact(a, "columns", "rows_below_dock");
                long columns = integer(a, "columns"), rows = integer(a, "rows_below_dock");
                if (columns < 4 || columns > 7 || rows < 0 || rows > 3) throw new IllegalArgumentException("layout");
                break;
            case "set_wallpaper":
                exact(a, "asset");
                if (!a.getString("asset").matches("[A-Za-z0-9_-]{1,48}\\.(jpg|jpeg|png|webp)")) throw new IllegalArgumentException("asset");
                break;
            default: throw new IllegalArgumentException("operation disabled");
        }
        return t;
    }
    private static final String[] MANAGED = {"columns", Config.ROWS_BELOW_DOCK_KEY, Config.WALLPAPER_CHOICE_KEY};
    private static AtomicFile snapshot(Context c) { return new AtomicFile(new File(c.getFilesDir(), "remote-desktop-before.json")); }
    private static void backup(Context c) throws Exception {
        AtomicFile af = snapshot(c);
        if (af.getBaseFile().exists()) return; // Preserve the baseline until restored locally/reviewed.
        SharedPreferences p = c.getSharedPreferences(Config.SETTINGS_NAME, 0); JSONObject s = new JSONObject();
        for (String k : MANAGED) if (p.contains(k)) s.put(k, p.getAll().get(k));
        FileOutputStream out = af.startWrite();
        try { out.write(s.toString().getBytes(StandardCharsets.UTF_8)); af.finishWrite(out); }
        catch (Exception e) { af.failWrite(out); throw e; }
    }
    static JSONObject execute(Context c, JSONObject task, JSONObject pairing) throws Exception {
        String op = task.getString("op"); JSONObject a = task.getJSONObject("args");
        File uploaded = op.equals("apply_wallpaper") ? RemoteWallpaper.download(c, pairing, task) : null;
        if (integer(task, "expires_at") <= System.currentTimeMillis() / 1000) throw new IllegalArgumentException("task expired before apply");
        if (!RemotePairing.enabled(c)) throw new IllegalStateException("revoked");
        switch (op) {
            case "status": return new JSONObject().put("sdk", Build.VERSION.SDK_INT).put("model", Build.MODEL)
                    .put("display_revision", c.getSharedPreferences("remote_render_state", 0).getString("revision", ""))
                    .put("display_file", c.getSharedPreferences("remote_render_state", 0).getString("file", ""))
                    .put("apk_install", "disabled").put("arbitrary_shell", "disabled");
            case "list_apps":
                JSONArray apps = new JSONArray();
                // Bound result size. This is inventory only; no launch/uninstall/disable operation.
                for (PackageInfo p : c.getPackageManager().getInstalledPackages(0)) {
                    if (apps.length() == 60) break;
                    apps.put(p.packageName);
                }
                return new JSONObject().put("packages", apps).put("limit", 60).put("possibly_truncated", apps.length() == 60);
            case "set_layout": case "set_wallpaper": case "apply_wallpaper": case "restore_desktop":
                Config.load(c); // Synchronize existing theme choices before snapshot/apply.
                SharedPreferences.Editor edit = c.getSharedPreferences(Config.SETTINGS_NAME, 0).edit();
                if (op.equals("restore_desktop")) {
                    JSONObject before = new JSONObject(new String(snapshot(c).readFully(), StandardCharsets.UTF_8));
                    for (String k : MANAGED) {
                        edit.remove(k);
                        if (before.has(k)) {
                            if (k.equals(Config.WALLPAPER_CHOICE_KEY)) edit.putString(k, before.getString(k));
                            else edit.putInt(k, before.getInt(k));
                        }
                    }
                } else {
                    if (uploaded != null) {
                        backup(c); edit.putString(Config.WALLPAPER_CHOICE_KEY, uploaded.getName());
                    } else if (op.equals("set_wallpaper")) {
                        File dir = Config.dir(c);
                        if (dir == null) throw new IllegalStateException("no theme storage");
                        File collection = new File(dir, "wallpapers"); File image = new File(collection, a.getString("asset"));
                        if (!image.getCanonicalFile().getParentFile().equals(collection.getCanonicalFile())
                                || !image.isFile() || image.length() == 0 || image.length() > 8 * 1024 * 1024)
                            throw new IllegalArgumentException("wallpaper must be pre-staged locally");
                        backup(c); edit.putString(Config.WALLPAPER_CHOICE_KEY, a.getString("asset"));
                    } else {
                        backup(c); edit.putInt("columns", a.getInt("columns"))
                                .putInt(Config.ROWS_BELOW_DOCK_KEY, a.getInt("rows_below_dock"));
                    }
                }
                // Revision and settings commit together; MainActivity observes it without an exported IPC.
                edit.putString(REVISION, task.getString("id"));
                if (!edit.commit()) throw new IllegalStateException("preferences commit failed");
                if (uploaded != null) return RemoteWallpaper.evidence(c, task, uploaded);
                return new JSONObject().put("applied", true).put("visible", "on Home resume or next minute tick");
            default: throw new IllegalArgumentException("operation disabled");
        }
    }
}
