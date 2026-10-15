# Android ONNX Runtime dependency

The Android app pins ONNX Runtime 1.20.0, the published Maven Central AAR. The official ONNX Runtime install guide specifies the Android Gradle coordinate `com.microsoft.onnxruntime:onnxruntime-android` and Maven Central as its repository [1]. Sonatype's component page confirms the 1.20.0 artifact, Android AAR packaging, and exact Maven coordinate [2].

The initial build could not resolve 1.20.1 from Google Maven or Maven Central; the dependency was corrected to 1.20.0, which is confirmed by the published component metadata.

[1]: https://onnxruntime.ai/docs/install/ "ONNX Runtime installation guide"
[2]: https://central.sonatype.com/artifact/com.microsoft.onnxruntime/onnxruntime-android/1.20.0 "Maven Central ONNX Runtime Android 1.20.0"
