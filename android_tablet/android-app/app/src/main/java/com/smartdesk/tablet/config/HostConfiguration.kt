package com.smartdesk.tablet.config

import java.net.URI

data class HostConfiguration(
    val centralHost: String,
    val serverUrl: String,
    val frontendUrl: String
) {
    companion object {
        fun parse(
            centralHost: String,
            serverOverride: String? = null,
            frontendOverride: String? = null
        ): HostConfiguration {
            val base = normalizeCentralHost(centralHost)
            return HostConfiguration(
                centralHost = base,
                serverUrl = normalizeEndpoint(
                    serverOverride?.takeIf(String::isNotBlank)
                        ?: "$base:8000",
                    "serverBaseUrl"
                ),
                frontendUrl = normalizeEndpoint(
                    frontendOverride?.takeIf(String::isNotBlank)
                        ?: "$base:5173",
                    "frontendBaseUrl"
                )
            )
        }

        private fun normalizeCentralHost(value: String): String {
            val trimmed = value.trim().trimEnd('/')
            val candidate = if (trimmed.contains("://")) {
                trimmed
            } else {
                "http://$trimmed"
            }
            val uri = parseUri(candidate, "centralHost")
            require(uri.port == -1) {
                "centralHost must not include a port; use advanced URLs"
            }
            require(uri.path.isNullOrBlank()) {
                "centralHost must not include a path"
            }
            return "${uri.scheme}://${uri.host}"
        }

        private fun normalizeEndpoint(value: String, field: String): String {
            val candidate = value.trim().trimEnd('/')
            parseUri(candidate, field)
            return candidate
        }

        private fun parseUri(value: String, field: String): URI {
            val uri = runCatching { URI(value) }.getOrElse {
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
            return uri
        }
    }
}
