package com.leafwise.app

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Color
import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.nio.FloatBuffer
import kotlin.math.exp
import kotlin.math.max
import kotlin.math.min

/** Executes the exact bundled model locally. No network calls are made here. */
class OnDeviceClassifier(private val context: Context) {
    private val env: OrtEnvironment = OrtEnvironment.getEnvironment()
    private val labels: List<String> by lazy {
        val json = context.assets.open("class_names.json").bufferedReader().use { it.readText() }
        val array = JSONArray(json)
        List(array.length()) { array.getString(it) }.also {
            check(it.size == 38 && it.toSet().size == 38) { "The bundled model must have 38 unique labels." }
        }
    }
    private val careData: JSONObject by lazy {
        JSONObject(context.assets.open("treatment_advice.json").bufferedReader().use { it.readText() })
    }
    private val session: OrtSession by lazy {
        val bytes = context.assets.open("crop_disease.onnx").use { it.readBytes() }
        val options = OrtSession.SessionOptions().apply {
            setIntraOpNumThreads(2)
            setInterOpNumThreads(1)
        }
        env.createSession(bytes, options)
    }

    fun classesJson(): String {
        val items = JSONArray()
        labels.forEach { label -> items.put(classDetails(label)) }
        return JSONObject().put("count", labels.size).put("classes", items).toString()
    }

    fun predict(bitmap: Bitmap, topK: Int = 3): JSONObject {
        require(topK in 1..5) { "top_k must be between 1 and 5." }
        val inputName = session.inputNames.firstOrNull() ?: error("The model has no input tensor.")
        val input = preprocess(bitmap)
        val tensor = OnnxTensor.createTensor(env, FloatBuffer.wrap(input), longArrayOf(1, 3, 96, 96))
        val output = session.run(mapOf(inputName to tensor))
        val logits = try {
            @Suppress("UNCHECKED_CAST")
            val rows = output[0].value as Array<FloatArray>
            rows.first()
        } finally {
            output.close()
            tensor.close()
        }
        check(logits.size == labels.size) { "The model output does not match the bundled labels." }
        val maxLogit = logits.maxOrNull() ?: error("The model returned no scores.")
        val exps = logits.map { exp((it - maxLogit).toDouble()) }
        val total = exps.sum().coerceAtLeast(1e-20)
        val ranked = logits.indices.sortedByDescending { exps[it] }.take(topK)
        val predictions = JSONArray()
        ranked.forEach { index ->
            val label = labels[index]
            predictions.put(predictionRow(label, exps[index] / total))
        }
        val primary = predictions.getJSONObject(0)
        val care = classDetails(primary.getString("label"))
        return JSONObject()
            .put("primary", primary)
            .put("predictions", predictions)
            .put("care", care)
            .put("saved", false)
            .put("history_id", JSONObject.NULL)
            .put("image_saved", false)
            .put("notice", "On-device model scores rank the supported classes; they are not probabilities or a confirmed diagnosis.")
    }

    fun classDetails(label: String): JSONObject {
        val cropSplit = label.split("___", limit = 2)
        val crop = cropSplit.firstOrNull().orEmpty().replace('_', ' ')
        val disease = cropSplit.getOrNull(1)?.replace('_', ' ')?.trim().orEmpty()
        val entry = careData.optJSONObject(label) ?: JSONObject()
        val healthy = disease.equals("healthy", ignoreCase = true)
        return JSONObject()
            .put("label", label)
            .put("crop", crop)
            .put("disease", disease)
            .put("display_name", if (disease.isEmpty()) crop else "$crop — $disease")
            .put("healthy", healthy)
            .put("summary", entry.optString("summary"))
            .put("one_method", entry.optString("one_method"))
            .put("immediate_steps", entry.optJSONArray("immediate_steps") ?: JSONArray())
            .put("prevention", entry.optJSONArray("prevention") ?: JSONArray())
            .put("caution", entry.optString("caution"))
            .put("references", entry.optJSONArray("references") ?: JSONArray())
    }

    private fun predictionRow(label: String, score: Double): JSONObject {
        val details = classDetails(label)
        return JSONObject()
            .put("label", label)
            .put("crop", details.getString("crop"))
            .put("disease", details.getString("disease"))
            .put("display_name", details.getString("display_name"))
            .put("score", score)
            .put("healthy", details.getBoolean("healthy"))
    }

    private fun preprocess(source: Bitmap): FloatArray {
        val shortEdge = 112
        val width = source.width
        val height = source.height
        val scale = shortEdge.toFloat() / min(width, height).toFloat()
        val resizedWidth = max(shortEdge, (width * scale).toInt())
        val resizedHeight = max(shortEdge, (height * scale).toInt())
        val resized = Bitmap.createScaledBitmap(source, resizedWidth, resizedHeight, true)
        val left = (resizedWidth - 96) / 2
        val top = (resizedHeight - 96) / 2
        val pixels = IntArray(96 * 96)
        resized.getPixels(pixels, 0, 96, left, top, 96, 96)
        if (resized !== source) resized.recycle()
        val plane = 96 * 96
        val result = FloatArray(3 * plane)
        val means = floatArrayOf(.485f, .456f, .406f)
        val stds = floatArrayOf(.229f, .224f, .225f)
        for (i in pixels.indices) {
            val color = pixels[i]
            result[i] = ((Color.red(color) / 255f) - means[0]) / stds[0]
            result[plane + i] = ((Color.green(color) / 255f) - means[1]) / stds[1]
            result[2 * plane + i] = ((Color.blue(color) / 255f) - means[2]) / stds[2]
        }
        return result
    }
}
