package family.blossom.tv;

import org.json.JSONArray;
import org.json.JSONObject;
import java.net.URI;
import java.util.ArrayList;
import java.util.List;

final class Catalog {
    record Video(String title, String imageUrl, String videoUrl) {}

    static List<Video> parse(String json, boolean allowHttp) throws Exception {
        JSONArray rows = new JSONObject(json).getJSONArray("videos");
        if (rows.length() > 300) throw new IllegalArgumentException("Too many videos");
        List<Video> videos = new ArrayList<>();
        for (int i = 0; i < rows.length(); i++) {
            JSONObject row = rows.getJSONObject(i);
            String title = row.getString("title").trim();
            if (title.isEmpty() || title.length() > 200) throw new IllegalArgumentException("Invalid title");
            String image = row.getString("imageUrl");
            String video = row.getString("videoUrl");
            validateUrl(image, allowHttp);
            validateUrl(video, allowHttp);
            String host = URI.create(video).getHost().toLowerCase(java.util.Locale.ROOT);
            if (host.equals("youtu.be") || host.equals("youtube.com") || host.endsWith(".youtube.com"))
                throw new IllegalArgumentException("Use a stored video, not a YouTube page");
            videos.add(new Video(title, image, video));
        }
        return java.util.Collections.unmodifiableList(videos);
    }

    static void validateUrl(String value, boolean allowHttp) {
        URI uri = URI.create(value);
        if (!("https".equals(uri.getScheme()) || (allowHttp && "http".equals(uri.getScheme())))
                || uri.getHost() == null || uri.getUserInfo() != null)
            throw new IllegalArgumentException("Expected a media URL");
    }
}
