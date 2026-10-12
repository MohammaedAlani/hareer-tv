package family.blossom.tv;

import android.app.Activity;
import android.app.Dialog;
import android.app.admin.DevicePolicyManager;
import android.content.ComponentName;
import android.graphics.*;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.view.*;
import android.widget.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;

public final class MainActivity extends Activity {
    private static final int INK = Color.rgb(83, 56, 81), ROSE = Color.rgb(163, 65, 112);
    private final ExecutorService io = Executors.newFixedThreadPool(3);
    private final Random random = new Random();
    private List<Catalog.Video> videos = Collections.emptyList();
    private LinearLayout list;
    private TextView caption;
    private FrameLayout root;
    private VideoView player;
    private Catalog.Video current;
    private Dialog puzzle;
    private AppUpdate updates;
    private int generation, selectedIndex, position;
    private boolean prepared, backgrounded, resumePlayback;
    private TextView playButton;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        immersive();
        DevicePolicyManager policy = getSystemService(DevicePolicyManager.class);
        try {
            if (policy.isDeviceOwnerApp(getPackageName())) {
                policy.setLockTaskPackages(new ComponentName(this, KioskAdmin.class), new String[]{getPackageName()});
            }
            if (policy.isLockTaskPermitted(getPackageName())) startLockTask();
        } catch (SecurityException | IllegalStateException error) {
            android.util.Log.w("HareerTV", "Kiosk configuration is unavailable", error);
            Toast.makeText(this, "Kiosk setup needs repair. The Home button may leave the app.", Toast.LENGTH_LONG).show();
        }
        updates = new AppUpdate(this);
        showLibrary();
        loadCatalog();
    }

    private void immersive() {
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_FULLSCREEN
            | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
            | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
            | View.SYSTEM_UI_FLAG_LAYOUT_STABLE);
    }

    private int dp(float value) { return Math.round(value * getResources().getDisplayMetrics().density); }
    private LinearLayout column() { LinearLayout v = new LinearLayout(this); v.setOrientation(LinearLayout.VERTICAL); return v; }
    private LinearLayout row() { LinearLayout v = new LinearLayout(this); v.setGravity(Gravity.CENTER_VERTICAL); return v; }
    private TextView text(String value, int size, int color) {
        TextView v = new TextView(this); v.setText(value); v.setTextSize(size); v.setTextColor(color);
        v.setFontFeatureSettings("kern"); return v;
    }
    private GradientDrawable rounded(int color, int stroke) {
        GradientDrawable d = new GradientDrawable(); d.setColor(color); d.setCornerRadius(dp(22));
        if (stroke != 0) d.setStroke(dp(3), stroke); return d;
    }
    private void focusable(View v, int color) {
        v.setFocusable(true); v.setClickable(true); v.setBackground(rounded(color, 0));
        v.setOnFocusChangeListener((view, focused) -> {
            view.setBackground(rounded(color, focused ? ROSE : 0));
            view.setElevation(dp(focused ? 7 : 1));
        });
    }
    private TextView button(String label, Runnable action) {
        TextView b = text(label, 16, INK); b.setGravity(Gravity.CENTER);
        b.setTypeface(null, Typeface.BOLD); b.setPadding(dp(22), dp(14), dp(22), dp(14));
        focusable(b, Color.WHITE); b.setOnClickListener(v -> action.run()); return b;
    }

    private void showLibrary() {
        current = null; player = null;
        root = new FrameLayout(this); root.addView(new Garden());
        LinearLayout page = column(); page.setPadding(dp(44), dp(25), dp(44), dp(18));
        LinearLayout top = row();
        TextView brand = text("✿  Hareer TV", 23, ROSE); brand.setTypeface(null, Typeface.BOLD);
        top.addView(brand, new LinearLayout.LayoutParams(0, dp(48), 1));
        top.addView(button("↻  Refresh", this::loadCatalog));
        top.addView(button("Update", () -> showPuzzle("Grown-up update check", updates::check)));
        TextView exit = button("Exit  ☆", this::showPuzzle);
        LinearLayout.LayoutParams exitParams = new LinearLayout.LayoutParams(-2, -2); exitParams.leftMargin = dp(12);
        top.addView(exit, exitParams); page.addView(top);
        TextView heading = text("A little world of happy stories", 32, INK);
        heading.setTypeface(Typeface.create("sans-serif-rounded", Typeface.BOLD)); heading.setPadding(0, dp(18), 0, dp(4));
        page.addView(heading);
        caption = text("Pick a picture. Let’s watch something lovely!", 16, INK); page.addView(caption);
        ScrollView scroll = new ScrollView(this); scroll.setClipToPadding(false); scroll.setPadding(dp(5), dp(18), dp(5), dp(12));
        scroll.setFillViewport(true); scroll.setVerticalScrollBarEnabled(false);
        list = column(); scroll.addView(list);
        page.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
        TextView hint = text("↑ ↓ ← →  Choose a story     •     OK  Play     •     Back  Exit puzzle", 13, INK);
        page.addView(hint); root.addView(page); setContentView(root); renderVideos();
    }

    private void showMessage(String title, String detail) {
        list.removeAllViews();
        LinearLayout box = column(); box.setGravity(Gravity.CENTER); box.setPadding(dp(28), dp(22), dp(28), dp(22));
        box.setBackground(rounded(0xDFFFFFFF, 0));
        TextView flower = text("✿", 52, ROSE); flower.setGravity(Gravity.CENTER); box.addView(flower);
        TextView heading = text(title, 24, INK); heading.setGravity(Gravity.CENTER); box.addView(heading);
        TextView body = text(detail, 16, INK); body.setGravity(Gravity.CENTER); body.setPadding(0, dp(12), 0, dp(12)); box.addView(body);
        box.addView(button("Try again ↻", this::loadCatalog));
        list.addView(box, new LinearLayout.LayoutParams(-1, -1));
    }

    private void loadCatalog() {
        if (current != null) return;
        int token = ++generation;
        videos = Collections.emptyList();
        if (BuildConfig.CATALOG_URL.isEmpty()) {
            showMessage("Your story garden is waiting", "Ask a grown-up to connect your video library."); return;
        }
        showMessage("Gathering your stories…", "Just a little moment.");
        io.execute(() -> {
            try {
                List<Catalog.Video> result = Catalog.parse(new String(Network.get(BuildConfig.CATALOG_URL, 1024 * 1024), StandardCharsets.UTF_8), BuildConfig.DEBUG);
                runOnUiThread(() -> { if (isDestroyed() || token != generation || current != null) return; videos = result; renderVideos(); });
            } catch (Exception e) {
                runOnUiThread(() -> { if (!isDestroyed() && token == generation && current == null)
                    showMessage("The stories couldn’t come over", "Check your connection, then try again."); });
            }
        });
    }

    private void renderVideos() {
        list.removeAllViews();
        if (videos.isEmpty()) { showMessage("Your story garden is waiting", "Your videos will blossom here soon."); return; }
        caption.setText("Pick a picture. Let’s watch something lovely!");
        int columns = getResources().getConfiguration().screenWidthDp >= 800 ? 3 : 2;
        LinearLayout cards = null;
        for (int i = 0; i < videos.size(); i++) {
            if (i % columns == 0) { cards = row(); cards.setGravity(Gravity.TOP); list.addView(cards); }
            Catalog.Video video = videos.get(i); int index = i;
            LinearLayout card = column(); card.setPadding(dp(7), dp(7), dp(7), dp(10));
            focusable(card, Color.WHITE); card.setContentDescription("Play " + video.title());
            card.setOnClickListener(v -> { selectedIndex = index; play(video); });
            LinearLayout.LayoutParams cp = new LinearLayout.LayoutParams(0, -2, 1); cp.setMargins(dp(5), dp(5), dp(9), dp(14));
            cards.addView(card, cp);
            FrameLayout picture = new FrameLayout(this); picture.setBackground(rounded(new int[]{0xFFF2DEEC,0xFFE2ECE1,0xFFE5DFF2}[i % 3],0));
            picture.setClipToOutline(true);
            int width = (getResources().getConfiguration().screenWidthDp - 88) / columns - 30;
            card.addView(picture, new LinearLayout.LayoutParams(-1, dp(width * 9f / 16f)));
            TextView placeholder = text("✿", 48, ROSE); placeholder.setGravity(Gravity.CENTER); picture.addView(placeholder, new FrameLayout.LayoutParams(-1, -1));
            ImageView image = new ImageView(this); image.setScaleType(ImageView.ScaleType.CENTER_CROP);
            image.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO); picture.addView(image, new FrameLayout.LayoutParams(-1, -1));
            TextView badge = text("▶", 21, ROSE); badge.setGravity(Gravity.CENTER); badge.setBackground(rounded(0xEEFFFFFF,0));
            FrameLayout.LayoutParams bp = new FrameLayout.LayoutParams(dp(40),dp(36),Gravity.BOTTOM | Gravity.END); bp.setMargins(0,0,dp(9),dp(9)); picture.addView(badge,bp);
            TextView title = text(video.title(), 18, INK); title.setTypeface(null, Typeface.BOLD); title.setMaxLines(2);
            title.setEllipsize(android.text.TextUtils.TruncateAt.END); title.setPadding(dp(10),dp(10),dp(8),0);
            card.addView(title, new LinearLayout.LayoutParams(-1, dp(60)));
            loadImage(video.imageUrl(), image);
            if (i == Math.min(selectedIndex, videos.size()-1)) card.post(card::requestFocus);
        }
        int remainder = videos.size() % columns;
        if (remainder != 0) for (int i = remainder; i < columns; i++) cards.addView(new View(this), new LinearLayout.LayoutParams(0, 1, 1));
    }

    private void loadImage(String url, ImageView image) {
        io.execute(() -> {
            try {
                byte[] data = Network.get(url, 5 * 1024 * 1024);
                BitmapFactory.Options options = new BitmapFactory.Options(); options.inJustDecodeBounds = true;
                BitmapFactory.decodeByteArray(data,0,data.length,options);
                options.inSampleSize = 1;
                while (options.outWidth / options.inSampleSize > 960 || options.outHeight / options.inSampleSize > 540) options.inSampleSize *= 2;
                options.inJustDecodeBounds = false;
                Bitmap bitmap = BitmapFactory.decodeByteArray(data,0,data.length,options);
                runOnUiThread(() -> { if (!isDestroyed() && image.isAttachedToWindow() && bitmap != null) image.setImageBitmap(bitmap); });
            } catch (Exception ignored) { /* Keep the flower if a thumbnail is unavailable. */ }
        });
    }

    private void play(Catalog.Video video) {
        current = video; position = 0; prepared = false; backgrounded = false;
        root = new FrameLayout(this); root.setBackgroundColor(Color.BLACK);
        player = new VideoView(this);
        FrameLayout.LayoutParams vp = new FrameLayout.LayoutParams(-1,-1,Gravity.CENTER); root.addView(player,vp);
        player.setFocusable(false);
        LinearLayout overlay = column(); overlay.setPadding(dp(28), dp(14), dp(28), dp(14)); overlay.setBackgroundColor(0xB0201524);
        TextView title = text(video.title(),20,Color.WHITE); overlay.addView(title);
        LinearLayout controls = row();
        controls.addView(button("‹  My stories", this::returnToLibrary));
        playButton = button("Loading…", this::togglePlayback);
        LinearLayout.LayoutParams margin = new LinearLayout.LayoutParams(-2,-2); margin.leftMargin=dp(12); controls.addView(playButton,margin);
        TextView seek = button("+10 seconds", () -> { if (prepared) player.seekTo(Math.min(player.getDuration(),player.getCurrentPosition()+10000)); });
        LinearLayout.LayoutParams sp = new LinearLayout.LayoutParams(-2,-2); sp.leftMargin=dp(12); controls.addView(seek,sp);
        overlay.addView(controls);
        FrameLayout.LayoutParams op = new FrameLayout.LayoutParams(-1,-2,Gravity.BOTTOM); root.addView(overlay,op);
        setContentView(root); playButton.requestFocus();
        player.setOnPreparedListener(mp -> { prepared=true; if (position>0) player.seekTo(position); if (puzzle == null && !backgrounded) { player.start(); playButton.setText("Ⅱ  Pause"); } });
        player.setOnCompletionListener(mp -> returnToLibrary());
        player.setOnErrorListener((mp, what, extra) -> {
            returnToLibrary(); caption.setText("That story couldn’t play. Try another picture."); return true;
        });
        player.setVideoURI(Uri.parse(video.videoUrl()));
    }

    private void togglePlayback() {
        if (!prepared || player == null) return;
        if (player.isPlaying()) { player.pause(); playButton.setText("▶  Play"); }
        else { player.start(); playButton.setText("Ⅱ  Pause"); }
    }

    private void returnToLibrary() {
        if (player != null) player.stopPlayback(); prepared=false; showLibrary();
        // Fetch again on return so removed videos disappear; there is no offline catalog cache.
        loadCatalog();
    }

    @Override public void onBackPressed() {
        if (puzzle != null) return;
        if (current != null) returnToLibrary(); else showPuzzle();
    }

    private void showPuzzle() {
        showPuzzle("Ready to say bye-bye?", () -> {
            if (player != null) player.stopPlayback();
            android.app.ActivityManager manager = getSystemService(android.app.ActivityManager.class);
            if (manager.getLockTaskModeState() != android.app.ActivityManager.LOCK_TASK_MODE_NONE) stopLockTask();
            finishAndRemoveTask();
        });
    }

    private void showPuzzle(String heading, Runnable approved) {
        if (puzzle != null) return;
        resumePlayback = player != null && player.isPlaying();
        if (player != null) player.pause();
        int answer = 2 + random.nextInt(4);
        Dialog dialog = new Dialog(this); puzzle = dialog; dialog.setCancelable(false);
        LinearLayout panel = column(); panel.setGravity(Gravity.CENTER); panel.setPadding(dp(32),dp(26),dp(32),dp(26)); panel.setBackground(rounded(0xFFFFF8F4,0));
        TextView eyebrow = text("ONE LITTLE PUZZLE", 13, ROSE); eyebrow.setGravity(Gravity.CENTER); eyebrow.setLetterSpacing(.12f); panel.addView(eyebrow);
        TextView title = text(heading,27,INK); title.setGravity(Gravity.CENTER); title.setTypeface(null,Typeface.BOLD); panel.addView(title);
        TextView stars = text(String.join("  ", Collections.nCopies(answer,"★")),38,0xFFC18320); stars.setGravity(Gravity.CENTER); stars.setPadding(0,dp(20),0,dp(15)); panel.addView(stars);
        TextView prompt = text("How many stars can you count?",18,INK); prompt.setGravity(Gravity.CENTER); panel.addView(prompt);
        LinearLayout choices = row(); choices.setGravity(Gravity.CENTER); choices.setPadding(0,dp(18),0,dp(12));
        List<Integer> answers = new ArrayList<>(Arrays.asList(answer,answer-1,answer+1)); Collections.shuffle(answers,random);
        for (int value : answers) {
            TextView choice = button(Integer.toString(value), () -> {
                if (value == answer) { puzzle=null; dialog.dismiss(); approved.run();
                } else { prompt.setText("Almost! Count the stars and try again."); }
            });
            LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(dp(90),dp(58)); p.setMargins(dp(6),0,dp(6),0); choices.addView(choice,p);
        }
        panel.addView(choices);
        TextView stay = button("♡  Stay and watch", () -> { puzzle=null; dialog.dismiss(); if (resumePlayback && prepared && player!=null) player.start(); });
        panel.addView(stay); dialog.setContentView(panel);
        dialog.setOnKeyListener((d,key,event) -> { if (key == KeyEvent.KEYCODE_BACK) { if (event.getAction()==KeyEvent.ACTION_UP) stay.performClick(); return true; } return false; });
        dialog.show(); dialog.getWindow().setBackgroundDrawableResource(android.R.color.transparent);
        dialog.getWindow().setLayout(dp(520),-2); stay.requestFocus();
    }

    @Override public boolean onKeyDown(int key, android.view.KeyEvent event) {
        if (player != null && (key == KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE || key == KeyEvent.KEYCODE_MEDIA_PLAY || key == KeyEvent.KEYCODE_MEDIA_PAUSE)) {
            if (prepared) {
                if (key==KeyEvent.KEYCODE_MEDIA_PLAY && !player.isPlaying() || key==KeyEvent.KEYCODE_MEDIA_PAUSE && player.isPlaying() || key==KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE) togglePlayback();
            }
            return true;
        }
        return super.onKeyDown(key,event);
    }
    @Override protected void onPause() { super.onPause(); backgrounded=true; if (player!=null) { player.pause(); if (playButton!=null) playButton.setText("▶  Play"); } }
    @Override protected void onResume() { super.onResume(); backgrounded=false; immersive(); }
    @Override protected void onActivityResult(int request, int result, android.content.Intent data) {
        super.onActivityResult(request, result, data);
        if (request == AppUpdate.PERMISSION || request == AppUpdate.INSTALL) updates.result(request);
    }
    @Override protected void onDestroy() { if (updates != null) updates.close(); if (puzzle!=null) { puzzle.dismiss(); puzzle=null; } if (player!=null) player.stopPlayback(); io.shutdownNow(); super.onDestroy(); }

    private final class Garden extends View {
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        Garden() { super(MainActivity.this); setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO); }
        @Override protected void onDraw(Canvas canvas) {
            canvas.drawColor(0xFFFFF8F4);
            paint.setColor(0xFFF5E3EC); canvas.drawCircle(getWidth()*.94f, getHeight()*.08f, dp(150),paint);
            paint.setColor(0xFFE7EDDF); canvas.drawCircle(getWidth()*.05f, getHeight()*1.15f, dp(170),paint);
            paint.setColor(0xFFECE3F3); canvas.drawCircle(getWidth()*.97f, getHeight()*1.2f, dp(200),paint);
        }
    }
}
