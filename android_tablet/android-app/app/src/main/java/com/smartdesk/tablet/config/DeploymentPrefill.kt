package com.smartdesk.tablet.config

data class DeploymentPrefill(
    val seatId: Int,
    val centralHost: String
) {
    companion object {
        fun parse(
            seatIdValue: String?,
            centralHostValue: String?
        ): DeploymentPrefill? {
            val seatId = seatIdValue?.toIntOrNull()
                ?.takeIf { it in 1..9 }
                ?: return null
            val centralHost = runCatching {
                HostConfiguration.parse(centralHostValue.orEmpty()).centralHost
            }.getOrNull() ?: return null
            return DeploymentPrefill(seatId, centralHost)
        }
    }
}
