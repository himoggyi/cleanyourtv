package com.gathin.tvhome;

import android.content.Context;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.AtomicFile;
import android.util.Base64;
import org.json.JSONObject;
import java.io.File;
import java.io.FileOutputStream;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.security.MessageDigest;
import java.security.KeyFactory;
import java.security.PublicKey;
import java.security.interfaces.RSAPublicKey;
import java.security.spec.X509EncodedKeySpec;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** Pairing is only imported by a local, visible confirmation screen. No remote configuration API. */
final class RemotePairing {
    private static final String ALIAS = "tvhome.remote.pairing.v1";
    static boolean enabled(Context c) {
        return c.getSharedPreferences("remote_enabled", 0).getBoolean("enabled", false);
    }
    static void enabled(Context c, boolean enabled) {
        if (!c.getSharedPreferences("remote_enabled", 0).edit().putBoolean("enabled", enabled).commit())
            throw new IllegalStateException("cannot save activation state");
    }
    static PublicKey publicKey(JSONObject c) throws Exception {
        String pem = c.getString("public_key").replace("-----BEGIN PUBLIC KEY-----", "")
                .replace("-----END PUBLIC KEY-----", "").replaceAll("\\s", "");
        PublicKey k = KeyFactory.getInstance("RSA").generatePublic(new X509EncodedKeySpec(java.util.Base64.getDecoder().decode(pem)));
        int bits = ((RSAPublicKey) k).getModulus().bitLength();
        if (bits < 2048 || bits > 4096) throw new IllegalArgumentException("RSA key size");
        return k;
    }
    static void validate(JSONObject c) throws Exception {
        if (github(c)) RemoteTasks.exact(c, "device", "transport", "repository", "repository_id", "token", "public_key");
        else RemoteTasks.exact(c, "device", "broker", "token", "public_key");
        if (!c.getString("device").matches("[A-Za-z0-9_-]{1,64}")) throw new IllegalArgumentException("device");
        if (!c.getString("token").matches("[A-Za-z0-9_-]{32,256}")) throw new IllegalArgumentException("token");
        if (github(c)) {
            if (!RemoteGitHub.REPOSITORY.equals(c.getString("repository"))
                    || RemoteTasks.integer(c, "repository_id") != RemoteGitHub.REPOSITORY_ID
                    || "cloud-probe".equals(c.getString("device"))) throw new IllegalArgumentException("repository/device");
            publicKey(c); return;
        }
        URI u = new URI(c.getString("broker"));
        if (!"https".equals(u.getScheme()) || u.getHost() == null || u.getRawUserInfo() != null
                || u.getRawQuery() != null || u.getRawFragment() != null
                || !(u.getPath().isEmpty() || "/".equals(u.getPath()))) throw new IllegalArgumentException("HTTPS origin required");
        publicKey(c);
    }
    static boolean github(JSONObject c) { return "github-issues".equals(c.optString("transport")); }
    static String controller(JSONObject c) throws Exception {
        return github(c) ? "GitHub private: " + c.getString("repository") : c.getString("broker");
    }
    static String fingerprint(JSONObject c) throws Exception {
        byte[] hash = MessageDigest.getInstance("SHA-256").digest(publicKey(c).getEncoded());
        StringBuilder b = new StringBuilder();
        for (byte v : hash) b.append(String.format(java.util.Locale.ROOT, "%02x", v & 255));
        return b.toString();
    }
    private static SecretKey key() throws Exception {
        KeyStore ks = KeyStore.getInstance("AndroidKeyStore"); ks.load(null);
        if (ks.containsAlias(ALIAS)) return (SecretKey) ks.getKey(ALIAS, null);
        KeyGenerator gen = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        gen.init(new KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());
        return gen.generateKey();
    }
    private static AtomicFile file(Context c) { return new AtomicFile(new File(c.getFilesDir(), "remote-pairing.enc")); }
    static void save(Context c, JSONObject pairing) throws Exception {
        validate(pairing);
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding"); cipher.init(Cipher.ENCRYPT_MODE, key());
        JSONObject wrapper = new JSONObject().put("iv", Base64.encodeToString(cipher.getIV(), Base64.NO_WRAP))
                .put("data", Base64.encodeToString(cipher.doFinal(pairing.toString().getBytes(StandardCharsets.UTF_8)), Base64.NO_WRAP));
        AtomicFile af = file(c); FileOutputStream out = af.startWrite();
        try { out.write(wrapper.toString().getBytes(StandardCharsets.UTF_8)); af.finishWrite(out); }
        catch (Exception e) { af.failWrite(out); throw e; }
    }
    static JSONObject load(Context c) throws Exception {
        JSONObject w = new JSONObject(new String(file(c).readFully(), StandardCharsets.UTF_8));
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, Base64.decode(w.getString("iv"), Base64.DEFAULT)));
        JSONObject pairing = new JSONObject(new String(cipher.doFinal(Base64.decode(w.getString("data"), Base64.DEFAULT)), StandardCharsets.UTF_8));
        validate(pairing); return pairing;
    }
}
