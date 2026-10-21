package com.gathin.tvhome;

import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import javax.net.ssl.HttpsURLConnection;

/** Fixed private repository, pinned task key, status only; no GitHub redirects or arbitrary URL. */
final class RemoteGitHub {
    static final String REPOSITORY = "himoggyi/cleanyourtv-tasks";
    static final long REPOSITORY_ID = 1428876145L;
    private static final String API = "https://api.github.com/repos/" + REPOSITORY;
    static final class Entry {
        final JSONObject task; final long issue;
        Entry(JSONObject task, long issue) { this.task = task; this.issue = issue; }
    }
    private static String request(JSONObject pairing, String suffix, String method, JSONObject body) throws Exception {
        HttpsURLConnection conn = (HttpsURLConnection) new URL(API + suffix).openConnection();
        conn.setConnectTimeout(10000); conn.setReadTimeout(10000); conn.setInstanceFollowRedirects(false);
        conn.setRequestMethod(method);
        conn.setRequestProperty("Authorization", "Bearer " + pairing.getString("token"));
        conn.setRequestProperty("Accept", "application/vnd.github+json");
        conn.setRequestProperty("X-GitHub-Api-Version", "2022-11-28");
        conn.setRequestProperty("User-Agent", "CleanYourTV-Android9-status-prototype");
        try {
            if (body != null) {
                conn.setDoOutput(true); conn.setRequestProperty("Content-Type", "application/json");
                byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
                conn.setFixedLengthStreamingMode(bytes.length);
                try (java.io.OutputStream out = conn.getOutputStream()) { out.write(bytes); }
            }
            int status = conn.getResponseCode();
            if (status != 200 && !(method.equals("POST") && status == 201))
                throw new IllegalStateException("GitHub HTTP " + status);
            try (InputStream in = conn.getInputStream()) {
                ByteArrayOutputStream out = new ByteArrayOutputStream(); byte[] buf = new byte[4096]; int n;
                while ((n = in.read(buf)) != -1) {
                    out.write(buf, 0, n);
                    if (out.size() > 262144) throw new IllegalArgumentException("GitHub response limit");
                }
                return new String(out.toByteArray(), StandardCharsets.UTF_8);
            }
        } finally { conn.disconnect(); }
    }
    static void requirePrivate(JSONObject pairing) throws Exception {
        JSONObject repo = new JSONObject(request(pairing, "", "GET", null));
        if (RemoteTasks.integer(repo, "id") != REPOSITORY_ID || !Boolean.TRUE.equals(repo.get("private"))
                || !Boolean.TRUE.equals(repo.get("has_issues")) || !REPOSITORY.equals(repo.getString("full_name"))
                || RemoteTasks.integer(repo.getJSONObject("owner"), "id") != 143339177L)
            throw new IllegalArgumentException("fixed private task repository required");
    }
    static JSONObject verifyRecord(JSONObject record, JSONObject pairing) throws Exception {
        RemoteTasks.exact(record, "schema", "kind", "run_id", "envelope");
        if (!"cleanyourtv.github-task.v1".equals(record.getString("schema"))
                || !"device_task".equals(record.getString("kind"))) throw new IllegalArgumentException("not a device task");
        JSONObject task = RemoteTasks.verify(record.getJSONObject("envelope"), pairing);
        if (!"status".equals(task.getString("op"))) throw new IllegalArgumentException("GitHub status only");
        return task;
    }
    static Entry next(JSONObject pairing) throws Exception {
        requirePrivate(pairing);
        // Bounded oldest-first scan. Completed tasks must be closed; expired/untrusted records are never executed.
        for (int page = 1; page <= 5; page++) {
            JSONArray issues = new JSONArray(request(pairing,
                    "/issues?state=open&sort=created&direction=asc&per_page=10&page=" + page, "GET", null));
            for (int i = 0; i < issues.length(); i++) {
                JSONObject issue = issues.getJSONObject(i);
                if (issue.has("pull_request") || !issue.optString("title").startsWith("[signed-task] ")) continue;
                try {
                    String body = issue.getString("body");
                    if (body.length() > 16384) continue;
                    JSONObject record = new JSONObject(body);
                    if (!"device_task".equals(record.optString("kind"))) continue; // Never trust probe keys.
                    JSONObject task = verifyRecord(record, pairing);
                    long number = RemoteTasks.integer(issue, "number");
                    if (number > 0) return new Entry(task, number);
                } catch (Exception ignored) { /* malformed, expired, wrong target or key: skip, never execute */ }
            }
            if (issues.length() < 10) break;
        }
        return null;
    }
    static void receipt(JSONObject pairing, long issue, String id, JSONObject result) throws Exception {
        if (issue <= 0 || !id.matches("[A-Za-z0-9_-]{1,64}")) throw new IllegalArgumentException("receipt binding");
        requirePrivate(pairing);
        JSONObject record = new JSONObject().put("schema", "cleanyourtv.github-result.v1")
                .put("device", pairing.getString("device")).put("task_id", id).put("result", result);
        // At-least-once delivery: a lost POST reply may duplicate this same immutable result comment.
        // No command or setting is ever taken from comments or issue state.
        request(pairing, "/issues/" + issue + "/comments", "POST", new JSONObject().put("body", record.toString()));
        request(pairing, "/issues/" + issue, "PATCH", new JSONObject().put("state", "closed"));
    }
}
