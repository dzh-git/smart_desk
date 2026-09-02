package com.smartdesk.tablet.recognition

import android.content.Context
import android.graphics.Bitmap
import com.smartdesk.tablet.BuildConfig
import org.json.JSONObject
import java.io.File
import java.util.concurrent.atomic.AtomicLong

class FaceDiagnostics(private val context: Context) {
    private val preferences = context.getSharedPreferences(
        PREFERENCES_NAME,
        Context.MODE_PRIVATE
    )
    private val sequence = AtomicLong(0)

    fun isEnabled(): Boolean =
        BuildConfig.DEBUG &&
            preferences.getBoolean(ENABLED_KEY, false)

    fun setEnabled(enabled: Boolean) {
        preferences.edit()
            .putBoolean(ENABLED_KEY, BuildConfig.DEBUG && enabled)
            .apply()
    }

    fun clear() {
        diagnosticsDirectory().deleteRecursively()
    }

    fun recordFrame(
        bitmap: Bitmap,
        mode: String,
        stage: TemplateKind,
        personId: String?,
        sampleIndex: Int,
        brightness: Float,
        sharpness: Float,
        embedding: FloatArray
    ) {
        if (!isEnabled()) {
            return
        }
        val directory = diagnosticsDirectory().apply { mkdirs() }
        val id = "${System.currentTimeMillis()}-${sequence.incrementAndGet()}"
        val imageFile = File(directory, "$id.png")
        imageFile.outputStream().use { stream ->
            check(bitmap.compress(Bitmap.CompressFormat.PNG, 100, stream)) {
                "诊断人脸图保存失败"
            }
        }
        append(
            JSONObject()
                .put("type", "frame")
                .put("id", id)
                .put("mode", mode)
                .put("stage", stage.name)
                .put("personId", personId ?: JSONObject.NULL)
                .put("sampleIndex", sampleIndex)
                .put("brightness", brightness)
                .put("sharpness", sharpness)
                .put("embeddingDimension", embedding.size)
                .put("image", imageFile.name)
                .put("timestamp", System.currentTimeMillis())
        )
    }

    fun recordMatch(result: FaceMatchResult) {
        if (!isEnabled()) {
            return
        }
        append(
            JSONObject()
                .put("type", "match")
                .put("stage", result.templateKind.name)
                .put("status", result.status)
                .put("top1PersonId", result.top1PersonId)
                .put("top1Score", result.top1Score)
                .put("top2PersonId", result.top2PersonId)
                .put("top2Score", result.top2Score)
                .put("margin", result.margin)
                .put("agreeingFrames", result.agreeingFrames)
                .put("removedFrameIndex", result.removedFrameIndex)
                .put("verificationLevel", result.verificationLevel)
                .put("timestamp", System.currentTimeMillis())
        )
    }

    fun directoryPath(): String = diagnosticsDirectory().absolutePath

    private fun append(payload: JSONObject) {
        val directory = diagnosticsDirectory().apply { mkdirs() }
        File(directory, METRICS_FILE).appendText(
            payload.toString() + "\n",
            Charsets.UTF_8
        )
    }

    private fun diagnosticsDirectory(): File =
        File(context.filesDir, DIRECTORY_NAME)

    private companion object {
        const val PREFERENCES_NAME = "face_diagnostics_private"
        const val ENABLED_KEY = "enabled"
        const val DIRECTORY_NAME = "face_diagnostics"
        const val METRICS_FILE = "metrics.jsonl"
    }
}
