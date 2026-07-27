package com.smartdesk.tablet.model

import org.json.JSONObject

object AndroidEvent {
    fun registeredPeople(personIds: List<String>): String {
        val people = org.json.JSONArray()
        personIds.forEach(people::put)
        return JSONObject()
            .put("type", "registered_people")
            .put(
                "data",
                JSONObject()
                    .put("personIds", people)
                    .put("count", personIds.size)
            )
            .toString()
    }

    fun cameraStatus(status: String): String =
        JSONObject()
            .put("type", "camera_status")
            .put(
                "data",
                JSONObject()
                    .put("status", status)
                    .put("timestamp", System.currentTimeMillis())
            )
            .toString()

    fun faceDetectionStatus(result: FaceDetectionResult): String =
        JSONObject()
            .put("type", "face_detection_status")
            .put(
                "data",
                JSONObject()
                    .put("status", result.status)
                    .put("faceCount", result.faceCount)
                    .put("processingTimeMs", result.processingTimeMs)
                    .put("timestamp", System.currentTimeMillis())
            )
            .toString()

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
            .put("timestamp", System.currentTimeMillis())

        return JSONObject()
            .put("type", "identity_status")
            .put("data", data)
            .toString()
    }

    fun error(
        code: String,
        message: String,
        cameraStillRunning: Boolean = false
    ): String =
        JSONObject()
            .put("type", "error")
            .put(
                "data",
                JSONObject()
                    .put("code", code)
                    .put("message", message)
                    .put("cameraStillRunning", cameraStillRunning)
            )
            .toString()
}
