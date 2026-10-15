package com.leafwise.app

import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.net.Uri
import android.os.Bundle
import android.util.Base64
import android.util.Log
import android.view.ViewGroup
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.ValueCallback
import android.webkit.WebView
import android.widget.FrameLayout
import androidx.activity.ComponentActivity
import androidx.activity.result.ActivityResultLauncher
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.FileProvider
import androidx.exifinterface.media.ExifInterface
import androidx.webkit.WebViewAssetLoader
import androidx.webkit.WebViewClientCompat
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import java.util.UUID
import java.util.concurrent.Executors

class MainActivity : ComponentActivity() {
    private lateinit var webView: WebView
    private lateinit var classifier: OnDeviceClassifier
    private lateinit var galleryLauncher: ActivityResultLauncher<String>
    private lateinit var cameraLauncher: ActivityResultLauncher<Uri>
    private val worker = Executors.newSingleThreadExecutor()
    private var pendingCameraFile: File? = null
    private var pendingCameraUri: Uri? = null
    private var pendingFileChooserCallback: ValueCallback<Array<Uri>>? = null
    @Volatile private var pickerInProgress = false
    @Volatile private var activityDestroyed = false
    @Volatile private var activeSelectedPhoto: File? = null
    private val selectedPhotoLock = Any()
    private val prefs by lazy { getSharedPreferences("leafwise_private_history", MODE_PRIVATE) }
    private val appOrigin = "appassets.androidplatform.net"

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = android.graphics.Color.rgb(245, 244, 235)
        window.navigationBarColor = android.graphics.Color.rgb(245, 244, 235)
        if (android.os.Build.VERSION.SDK_INT >= 26) {
            window.decorView.systemUiVisibility = window.decorView.systemUiVisibility or
                android.view.View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR or android.view.View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR
        }
        activityDestroyed = false
        pickerInProgress = false
        File(cacheDir, "selected").deleteRecursively()
        cacheDir.listFiles()?.filter { it.isFile && it.name.startsWith("leafwise-") }?.forEach { it.delete() }
        classifier = OnDeviceClassifier(this)
        galleryLauncher = registerForActivityResult(ActivityResultContracts.GetContent()) { uri ->
            val chooserCallback = pendingFileChooserCallback
            if (chooserCallback != null) {
                pickerInProgress = false
                pendingFileChooserCallback = null
                chooserCallback.onReceiveValue(uri?.let { arrayOf(it) })
                dispatchPickerClosed()
            } else if (uri != null) dispatchSelectedPhoto(uri, "Gallery photo")
            else { pickerInProgress = false; dispatchPickerClosed() }
        }
        cameraLauncher = registerForActivityResult(ActivityResultContracts.TakePicture()) { success ->
            val file = pendingCameraFile
            val uri = pendingCameraUri
            val chooserCallback = pendingFileChooserCallback
            if (chooserCallback != null) {
                pickerInProgress = false
                pendingFileChooserCallback = null
                if (success && file != null && file.exists() && uri != null) {
                    chooserCallback.onReceiveValue(arrayOf(uri))
                    webView.postDelayed({ file.delete() }, 60_000L)
                    dispatchPickerClosed()
                } else {
                    chooserCallback.onReceiveValue(null)
                    file?.delete()
                    dispatchPickerClosed()
                }
            } else if (success && file != null && file.exists() && uri != null) {
                dispatchSelectedPhoto(uri, "Camera photo", file)
            } else {
                pickerInProgress = false
                file?.delete()
                dispatchPickerClosed()
            }
            pendingCameraFile = null
            pendingCameraUri = null
        }
        webView = WebView(this).apply {
            layoutParams = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
            setBackgroundColor(android.graphics.Color.rgb(245, 244, 235))
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.allowFileAccess = false
            settings.allowContentAccess = true
            settings.allowFileAccessFromFileURLs = false
            settings.allowUniversalAccessFromFileURLs = false
            settings.mixedContentMode = android.webkit.WebSettings.MIXED_CONTENT_NEVER_ALLOW
            if (android.os.Build.VERSION.SDK_INT >= 26) settings.safeBrowsingEnabled = true
            addJavascriptInterface(LeafwiseBridge(), "LeafwiseNative")
        }
        val assetLoader = WebViewAssetLoader.Builder()
            .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(this))
            .addPathHandler("/selected/", object : WebViewAssetLoader.PathHandler {
                override fun handle(path: String): WebResourceResponse? {
                    if (!path.endsWith(".jpg")) return null
                    val file = selectedPhotoFile(path.removeSuffix(".jpg")) ?: return null
                    return WebResourceResponse("image/jpeg", "UTF-8", file.inputStream())
                }
            })
            .build()
        webView.webViewClient = object : WebViewClientCompat() {
            override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest) =
                assetLoader.shouldInterceptRequest(request.url)

            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val uri = request.url
                if (uri.scheme == "https" && uri.host == appOrigin) return false
                if (uri.scheme == "https") {
                    runCatching { startActivity(Intent(Intent.ACTION_VIEW, uri)) }
                    return true
                }
                return true
            }
        }
        webView.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(
                view: WebView?,
                filePathCallback: ValueCallback<Array<Uri>>?,
                fileChooserParams: FileChooserParams?
            ): Boolean {
                if (filePathCallback == null) return false
                if (pickerInProgress) {
                    filePathCallback.onReceiveValue(null)
                    return true
                }
                pendingFileChooserCallback?.onReceiveValue(null)
                pendingFileChooserCallback = filePathCallback
                if (fileChooserParams?.isCaptureEnabled == true) capturePhoto() else selectGallery()
                return true
            }
        }
        setContentView(FrameLayout(this).apply { addView(webView) })
        webView.loadUrl("https://$appOrigin/assets/index.html")
        if (BuildConfig.DEBUG) WebView.setWebContentsDebuggingEnabled(true)
    }

    private fun selectGallery() {
        if (activityDestroyed) return
        runOnUiThread {
            if (activityDestroyed) return@runOnUiThread
            if (pickerInProgress) { dispatchFailure("Please wait while the selected photo is being prepared."); return@runOnUiThread }
            pickerInProgress = true
            runCatching { galleryLauncher.launch("image/*") }
                .onFailure { failPhotoPicker("Could not open the photo gallery. Please try again.") }
        }
    }

    private fun capturePhoto() {
        if (activityDestroyed) return
        runOnUiThread {
            if (activityDestroyed) return@runOnUiThread
            if (pickerInProgress) { dispatchFailure("Please wait while the selected photo is being prepared."); return@runOnUiThread }
            pickerInProgress = true
            runCatching {
                val file = File(cacheDir, "leafwise-${UUID.randomUUID()}.jpg")
                pendingCameraFile = file
                val uri = FileProvider.getUriForFile(this, "$packageName.provider", file)
                pendingCameraUri = uri
                cameraLauncher.launch(uri)
            }.onFailure { failPhotoPicker("Could not open the camera. Check that a camera app is available and try again.") }
        }
    }

    private fun failPhotoPicker(message: String) {
        pickerInProgress = false
        pendingFileChooserCallback?.onReceiveValue(null)
        pendingFileChooserCallback = null
        pendingCameraFile?.delete()
        pendingCameraFile = null
        pendingCameraUri = null
        dispatchFailure(message)
    }

    private fun dispatchSelectedPhoto(uri: Uri, label: String, temporaryCameraFile: File? = null) {
        if (activityDestroyed) { temporaryCameraFile?.delete(); return }
        worker.execute {
            var bitmap: Bitmap? = null
            var importedFile: File? = null
            var stage = "copy"
            try {
                if (activityDestroyed) return@execute
                val sourceFile = temporaryCameraFile ?: copyUriToCache(uri).also { importedFile = it }
                stage = "decode"
                val decoded = decodeImageFile(sourceFile)
                bitmap = decoded
                stage = "prepare"
                val token = stageSelectedPhoto(decoded)
                decoded.recycle()
                bitmap = null
                if (!activityDestroyed) postJavascript("window.onNativeImage && window.onNativeImage(${JSONObject.quote(token)}, 'image/jpeg', ${JSONObject.quote(label)})")
                else releaseSelectedPhoto(token)
            } catch (error: Exception) {
                Log.e("LeafwisePhoto", "Photo import failed during $stage (${error.javaClass.simpleName})", error)
                if (!activityDestroyed) {
                    val message = when (error) {
                        is SecurityException -> "Android denied access to that photo. Reopen the gallery and choose it again."
                        is PhotoImportException -> error.message ?: "The photo could not be read."
                        else -> "Could not read that image. Try a JPEG or PNG photo, or take a new picture."
                    }
                    dispatchFailure(message)
                }
            } finally {
                pickerInProgress = false
                bitmap?.recycle()
                importedFile?.delete()
                temporaryCameraFile?.delete()
            }
        }
    }

    private fun copyUriToCache(uri: Uri): File {
        val file = File(cacheDir, "leafwise-import-${UUID.randomUUID()}.bin")
        try {
            val input = contentResolver.openInputStream(uri)
                ?: throw PhotoImportException("Android did not provide the selected photo data.")
            input.use { source ->
                FileOutputStream(file).use { output ->
                    val buffer = ByteArray(64 * 1024)
                    var total = 0L
                    while (true) {
                        val count = source.read(buffer)
                        if (count < 0) break
                        if (count == 0) continue
                        total += count
                        if (total > 40L * 1024L * 1024L) {
                            throw PhotoImportException("That source photo is over 40 MB. Choose a smaller image.")
                        }
                        output.write(buffer, 0, count)
                    }
                }
            }
            if (!file.isFile || file.length() == 0L) {
                throw PhotoImportException("The selected photo is empty. Choose it again or take a new photo.")
            }
            return file
        } catch (error: Exception) {
            file.delete()
            throw error
        }
    }

    private fun stageSelectedPhoto(bitmap: Bitmap): String = synchronized(selectedPhotoLock) {
        if (activityDestroyed) error("The app closed before the photo could be prepared.")
        val token = UUID.randomUUID().toString()
        val directory = File(cacheDir, "selected")
        if (!directory.exists() && !directory.mkdirs()) error("Could not prepare the photo.")
        val file = File(directory, "$token.jpg")
        FileOutputStream(file).use { output ->
            if (!bitmap.compress(Bitmap.CompressFormat.JPEG, 86, output)) error("Could not prepare the photo.")
        }
        if (file.length() <= 0L || file.length() > 10L * 1024L * 1024L) {
            file.delete()
            error("Choose an image that is 10 MB or smaller.")
        }
        activeSelectedPhoto?.takeIf { it != file }?.delete()
        activeSelectedPhoto = file
        token
    }

    private fun selectedPhotoFile(token: String): File? {
        if (activityDestroyed) return null
        val canonicalId = runCatching { UUID.fromString(token).toString() }.getOrNull() ?: return null
        if (canonicalId != token.lowercase(Locale.US)) return null
        return synchronized(selectedPhotoLock) {
            if (activityDestroyed) return@synchronized null
            val file = File(File(cacheDir, "selected"), "$canonicalId.jpg")
            file.takeIf { it.isFile && it.length() > 0L && it.length() <= 10L * 1024L * 1024L }
        }
    }

    private fun decodeImageFile(file: File): Bitmap {
        if (!file.isFile || file.length() == 0L) {
            throw PhotoImportException("The photo file is empty. Choose it again or take a new photo.")
        }
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(file.absolutePath, bounds)
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) {
            throw PhotoImportException("Android could not decode that image. Try a JPEG or PNG photo.")
        }
        var sample = 1
        while (maxOf(bounds.outWidth, bounds.outHeight) / sample > 1600) sample *= 2
        val options = BitmapFactory.Options().apply { inSampleSize = sample.coerceAtLeast(1); inPreferredConfig = Bitmap.Config.ARGB_8888 }
        val decoded = BitmapFactory.decodeFile(file.absolutePath, options)
            ?: throw PhotoImportException("Android could not decode that image. Try a JPEG or PNG photo.")
        // EXIF orientation is useful but optional: some document providers supply images
        // without a seekable or complete EXIF stream, and that must not reject the photo.
        val rotation = runCatching { ExifInterface(file.absolutePath).rotationDegrees }.getOrDefault(0)
        if (rotation == 0) return decoded
        val matrix = Matrix().apply { postRotate(rotation.toFloat()) }
        return Bitmap.createBitmap(decoded, 0, 0, decoded.width, decoded.height, matrix, true).also {
            if (it !== decoded) decoded.recycle()
        }
    }

    private class PhotoImportException(message: String) : Exception(message)

    private fun postJavascript(script: String) {
        if (activityDestroyed || !::webView.isInitialized) return
        webView.post { if (!activityDestroyed) webView.evaluateJavascript(script, null) }
    }

    private fun dispatchFailure(message: String) {
        postJavascript("window.onNativePickerFailure && window.onNativePickerFailure(${JSONObject.quote(message)})")
    }

    private fun dispatchPickerClosed() {
        postJavascript("window.onNativePickerClosed && window.onNativePickerClosed()")
    }

    private fun dispatchAnalysisFailure(requestId: String, message: String) {
        postJavascript("window.onNativeFailure && window.onNativeFailure(${JSONObject.quote(requestId)}, ${JSONObject.quote(message)})")
    }

    private fun releaseSelectedPhoto(token: String): Boolean {
        val canonicalId = runCatching { UUID.fromString(token).toString() }.getOrNull() ?: return false
        if (canonicalId != token.lowercase(Locale.US)) return false
        val file = File(File(cacheDir, "selected"), "$canonicalId.jpg")
        synchronized(selectedPhotoLock) {
            if (activeSelectedPhoto == file) activeSelectedPhoto = null
            return !file.exists() || file.delete()
        }
    }

    private inner class LeafwiseBridge {
        @JavascriptInterface
        fun getClasses(): String = classifier.classesJson()

        @JavascriptInterface
        fun openGallery() = selectGallery()

        @JavascriptInterface
        fun openCamera() = capturePhoto()

        @JavascriptInterface
        fun releaseSelectedPhoto(token: String): Boolean = this@MainActivity.releaseSelectedPhoto(token)

        @JavascriptInterface
        fun openExternal(url: String) {
            val uri = Uri.parse(url)
            if (uri.scheme != "https") return
            runOnUiThread { runCatching { startActivity(Intent(Intent.ACTION_VIEW, uri)) } }
        }

        @JavascriptInterface
        fun analyzeImage(photoToken: String, saveToHistory: String, requestId: String) {
            if (activityDestroyed) return
            worker.execute {
                var bitmap: Bitmap? = null
                try {
                    if (activityDestroyed) return@execute
                    val bytes = synchronized(selectedPhotoLock) {
                        if (activityDestroyed) error("The app closed before analysis finished.")
                        val file = selectedPhotoFile(photoToken) ?: error("The selected photo expired. Choose it again.")
                        file.readBytes()
                    }
                    val decoded = BitmapFactory.decodeByteArray(bytes, 0, bytes.size) ?: error("The photo could not be decoded.")
                    bitmap = decoded
                    var result = classifier.predict(decoded)
                    decoded.recycle()
                    bitmap = null
                    if (activityDestroyed) return@execute
                    if (saveToHistory.equals("true", ignoreCase = true)) result = saveHistory(result, bytes)
                    val json = JSONObject.quote(result.toString())
                    postJavascript("window.onNativeAnalysis && window.onNativeAnalysis(${JSONObject.quote(requestId)}, JSON.parse($json))")
                } catch (error: Exception) {
                    if (!activityDestroyed) dispatchAnalysisFailure(requestId, error.message ?: "On-device analysis failed. Please try another photo.")
                } finally {
                    bitmap?.recycle()
                }
            }
        }

        @JavascriptInterface
        fun getHistory(): String {
            val stored = prefs.getString("items", "[]") ?: "[]"
            val original = JSONArray(stored)
            val safe = JSONArray()
            for (i in 0 until original.length()) {
                val item = original.optJSONObject(i) ?: continue
                val copy = JSONObject(item.toString())
                copy.put("image_available", copy.optString("photo_file").isNotBlank())
                copy.remove("photo_file")
                safe.put(copy)
            }
            return safe.toString()
        }

        @JavascriptInterface
        fun getHistoryImage(id: String): String {
            synchronized(prefs) {
                val items = JSONArray(prefs.getString("items", "[]") ?: "[]")
                for (i in 0 until items.length()) {
                    val item = items.optJSONObject(i) ?: continue
                    if (item.optString("id") == id) {
                        val fileName = item.optString("photo_file")
                        if (fileName.isBlank()) return ""
                        val file = File(filesDir, "diagnoses/$fileName")
                        if (!file.isFile || file.length() > 10L * 1024L * 1024L) return ""
                        return Base64.encodeToString(file.readBytes(), Base64.NO_WRAP)
                    }
                }
                return ""
            }
        }

        @JavascriptInterface
        fun deleteHistory(id: String): Boolean {
            synchronized(prefs) {
                val original = JSONArray(prefs.getString("items", "[]") ?: "[]")
                val kept = JSONArray()
                var deleted = false
                for (i in 0 until original.length()) {
                    val item = original.optJSONObject(i) ?: continue
                    if (item.optString("id") == id) {
                        val photo = item.optString("photo_file")
                        if (photo.isNotBlank()) {
                            val file = File(filesDir, "diagnoses/$photo")
                            if (file.exists() && !file.delete()) return false
                        }
                        deleted = true
                    } else kept.put(item)
                }
                if (deleted) prefs.edit().putString("items", kept.toString()).apply()
                return deleted
            }
        }
    }

    private fun timestampUtc(): String = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US).apply {
        timeZone = TimeZone.getTimeZone("UTC")
    }.format(Date())

    private fun saveHistory(result: JSONObject, imageBytes: ByteArray): JSONObject {
        synchronized(prefs) {
            val id = UUID.randomUUID().toString()
            val directory = File(filesDir, "diagnoses").apply { mkdirs() }
            val photoFile = File(directory, "$id.jpg")
            photoFile.writeBytes(imageBytes)
            val primary = result.getJSONObject("primary")
            val record = JSONObject()
                .put("id", id)
                .put("created_at", timestampUtc())
                .put("label", primary.getString("label"))
                .put("display_name", primary.getString("display_name"))
                .put("score", primary.getDouble("score"))
                .put("predictions", result.getJSONArray("predictions"))
                .put("care", result.getJSONObject("care"))
                .put("photo_file", photoFile.name)
            val items = JSONArray().put(record)
            val old = JSONArray(prefs.getString("items", "[]") ?: "[]")
            for (i in 0 until old.length().coerceAtMost(29)) {
                val previous = old.optJSONObject(i) ?: continue
                if (previous.optString("id") != id) items.put(previous)
            }
            for (i in 29 until old.length()) {
                old.optJSONObject(i)?.optString("photo_file")?.takeIf { it.isNotBlank() }?.let { File(directory, it).delete() }
            }
            prefs.edit().putString("items", items.toString()).apply()
            return JSONObject(result.toString()).put("saved", true).put("history_id", id).put("image_saved", true)
        }
    }

    override fun onDestroy() {
        activityDestroyed = true
        pickerInProgress = false
        pendingFileChooserCallback?.onReceiveValue(null)
        pendingFileChooserCallback = null
        pendingCameraFile?.delete()
        synchronized(selectedPhotoLock) {
            File(cacheDir, "selected").deleteRecursively()
            activeSelectedPhoto = null
        }
        cacheDir.listFiles()?.filter { it.isFile && it.name.startsWith("leafwise-") }?.forEach { it.delete() }
        if (::webView.isInitialized) {
            webView.removeJavascriptInterface("LeafwiseNative")
            webView.destroy()
        }
        worker.shutdownNow()
        super.onDestroy()
    }
}
