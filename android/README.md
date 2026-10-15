# Leafwise Android

This is a native Android application shell with a local WebView interface and Kotlin ONNX Runtime inference. The UI, labels, model, and care data are bundled in the APK, so photo prediction works offline and does not upload a phone photo.

## Build

Use Android Studio with Android SDK platform 35 and Java 17 or newer, or use the included Gradle wrapper from this directory:

```bash
./gradlew assembleDebug
```

The web UI and shared model files are consumed directly from `../web` and `../shared` by the Android build; there are no duplicate model files to keep synchronized. The debug APK is written to `app/build/outputs/apk/debug/app-debug.apk`.

A debug build is for installation/testing. A signed release build requires a private signing key owned by the app publisher; no release key is included.
