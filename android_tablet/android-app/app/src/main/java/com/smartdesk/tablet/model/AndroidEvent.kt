package com.smartdesk.tablet.model

import android.util.Base64
import org.json.JSONObject
import java.util.UUID

object AndroidEvent {
    fun event(type: String, data: JSONObject): String =
        JSONObject()
            .put("schemaVersion", 1)
            .put("eventId", UUID.randomUUID().toString())
            .put("type", type)
            .put("timestamp", System.currentTimeMillis())
            .put("data", data)
            .toString()

    fun registeredPeople(personIds: List<String>): String {
        val people = org.json.JSONArray()
        personIds.forEach(people::put)
        return event(
            "registered_people",
            JSONObject()
                .put("personIds", people)
                .put("count", personIds.size)
        )
    }

    fun cameraStatus(status: String): String =
        event(
            "camera_status",
            JSONObject().put("status", status)
        )

    fun appLifecycle(state: String, reason: String? = null): String =
        event(
            "app_lifecycle",
            JSONObject()
                .put("state", state)
                .also { payload ->
                    if (reason != null) {
                        payload.put("reason", reason)
                    }
                }
        )

    fun microphoneStatus(status: String): String =
        event(
            "microphone_status",
            JSONObject().put("status", status)
        )

    fun microphoneAudio(pcm16: ByteArray): String =
        event(
            "microphone_audio",
            JSONObject()
                .put("encoding", "pcm_s16le")
                .put("sampleRate", 16_000)
                .put("channels", 1)
                .put("pcm16Base64", Base64.encodeToString(pcm16, Base64.NO_WRAP))
        )

    fun faceDetectionStatus(result: FaceDetectionResult): String =
        event(
            "face_detection_status",
            JSONObject()
                .put("status", result.status)
                .put("faceCount", result.faceCount)
                .put("processingTimeMs", result.processingTimeMs)
        )

    fun identityStatus(result: IdentityStatus): String {
        val data = JSONObject()
            .put("mode", result.mode)
            .put("status", result.status)
            .put("personId", result.personId ?: JSONObject.NULL)
            .put("sampleCount", result.sampleCount)
            .put("requiredSamples", result.requiredSamples)
            .put("captureStage", result.captureStage)
            .put("stageSampleCount", result.stageSampleCount)
            .put("stageRequiredSamples", result.stageRequiredSamples)
            .put("registeredCount", result.registeredCount)
            .put("similarity", result.similarity ?: JSONObject.NULL)
            .put("threshold", result.threshold ?: JSONObject.NULL)
            .put(
                "top1PersonId",
                result.top1PersonId ?: JSONObject.NULL
            )
            .put("top1Score", result.top1Score ?: JSONObject.NULL)
            .put(
                "top2PersonId",
                result.top2PersonId ?: JSONObject.NULL
            )
            .put("top2Score", result.top2Score ?: JSONObject.NULL)
            .put("margin", result.margin ?: JSONObject.NULL)
            .put("thresholdStatus", result.thresholdStatus)
            .put("verificationLevel", result.verificationLevel)
            .put(
                "modelVersion",
                result.modelVersion ?: JSONObject.NULL
            )
            .put("matchStreak", result.matchStreak)
            .put("rejectStreak", result.rejectStreak)
            .put(
                "processingTimeMs",
                result.processingTimeMs ?: JSONObject.NULL
            )
            .put("message", result.message)

        return event("identity_status", data)
    }

    fun error(
        code: String,
        message: String,
        cameraStillRunning: Boolean = false
    ): String =
        event(
            "error",
            JSONObject()
                .put("code", code)
                .put("message", message)
                .put("cameraStillRunning", cameraStillRunning)
        )
}
