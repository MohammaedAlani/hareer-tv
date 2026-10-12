package family.blossom.tv;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;

final class Network {
    static byte[] get(String address, int limit) throws Exception {
        for (int redirect = 0; redirect < 5; redirect++) {
            Catalog.validateUrl(address, BuildConfig.DEBUG);
            HttpURLConnection connection = (HttpURLConnection) new URL(address).openConnection();
            connection.setConnectTimeout(8000);
            connection.setReadTimeout(10000);
            connection.setInstanceFollowRedirects(false);
            try {
                int status = connection.getResponseCode();
                if (status >= 300 && status < 400) {
                    String location = connection.getHeaderField("Location");
                    if (location == null) throw new IllegalStateException("Missing redirect location");
                    address = new URL(new URL(address), location).toString();
                    continue;
                }
                if (status != 200) throw new IllegalStateException("HTTP " + status);
                try (InputStream input = connection.getInputStream(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
                    byte[] buffer = new byte[8192];
                    int count;
                    while ((count = input.read(buffer)) != -1) {
                        if (output.size() + count > limit) throw new IllegalStateException("Response too large");
                        output.write(buffer, 0, count);
                    }
                    return output.toByteArray();
                }
            } finally { connection.disconnect(); }
        }
        throw new IllegalStateException("Too many redirects");
    }
}
