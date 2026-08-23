package com.smartdesk.tablet.provisioning

import com.smartdesk.tablet.config.DeviceConfig
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL

data class TabletBinding(
    val deviceId: String,
    val seatId: Int,
    val seatAlias: String,
    val enabled: Boolean,
    val identityMode: String
)

sealed class TabletApiResult {
    data class Success(val binding: TabletBinding) : TabletApiResult()
    data class Conflict(val code: String, val message: String) : TabletApiResult()
    data class Rejected(val code: String, val message: String) : TabletApiResult()
    data class ServerError(val message: String) : TabletApiResult()
    data object Offline : TabletApiResult()
}

class TabletDeviceClient(
    private val connectTimeoutMs: Int = 5_000,
    private val readTimeoutMs: Int = 5_000
) {
    fun provision(
        serverBaseUrl: String,
        deviceId: String,
        seatId: Int,
        deviceToken: String,
        provisioningToken: String,
        replaceExisting: Boolean
    ): TabletApiResult {
        val payload = JSONObject()
            .put("deviceId", deviceId)
            .put("seatId", seatId)
            .put("deviceToken", deviceToken)
            .put("replaceExisting", replaceExisting)
        val response = post(
            url = "${serverBaseUrl.trimEnd('/')}/api/tablet-devices/provision",
            payload = payload,
            headers = mapOf(
                "X-SmartDesk-Provisioning-Token" to provisioningToken
            )
        )
        return response.toResult(conflictCode = "DEVICE_SEAT_ALREADY_BOUND")
    }

    fun validate(config: DeviceConfig, appVersion: String): TabletApiResult {
        val payload = JSONObject()
            .put("seatId", config.seatId)
            .put("appVersion", appVersion)
        val encodedDeviceId = URI(null, null, config.deviceId, null).rawPath
        val response = post(
            url = (
                "${config.serverUrl.trimEnd('/')}/api/tablet-devices/" +
                    "$encodedDeviceId/validate"
                ),
            payload = payload,
            headers = mapOf(
                "X-SmartDesk-Device-Token" to config.deviceToken
            )
        )
        return response.toResult()
    }

    private fun post(
        url: String,
        payload: JSONObject,
        headers: Map<String, String>
    ): RawResponse {
        val connection = try {
            URL(url).openConnection() as HttpURLConnection
        } catch (_: Exception) {
            return RawResponse.offline()
        }
        return try {
            connection.requestMethod = "POST"
            connection.connectTimeout = connectTimeoutMs
            connection.readTimeout = readTimeoutMs
            connection.useCaches = false
            connection.doOutput = true
            connection.setRequestProperty("Accept", "application/json")
            connection.setRequestProperty("Content-Type", "application/json")
            headers.forEach { (name, value) ->
                connection.setRequestProperty(name, value)
            }
            connection.outputStream.bufferedWriter(Charsets.UTF_8).use {
                it.write(payload.toString())
            }
            val status = connection.responseCode
            val stream = if (status in 200..299) {
                connection.inputStream
            } else {
                connection.errorStream
            }
            val body = stream?.bufferedReader(Charsets.UTF_8)?.use {
                it.readText().take(MAX_BODY_CHARS)
            }.orEmpty()
            RawResponse(status, body, offline = false)
        } catch (_: Exception) {
            RawResponse.offline()
        } finally {
            connection.disconnect()
        }
    }

    private data class RawResponse(
        val statusCode: Int,
        val body: String,
        val offline: Boolean
    ) {
        fun toResult(conflictCode: String? = null): TabletApiResult {
            if (offline) return TabletApiResult.Offline
            val payload = runCatching { JSONObject(body) }.getOrNull()
            if (statusCode in 200..299) {
                val data = payload?.optJSONObject("data")
                    ?: return TabletApiResult.ServerError(
                        "中央主机返回了无效的设备响应"
                    )
                val deviceId = data.optString("deviceId")
                val seatId = data.optInt("seatId", 0)
                val seatAlias = data.optString("seatAlias")
                if (deviceId.isBlank() || seatId !in 1..9 || seatAlias.isBlank()) {
                    return TabletApiResult.ServerError(
                        "中央主机返回的设备绑定不完整"
                    )
                }
                return TabletApiResult.Success(
                    TabletBinding(
                        deviceId = deviceId,
                        seatId = seatId,
                        seatAlias = seatAlias,
                        enabled = data.optBoolean("enabled", false),
                        identityMode = data.optString("identityMode")
                            .takeIf { it == "formal" || it == "debug" }
                            ?: "formal"
                    )
                )
            }
            val code = payload?.optString("error_code")
                ?.takeIf(String::isNotBlank)
                ?: "DEVICE_SERVER_ERROR"
            val message = payload?.optString("message")
                ?.takeIf(String::isNotBlank)
                ?: "中央主机拒绝了设备请求"
            if (conflictCode != null && code == conflictCode) {
                return TabletApiResult.Conflict(code, message)
            }
            return if (statusCode in 400..499) {
                TabletApiResult.Rejected(code, message)
            } else {
                TabletApiResult.ServerError(message)
            }
        }

        companion object {
            fun offline(): RawResponse = RawResponse(0, "", offline = true)
        }
    }

    private companion object {
        const val MAX_BODY_CHARS = 16_384
    }
}
