package com.gathin.tvhome;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.os.Bundle;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import org.json.JSONObject;
import java.io.InputStream;
import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;

/** User opens this screen locally, selects a pairing file, and checks the pinned key. */
public class RemotePairingActivity extends Activity {
    private TextView status;
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout layout = new LinearLayout(this); layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(48, 24, 48, 24);
        status = new TextView(this);
        status.setText("Remote prototype: " + (RemotePairing.enabled(this) ? "enabled" : "disabled")
                + "\nOnly signed tasks: status, app list, layout, uploaded JPG/PNG or existing wallpaper, restore. APK install is disabled.");
        layout.addView(status);
        Button pair = new Button(this); pair.setText("Import pairing file and review");
        pair.setOnClickListener(v -> startActivityForResult(new Intent(Intent.ACTION_OPEN_DOCUMENT)
                .addCategory(Intent.CATEGORY_OPENABLE).setType("application/json"), 1));
        layout.addView(pair);
        Button stop = new Button(this); stop.setText("Revoke local access / stop");
        stop.setOnClickListener(v -> {
            RemotePairing.enabled(this, false);
            stopService(new Intent(this, RemoteTaskService.class));
            ((android.app.job.JobScheduler) getSystemService(JOB_SCHEDULER_SERVICE)).cancel(RemoteWatchdog.JOB);
            status.setText("Disabled. Rotate broker device token to revoke it on the server too.");
        });
        layout.addView(stop);
        Button resume = new Button(this); resume.setText("Resume previously paired agent");
        resume.setOnClickListener(v -> {
            try { RemotePairing.load(this); activate(); } catch (Exception e) { status.setText("Pairing missing or invalid"); }
        });
        layout.addView(resume); setContentView(layout);
    }
    private void activate() {
        RemotePairing.enabled(this, true);
        try {
            startForegroundService(new Intent(this, RemoteTaskService.class));
            RemoteWatchdog.schedule(this);
        } catch (RuntimeException e) {
            RemotePairing.enabled(this, false);
            throw e;
        }
        status.setText("Enabled. Notification shows connectivity. Task results are stored in the broker.");
    }
    @Override public void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request != 1 || result != RESULT_OK || data == null || data.getData() == null) return;
        try (InputStream in = getContentResolver().openInputStream(data.getData())) {
            ByteArrayOutputStream out = new ByteArrayOutputStream(); byte[] buf = new byte[1024]; int n;
            while ((n = in.read(buf)) != -1) { out.write(buf, 0, n); if (out.size() > 16384) throw new IllegalArgumentException(); }
            JSONObject c = new JSONObject(new String(out.toByteArray(), StandardCharsets.UTF_8)); RemotePairing.validate(c);
            new AlertDialog.Builder(this).setTitle("Authorize this controller?")
                    .setMessage("Device: " + c.getString("device") + "\nBroker: " + c.getString("broker")
                            + "\nRSA SHA-256: " + RemotePairing.fingerprint(c)
                            + "\nCompare this fingerprint with your trusted controller. Authorizes signed JPG/PNG wallpaper uploads. No APK installation or shell access.")
                    .setNegativeButton("Cancel", null).setPositiveButton("Authorize", (d, which) -> {
                        try {
                            // Stop old worker before replacing credentials. Activation uses a fresh service.
                            RemotePairing.enabled(this, false); stopService(new Intent(this, RemoteTaskService.class));
                            RemotePairing.save(this, c); activate();
                        } catch (Exception e) { status.setText("Could not save pairing; access remains disabled"); }
                    }).show();
        } catch (Exception e) { status.setText("Invalid pairing file"); }
    }
}
