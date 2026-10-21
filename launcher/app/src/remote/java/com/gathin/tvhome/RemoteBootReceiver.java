package com.gathin.tvhome;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

public class RemoteBootReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context c, Intent intent) {
        if (Intent.ACTION_BOOT_COMPLETED.equals(intent.getAction()) && RemotePairing.enabled(c)) {
            c.startForegroundService(new Intent(c, RemoteTaskService.class)); RemoteWatchdog.schedule(c);
        }
    }
}
