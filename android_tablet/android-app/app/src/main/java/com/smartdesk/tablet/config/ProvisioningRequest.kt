package com.smartdesk.tablet.config

import com.google.gson.Gson

data class ProvisioningRequest(
    val seatId: Int,
    val endpoints: HostConfiguration,
    val provisioningToken: String,
    val maintenancePin: String?,
    val replaceExisting: Boolean
) {
    companion object {
        private val gson = Gson()

        fun parse(json: String, requireMaintenancePin: Boolean): ProvisioningRequest {
            val payload = runCatching {
                gson.fromJson(json, Payload::class.java)
            }.getOrElse {
                throw IllegalArgumentException("Provisioning request must be valid JSON", it)
            } ?: throw IllegalArgumentException(
                "Provisioning request must be a JSON object"
            )
            require(payload.seatId in 1..9) {
                "seatId must be an integer between 1 and 9"
            }
            val token = payload.provisioningToken.orEmpty().trim()
            require(token.length in 24..256 && token.all { !it.isWhitespace() }) {
                "Provisioning token must contain 24-256 non-whitespace characters"
            }
            val pin = payload.maintenancePin?.trim()?.takeIf(String::isNotBlank)
            if (requireMaintenancePin) {
                require(pin != null && pin.length in 6..12 && pin.all(Char::isDigit)) {
                    "Maintenance PIN must contain 6-12 digits"
                }
            }
            return ProvisioningRequest(
                seatId = payload.seatId,
                endpoints = HostConfiguration.parse(
                    centralHost = payload.centralHost.orEmpty(),
                    serverOverride = payload.serverBaseUrl,
                    frontendOverride = payload.frontendBaseUrl
                ),
                provisioningToken = token,
                maintenancePin = pin,
                replaceExisting = payload.replaceExisting
            )
        }

        private data class Payload(
            val seatId: Int = 0,
            val centralHost: String? = null,
            val serverBaseUrl: String? = null,
            val frontendBaseUrl: String? = null,
            val provisioningToken: String? = null,
            val maintenancePin: String? = null,
            val replaceExisting: Boolean = false
        )
    }
}
