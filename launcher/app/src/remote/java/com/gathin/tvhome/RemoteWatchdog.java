package com.gathin.tvhome;

import android.app.job.JobInfo;
import android.app.job.JobParameters;
import android.app.job.JobScheduler;
import android.app.job.JobService;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;

/** Android 9 recovery opportunity, subject to Doze and vendor restrictions; no uptime guarantee. */
public class RemoteWatchdog extends JobService {
    static final int JOB = 7602;
    static void schedule(Context c) {
        JobScheduler scheduler = (JobScheduler) c.getSystemService(Context.JOB_SCHEDULER_SERVICE);
        // Avoid resetting the periodic deadline on every service start.
        if (scheduler.getPendingJob(JOB) == null) scheduler.schedule(new JobInfo.Builder(JOB,
                new ComponentName(c, RemoteWatchdog.class)).setPeriodic(15 * 60 * 1000L).setPersisted(true)
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY).build());
    }
    @Override public boolean onStartJob(JobParameters params) {
        if (RemotePairing.enabled(this)) startForegroundService(new Intent(this, RemoteTaskService.class));
        return false;
    }
    @Override public boolean onStopJob(JobParameters params) { return true; }
}
