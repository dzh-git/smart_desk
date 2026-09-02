package com.smartdesk.tablet.recognition

import com.smartdesk.tablet.config.DeviceConfig
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL

class FaceTemplateSyncClient(
    private val crypto: FaceTransportCrypto = FaceTransportCrypto(),
    private val connectTimeoutMs: Int = 5_000,
    private val readTimeoutMs: Int = 15_000
) {
    fun publishFromHost(
        config: DeviceConfig,
        personId: String,
        generated: FacePhotoImporter.Generated,
        manager: FaceRecognitionManager
    ): JSONObject {
        require(config.seatId == 1) { "只有主持人平板可以发布人脸模板" }
        val template = requireNotNull(generated.template) {
            generated.result.message
        }
        val keyData = request(
            "GET",
            "${config.serverUrl.trimEnd('/')}/api/face-templates/transport-key"
        ).getJSONObject("data")
        val model = manager.modelConfig()
        val threshold = requireNotNull(manager.currentThreshold()) {
            "当前模型尚未确认原型阈值，请先在主持人人脸模板管理页确认"
        }
        require(manager.currentThresholdStatus() == ThresholdStatus.PROVISIONAL) {
            "当前模型或处理流水线已变化，请在主持人人脸模板管理页重新确认原型阈值"
        }
        val payload = JSONObject()
            .put("personId", personId)
            .put("modelVersion", model.modelVersion)
            .put("modelHash", model.modelSha256)
            .put("pipelineVersion", model.pipelineVersion)
            .put("embeddingDimension", model.embeddingDimension)
            .put("normalSampleCount", template.normalSampleCount)
            .put("fillLightSampleCount", template.fillLightSampleCount)
            .put("normalEmbedding", template.normalEmbedding.toJson())
            .put("fillLightEmbedding", template.fillLightEmbedding.toJson())
            .put("threshold", threshold)
            .put("thresholdStatus", "PROVISIONAL")
        val envelope = crypto.encryptForServer(
            payload,
            keyData.getString("publicKeyPem")
        )
        val encodedPerson = URI(null, null, personId, null).rawPath
        return request(
            "PUT",
            "${config.serverUrl.trimEnd('/')}/api/face-templates/$encodedPerson",
            JSONObject()
                .put("deviceId", config.deviceId)
                .put("envelope", envelope),
            config.deviceToken
        ).getJSONObject("data")
    }

    fun syncActiveMeeting(
        config: DeviceConfig,
        expectedMeetingId: Int,
        manager: FaceRecognitionManager
    ): JSONObject {
        require(config.seatId in 2..9) { "主持人平板不需要同步参会者模板" }
        val devicePath = URI(null, null, config.deviceId, null).rawPath
        var reportedRevision = 0
        var reportedCount = 0
        return try {
            request(
            "PUT",
            "${config.serverUrl.trimEnd('/')}/api/tablet-devices/$devicePath/face-transport-key",
            JSONObject()
                .put("seatId", config.seatId)
                .put("publicKeyPem", crypto.publicKeyPem()),
            config.deviceToken
        )
        val response = request(
            "GET",
            "${config.serverUrl.trimEnd('/')}/api/tablet-devices/$devicePath/face-template-bundle?seatId=${config.seatId}",
            token = config.deviceToken
        ).getJSONObject("data")
        val meetingId = response.getInt("meetingId")
        val revision = response.getInt("templateSetRevision")
        reportedRevision = revision
        reportedCount = response.getInt("templateCount")
        require(meetingId == expectedMeetingId) {
            "中央模板属于会议$meetingId，不是当前会议$expectedMeetingId"
        }
        val payload = crypto.decryptFromServer(response.getJSONObject("envelope"))
        require(payload.getInt("meetingId") == meetingId) { "会议模板包标识不一致" }
        val expectedPersonId = payload.getString("expectedPersonId")
        val templatesJson = payload.getJSONArray("templates")
        val templates = List(templatesJson.length()) { index ->
            val item = templatesJson.getJSONObject(index)
            PersonFaceTemplate(
                personId = item.getString("personId"),
                normalSampleCount = item.getInt("normalSampleCount"),
                fillLightSampleCount = item.getInt("fillLightSampleCount"),
                normalEmbedding = item.getJSONArray("normalEmbedding").toFloatArray(),
                fillLightEmbedding = item.getJSONArray("fillLightEmbedding").toFloatArray(),
                createdAt = item.optLong("createdAt", System.currentTimeMillis())
            )
        }
        require(templates.size == 1 && templates.single().personId == expectedPersonId) {
            "会议模板包与当前席位分配人员不一致"
        }
        manager.installManagedTemplates(
            meetingId = meetingId,
            revision = revision,
            templates = templates,
            threshold = payload.getDouble("threshold").toFloat(),
            thresholdStatus = ThresholdStatus.valueOf(payload.getString("thresholdStatus")),
            modelHash = payload.getString("modelHash"),
            pipelineVersion = payload.getInt("pipelineVersion")
        )
        acknowledge(
            config,
            devicePath,
            meetingId,
            revision,
            templates.size,
            "SYNCED",
            null
        )
            JSONObject()
                .put("meetingId", meetingId)
                .put("templateSetRevision", revision)
                .put("templateCount", templates.size)
                .put("expectedPersonId", expectedPersonId)
                .put("status", "SYNCED")
        } catch (error: Exception) {
            runCatching {
                acknowledge(
                    config,
                    devicePath,
                    expectedMeetingId,
                    reportedRevision,
                    reportedCount,
                    "ERROR",
                    error.message?.take(300)
                )
            }
            throw error
        }
    }

    private fun acknowledge(
        config: DeviceConfig,
        devicePath: String,
        meetingId: Int,
        revision: Int,
        count: Int,
        status: String,
        error: String?
    ) {
        request(
            "POST",
            "${config.serverUrl.trimEnd('/')}/api/tablet-devices/$devicePath/face-template-sync-ack",
            JSONObject()
                .put("seatId", config.seatId)
                .put("meetingId", meetingId)
                .put("templateSetRevision", revision)
                .put("templateCount", count)
                .put("status", status)
                .put("error", error ?: JSONObject.NULL),
            config.deviceToken
        )
    }

    private fun request(
        method: String,
        url: String,
        payload: JSONObject? = null,
        token: String? = null
    ): JSONObject {
        val connection = URL(url).openConnection() as HttpURLConnection
        return try {
            connection.requestMethod = method
            connection.connectTimeout = connectTimeoutMs
            connection.readTimeout = readTimeoutMs
            connection.useCaches = false
            connection.setRequestProperty("Accept", "application/json")
            token?.let {
                connection.setRequestProperty("X-SmartDesk-Device-Token", it)
            }
            if (payload != null) {
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json")
                connection.outputStream.bufferedWriter(Charsets.UTF_8).use {
                    it.write(payload.toString())
                }
            }
            val status = connection.responseCode
            val stream = if (status in 200..299) connection.inputStream else connection.errorStream
            val body = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
            val json = JSONObject(body)
            if (status !in 200..299 || !json.optBoolean("success", false)) {
                throw IllegalStateException(
                    listOf(
                        json.optString("error_code"),
                        json.optString("message")
                    ).filter(String::isNotBlank).joinToString(": ")
                )
            }
            json
        } finally {
            connection.disconnect()
        }
    }

    private fun FloatArray.toJson(): JSONArray =
        JSONArray().also { target -> forEach(target::put) }

    private fun JSONArray.toFloatArray(): FloatArray =
        FloatArray(length()) { index -> getDouble(index).toFloat() }
}
