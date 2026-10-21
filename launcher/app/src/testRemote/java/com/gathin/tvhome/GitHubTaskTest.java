package com.gathin.tvhome;

import org.json.JSONObject;
import org.junit.Before;
import org.junit.Test;
import java.nio.charset.StandardCharsets;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.Signature;
import java.util.Base64;
import static org.junit.Assert.*;

/** Real RSA verification through the device parser. No network or projector is simulated as successful. */
public class GitHubTaskTest {
    private KeyPair key;
    private JSONObject pairing;
    @Before public void setUp() throws Exception {
        KeyPairGenerator generator = KeyPairGenerator.getInstance("RSA"); generator.initialize(2048);
        key = generator.generateKeyPair();
        String pub = "-----BEGIN PUBLIC KEY-----\n" + Base64.getEncoder().encodeToString(key.getPublic().getEncoded())
                + "\n-----END PUBLIC KEY-----\n";
        pairing = new JSONObject().put("transport", "github-issues").put("repository", RemoteGitHub.REPOSITORY)
                .put("repository_id", RemoteGitHub.REPOSITORY_ID).put("device", "x5pro")
                .put("token", "github_pat_" + "a".repeat(64)).put("public_key", pub);
    }
    private JSONObject record(String device, String op, long expires) throws Exception {
        long now = System.currentTimeMillis()/1000;
        JSONObject task = new JSONObject().put("v", 1).put("id", "gh-123").put("device", device)
                .put("issued_at", now - 5).put("expires_at", expires).put("op", op).put("args", new JSONObject());
        byte[] bytes = task.toString().getBytes(StandardCharsets.UTF_8);
        Signature signature = Signature.getInstance("SHA256withRSA"); signature.initSign(key.getPrivate()); signature.update(bytes);
        JSONObject envelope = new JSONObject().put("payload", Base64.getEncoder().encodeToString(bytes))
                .put("signature", Base64.getEncoder().encodeToString(signature.sign()));
        return new JSONObject().put("schema", "cleanyourtv.github-task.v1").put("kind", "device_task")
                .put("run_id", "123").put("envelope", envelope);
    }
    @Test public void validPinnedStatus() throws Exception {
        RemotePairing.validate(pairing);
        assertEquals("gh-123", RemoteGitHub.verifyRecord(record("x5pro", "status", System.currentTimeMillis()/1000+600), pairing).getString("id"));
    }
    @Test public void repositoryAndProbePairingRejected() throws Exception {
        pairing.put("repository", "other/repo");
        assertThrows(Exception.class, () -> RemotePairing.validate(pairing));
        pairing.put("repository", RemoteGitHub.REPOSITORY).put("device", "cloud-probe");
        assertThrows(Exception.class, () -> RemotePairing.validate(pairing));
    }
    @Test public void cloudProbeCannotSupplyItsOwnTrustKey() throws Exception {
        JSONObject record = record("x5pro", "status", System.currentTimeMillis()/1000+600);
        record.put("kind", "cloud_probe").put("probe_public_key", pairing.getString("public_key"));
        assertThrows(Exception.class, () -> RemoteGitHub.verifyRecord(record, pairing));
    }
    @Test public void signedNonStatusCannotEnterGitHubTransport() throws Exception {
        JSONObject record = record("x5pro", "list_apps", System.currentTimeMillis()/1000+600);
        assertThrows(Exception.class, () -> RemoteGitHub.verifyRecord(record, pairing));
    }
    @Test public void expiredOrWrongDeviceCannotExecute() throws Exception {
        JSONObject expired = record("x5pro", "status", System.currentTimeMillis()/1000-1);
        assertThrows(Exception.class, () -> RemoteGitHub.verifyRecord(expired, pairing));
        JSONObject wrong = record("other", "status", System.currentTimeMillis()/1000+600);
        assertThrows(Exception.class, () -> RemoteGitHub.verifyRecord(wrong, pairing));
    }
    @Test public void payloadTamperingCannotExecute() throws Exception {
        JSONObject record = record("x5pro", "status", System.currentTimeMillis()/1000+600);
        JSONObject envelope = record.getJSONObject("envelope");
        String body = new String(Base64.getDecoder().decode(envelope.getString("payload")), StandardCharsets.UTF_8);
        envelope.put("payload", Base64.getEncoder().encodeToString(body.replace("gh-123", "gh-999").getBytes(StandardCharsets.UTF_8)));
        assertThrows(Exception.class, () -> RemoteGitHub.verifyRecord(record, pairing));
    }
}
