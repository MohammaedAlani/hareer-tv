package family.blossom.tv;

import org.json.JSONObject;
import java.security.MessageDigest;

final class UpdateRelease {
    final int versionCode;
    final String version, url, sha256;
    UpdateRelease(String json) throws Exception {
        JSONObject value = new JSONObject(json);
        versionCode = value.getInt("versionCode");
        version = value.getString("version");
        url = value.getString("url");
        sha256 = value.getString("sha256");
        Catalog.validateUrl(url, false);
        if (versionCode <= 0 || version.isEmpty() || version.length() > 64 || !sha256.matches("[a-fA-F0-9]{64}"))
            throw new IllegalArgumentException("Invalid release metadata");
    }
    void verifyChecksum(byte[] bytes) throws Exception {
        StringBuilder actual = new StringBuilder();
        for (byte b : MessageDigest.getInstance("SHA-256").digest(bytes)) actual.append(String.format("%02x", b & 255));
        if (!actual.toString().equalsIgnoreCase(sha256)) throw new SecurityException("Checksum mismatch");
    }
}
