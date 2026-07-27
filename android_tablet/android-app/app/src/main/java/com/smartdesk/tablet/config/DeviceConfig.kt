package com.smartdesk.tablet.config

import com.google.gson.Gson
import org.json.JSONObject
import java.net.URI

data class DeviceConfig(
    val seatId: Int,
    val deviceId: String,
    val serverUrl: String,
    val frontendUrl: String,
    val deviceToken: String
) {
    fun seatPageUrl(): String = "$frontendUrl/seat/$seatId"

    fun toJson(includeSecret: Boolean = false): JSONObject =
        JSONObject()
            .put("seatId", seatId)
            .put("deviceId", deviceId)
            .put("serverBaseUrl", serverUrl)
            .put("frontendBaseUrl", frontendUrl)
            .put("deviceTokenConfigured", deviceToken.isNotBlank())
            .also { payload ->
                if (includeSecret) {
                    payload.put("deviceToken", deviceToken)
                }
            }

    companion object {
        private val deviceIdPattern = Regex("[A-Za-z0-9._-]{3,64}")
        private val gson = Gson()

        fun parse(
            json: String,
            fallbackDeviceToken: String? = null
        ): DeviceConfig {
            val payload = runCatching {
                gson.fromJson(json, DeviceConfigPayload::class.java)
            }.getOrElse {
                throw IllegalArgumentException(
                    "Device configuration must be valid JSON",
                    it
                )
            } ?: throw IllegalArgumentException(
                "Device configuration must be a JSON object"
            )
            val seatId = payload.seatId
            require(seatId in 1..9) {
                "seatId must be an integer between 1 and 9"
            }

            val deviceId = payload.deviceId.orEmpty().trim()
            require(deviceIdPattern.matches(deviceId)) {
                "deviceId must contain 3-64 letters, numbers, dots, underscores, or hyphens"
            }

            val deviceToken = (
                payload.deviceToken?.trim()
                    ?.takeIf(String::isNotBlank)
                    ?: fallbackDeviceToken
                ).orEmpty()
            require(
                deviceToken.length in 24..256 &&
                    deviceToken.all { !it.isWhitespace() }
            ) {
                "deviceToken must contain 24-256 non-whitespace characters"
            }

            return DeviceConfig(
                seatId = seatId,
                deviceId = deviceId,
                serverUrl = normalizeBaseUrl(
                    payload.serverBaseUrl
                        ?: payload.serverUrl.orEmpty(),
                    "serverBaseUrl"
                ),
                frontendUrl = normalizeBaseUrl(
                    payload.frontendBaseUrl
                        ?: payload.frontendUrl.orEmpty(),
                    "frontendBaseUrl"
                ),
                deviceToken = deviceToken
            )
        }

        private fun normalizeBaseUrl(value: String, field: String): String {
            val candidate = value.trim().trimEnd('/')
            val uri = runCatching { URI(candidate) }.getOrElse {
                throw IllegalArgumentException("$field must be a valid URL")
            }
            require(uri.scheme == "http" || uri.scheme == "https") {
                "$field must use http or https"
            }
            require(!uri.host.isNullOrBlank()) {
                "$field must include a host"
            }
            require(uri.userInfo == null && uri.query == null && uri.fragment == null) {
                "$field must not include credentials, a query, or a fragment"
            }
            return candidate
        }

        private data class DeviceConfigPayload(
            val seatId: Int = 0,
            val deviceId: String? = null,
            val deviceToken: String? = null,
            val serverBaseUrl: String? = null,
            val frontendBaseUrl: String? = null,
            val serverUrl: String? = null,
            val frontendUrl: String? = null
        )
    }
}
