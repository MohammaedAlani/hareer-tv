package family.blossom.tv;

import android.app.AlertDialog;
import android.app.ActivityManager;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.provider.Settings;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Parent-initiated updates. Android always owns installation approval. */
final class AppUpdate {
    static final int PERMISSION = 800, INSTALL = 801;
    private final MainActivity activity;
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private AlertDialog dialog;
    private boolean busy, relock;
    private File apk;

    AppUpdate(MainActivity activity) { this.activity = activity; }

    void check() {
        if (busy) return;
        busy = true;
        message("Checking for updates…", "Installed version: " + BuildConfig.VERSION_NAME);
        worker.execute(() -> {
            try {
                UpdateRelease release = new UpdateRelease(new String(Network.get(BuildConfig.UPDATE_URL, 16384), StandardCharsets.UTF_8));
                int version = release.versionCode;
                String name = release.version;
                activity.runOnUiThread(() -> {
                    busy = false;
                    if (activity.isDestroyed()) return;
                    if (version <= BuildConfig.VERSION_CODE) message("You’re up to date", "Hareer TV " + BuildConfig.VERSION_NAME);
                    else {
                        dismiss();
                        dialog = new AlertDialog.Builder(activity).setTitle("Hareer TV " + name)
                            .setMessage("Download and install this update? Your video library will stay the same.")
                            .setNegativeButton("Later", null).setPositiveButton("Download", (d,w) -> download(release)).show();
                    }
                });
            } catch (Exception error) { failed("Couldn’t check for updates. Check the connection and try again."); }
        });
    }

    private void download(UpdateRelease release) {
        busy = true;
        message("Downloading update…", "Please keep Hareer TV open. Installation needs a grown-up’s approval.");
        worker.execute(() -> {
            File file = new File(activity.getCacheDir(), "update.apk");
            try {
                byte[] bytes = Network.get(release.url, 50 * 1024 * 1024);
                release.verifyChecksum(bytes);
                Files.write(file.toPath(), bytes);
                verify(file, release.versionCode);
                activity.runOnUiThread(() -> {
                    busy = false;
                    if (activity.isDestroyed()) return;
                    apk = file;
                    dismiss();
                    dialog = new AlertDialog.Builder(activity).setTitle("Update ready")
                        .setMessage("Continue to Android’s installer. If asked, allow Hareer TV to install apps, then return here.")
                        .setNegativeButton("Later", null).setPositiveButton("Install", (d,w) -> install()).show();
                });
            } catch (Exception error) { file.delete(); failed("The update could not be downloaded or verified. Please try again."); }
        });
    }

    @SuppressWarnings("deprecation")
    private void verify(File file, int version) throws Exception {
        PackageManager pm = activity.getPackageManager();
        PackageInfo candidate = pm.getPackageArchiveInfo(file.getPath(), PackageManager.GET_SIGNATURES);
        PackageInfo installed = pm.getPackageInfo(activity.getPackageName(), PackageManager.GET_SIGNATURES);
        if (candidate == null || !activity.getPackageName().equals(candidate.packageName)
                || candidate.versionCode != version || candidate.versionCode <= installed.versionCode
                || candidate.signatures == null || candidate.signatures.length == 0
                || !Arrays.equals(candidate.signatures, installed.signatures)) throw new SecurityException("Invalid update");
    }

    private void install() {
        if (apk == null || !apk.isFile()) { message("Update unavailable", "Check for updates again."); return; }
        try {
            ActivityManager manager = activity.getSystemService(ActivityManager.class);
            if (manager.getLockTaskModeState() != ActivityManager.LOCK_TASK_MODE_NONE) {
                relock = true; activity.stopLockTask();
            }
            if (!activity.getPackageManager().canRequestPackageInstalls()) {
                activity.startActivityForResult(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                    Uri.parse("package:" + activity.getPackageName())), PERMISSION);
                return;
            }
            Intent intent = new Intent(Intent.ACTION_INSTALL_PACKAGE)
                .setDataAndType(Uri.parse("content://" + activity.getPackageName() + ".updates/update.apk"), "application/vnd.android.package-archive")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION).putExtra(Intent.EXTRA_RETURN_RESULT, true);
            activity.startActivityForResult(intent, INSTALL);
        } catch (Exception error) {
            restoreLock();
            message("Installer unavailable", "This TV could not open the installer. Install the latest APK from tv.nawaa.app using your usual TV installation method.");
        }
    }

    void result(int request) {
        restoreLock();
        if (request == PERMISSION) {
            if (activity.getPackageManager().canRequestPackageInstalls()) {
                dismiss();
                dialog = new AlertDialog.Builder(activity).setTitle("Ready to install")
                    .setMessage("Install the downloaded update now?").setNegativeButton("Later", null)
                    .setPositiveButton("Install", (d,w) -> install()).show();
            } else message("Installation not allowed", "No changes were made. You can try again from Update.");
        } else message("Installation finished", "If you cancelled, you can retry from Update. Installed version: " + BuildConfig.VERSION_NAME);
    }

    private void restoreLock() {
        if (relock) { try { activity.startLockTask(); } catch (Exception ignored) { /* Device policy may have changed. */ } relock = false; }
    }
    private void failed(String text) { activity.runOnUiThread(() -> { busy = false; message("Update unavailable", text); }); }
    private void message(String title, String text) {
        if (activity.isDestroyed()) return;
        dismiss(); dialog = new AlertDialog.Builder(activity).setTitle(title).setMessage(text).setPositiveButton("OK", null).show();
    }
    private void dismiss() { if (dialog != null) { dialog.dismiss(); dialog = null; } }
    void close() { dismiss(); worker.shutdownNow(); }
}
