"""Regression checks for the Android gallery/camera photo handoff."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
ANDROID = (ROOT / "android/app/src/main/java/com/leafwise/app/MainActivity.kt").read_text()
WEB = (ROOT / "web/app.js").read_text()
INDEX = (ROOT / "web/index.html").read_text()


class AndroidPhotoFlowTests(unittest.TestCase):
    def test_native_selection_passes_a_short_token_not_the_photo_payload(self):
        self.assertIn("val token = stageSelectedPhoto(decoded)", ANDROID)
        self.assertIn("window.onNativeImage(${JSONObject.quote(token)}", ANDROID)
        self.assertNotIn("bitmapToBase64(bitmap)", ANDROID)
        self.assertIn('addPathHandler("/selected/"', ANDROID)

    def test_gallery_import_is_copied_to_private_file_before_decode(self):
        self.assertIn("copyUriToCache(uri)", ANDROID)
        self.assertIn("temporaryCameraFile ?: copyUriToCache(uri)", ANDROID)
        self.assertIn("contentResolver.openInputStream(uri)", ANDROID)
        self.assertIn("BitmapFactory.decodeFile(file.absolutePath, options)", ANDROID)
        self.assertIn("ExifInterface(file.absolutePath).rotationDegrees", ANDROID)
        self.assertIn("getOrDefault(0)", ANDROID)
        self.assertIn("Android denied access to that photo", ANDROID)
        self.assertNotIn("private fun decodeUri(uri: Uri)", ANDROID)

    def test_native_analysis_reads_the_private_staged_photo(self):
        self.assertIn("fun analyzeImage(photoToken: String", ANDROID)
        self.assertIn("requestId: String", ANDROID)
        self.assertIn("window.onNativeAnalysis && window.onNativeAnalysis(${JSONObject.quote(requestId)}", ANDROID)
        self.assertIn("selectedPhotoFile(photoToken)", ANDROID)
        self.assertIn("fun releaseSelectedPhoto(token: String)", ANDROID)
        self.assertIn("File(cacheDir, \"selected\")", ANDROID)

    def test_late_native_results_are_ignored_after_request_timeout(self):
        self.assertIn("pending.requestId !== requestId", WEB)
        self.assertIn("pendingNativeAnalysis?.requestId === requestId", WEB)
        self.assertIn("window.onNativeFailure = (requestId, message)", WEB)

    def test_webview_has_gallery_and_capture_file_chooser_fallbacks(self):
        self.assertIn("override fun onShowFileChooser(", ANDROID)
        self.assertIn("fileChooserParams?.isCaptureEnabled == true", ANDROID)
        self.assertIn("settings.allowContentAccess = true", ANDROID)
        self.assertIn("chooserCallback.onReceiveValue(uri?.let { arrayOf(it) })", ANDROID)

    def test_web_ui_uses_native_token_and_resets_file_inputs_for_retries(self):
        self.assertIn("nativePhotoToken", WEB)
        self.assertIn("native.analyzeImage(state.nativePhotoToken", WEB)
        self.assertIn("native.releaseSelectedPhoto(state.nativePhotoToken)", WEB)
        self.assertNotIn("nativeBase64", WEB)
        self.assertIn("event.target.value = ''", WEB)
        self.assertIn("window.onNativeFailure", WEB)
        self.assertIn("window.onNativePickerFailure", WEB)
        self.assertIn("window.onNativePickerClosed", WEB)
        self.assertIn("pickerInProgress", ANDROID)
        self.assertIn("worker.shutdownNow()", ANDROID)
        self.assertIn('File(cacheDir, "selected").deleteRecursively()', ANDROID)
        self.assertIn("(state.file || state.nativePhotoToken)", WEB)
        self.assertIn("Android temporarily holds a private copy", INDEX)

    def test_creator_details_are_in_a_separate_navigation_view(self):
        self.assertIn('data-view-link="creator"', INDEX)
        self.assertIn('id="view-creator" data-view="creator"', INDEX)
        creator = INDEX.split('id="view-creator"', 1)[1]
        about = INDEX.split('id="view-about"', 1)[1].split('id="view-creator"', 1)[0]
        self.assertIn("Vignesh P", creator)
        self.assertIn("@vignesh_pgd", creator)
        self.assertIn("vigneshperingode352@gmail.com", creator)
        self.assertIn("cybrogofficial@gmail.com", creator)
        self.assertNotIn("creator-profile", about)
        self.assertIn(".creator-profile", (ROOT / "web/styles.css").read_text())


if __name__ == "__main__":
    unittest.main()
