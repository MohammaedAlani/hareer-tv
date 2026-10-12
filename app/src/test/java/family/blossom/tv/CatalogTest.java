package family.blossom.tv;
import org.junit.Test;
import static org.junit.Assert.*;
public class CatalogTest {
    private String entry(String video) { return "{\"videos\":[{\"title\":\" A happy story \",\"imageUrl\":\"https://media.example/cover.jpg\",\"videoUrl\":\""+video+"\"}]}"; }
    @Test public void readsBackendContract() throws Exception {
        var videos = Catalog.parse(entry("https://media.example/story.mp4"), false);
        assertEquals(1,videos.size()); assertEquals("A happy story",videos.get(0).title());
    }
    @Test public void allowsEmptyLibrary() throws Exception { assertTrue(Catalog.parse("{\"videos\":[]}",false).isEmpty()); }
    @Test public void rejectsInvalidSources() {
        for (String source : new String[]{"file:///sdcard/movie.mp4","javascript:alert(1)","http://media.example/movie.mp4","https://youtube.com/watch?v=abc","https://youtu.be/abc"}) {
            assertThrows(Exception.class, () -> Catalog.parse(entry(source),false));
        }
    }
    @Test public void permitsLocalDevelopmentHttpOnlyWhenExplicit() throws Exception {
        assertEquals(1,Catalog.parse(entry("http://10.0.2.2:8080/story.mp4"),true).size());
    }
    @Test public void malformedCatalogFailsClosed() {
        assertThrows(Exception.class, () -> Catalog.parse("{\"videos\":[{\"title\":\"Missing video\"}]}",false));
        assertThrows(Exception.class, () -> Catalog.parse(entry("https://media.example/a.mp4").replace(" A happy story "," "),false));
    }
}
