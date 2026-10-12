package family.blossom.tv;

import org.junit.Test;
import org.json.JSONObject;
import static org.junit.Assert.*;

public class UpdateReleaseTest {
    private String metadata(String url, String hash, int code) throws Exception {
        return new JSONObject().put("versionCode", code).put("version", "1.1.0")
            .put("url", url).put("sha256", hash).toString();
    }
    private static final String EMPTY_HASH = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";
    @Test public void validReleaseAndChecksum() throws Exception {
        UpdateRelease release = new UpdateRelease(metadata("https://example.com/app.apk", EMPTY_HASH.toUpperCase(), 3));
        assertEquals(3, release.versionCode);
        release.verifyChecksum(new byte[0]);
    }
    @Test public void rejectsInsecureAndMalformedMetadata() throws Exception {
        for (String url : new String[]{"http://example.com/app.apk", "file:///tmp/app.apk", "https://user:pass@example.com/app.apk"}) {
            assertThrows(Exception.class, () -> new UpdateRelease(metadata(url, EMPTY_HASH, 3)));
        }
        assertThrows(Exception.class, () -> new UpdateRelease(metadata("https://example.com/app.apk", "bad", 3)));
        assertThrows(Exception.class, () -> new UpdateRelease(metadata("https://example.com/app.apk", EMPTY_HASH, 0)));
        assertThrows(Exception.class, () -> new UpdateRelease("{}"));
    }
    @Test public void rejectsModifiedDownload() throws Exception {
        UpdateRelease release = new UpdateRelease(metadata("https://example.com/app.apk", EMPTY_HASH, 3));
        assertThrows(SecurityException.class, () -> release.verifyChecksum(new byte[]{1}));
    }
}
