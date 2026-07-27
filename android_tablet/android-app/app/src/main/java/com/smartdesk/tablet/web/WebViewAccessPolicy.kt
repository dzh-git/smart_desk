package com.smartdesk.tablet.web

import com.smartdesk.tablet.config.DeviceConfig
import java.net.URI

/**
 * Pure URL/resource policy shared by WebView navigation, privileged Bridge
 * access, and microphone permission handling.
 */
object WebViewAccessPolicy {
    const val AUDIO_CAPTURE_RESOURCE =
        "android.webkit.resource.AUDIO_CAPTURE"

    fun isTrustedSeatPage(
        currentUrl: String?,
        config: DeviceConfig?
    ): Boolean {
        if (currentUrl.isNullOrBlank() || config == null) {
            return false
        }
        val current = parseHttpUri(currentUrl) ?: return false
        val frontend = parseHttpUri(config.frontendUrl) ?: return false
        return sameOrigin(current, frontend) &&
            current.path.trimEnd('/') == "/seat/${config.seatId}"
    }

    fun isTrustedFrontendOrigin(
        originUrl: String?,
        config: DeviceConfig?
    ): Boolean {
        if (originUrl.isNullOrBlank() || config == null) {
            return false
        }
        val origin = parseHttpUri(originUrl) ?: return false
        val frontend = parseHttpUri(config.frontendUrl) ?: return false
        return sameOrigin(origin, frontend)
    }

    fun mayGrantMicrophone(
        originUrl: String?,
        currentPageUrl: String?,
        requestedResources: Collection<String>,
        config: DeviceConfig?,
        androidPermissionGranted: Boolean
    ): Boolean =
        androidPermissionGranted &&
            requestedResources.isNotEmpty() &&
            requestedResources.all { it == AUDIO_CAPTURE_RESOURCE } &&
            isTrustedFrontendOrigin(originUrl, config) &&
            isTrustedSeatPage(currentPageUrl, config)

    private fun parseHttpUri(value: String): URI? =
        runCatching { URI(value) }
            .getOrNull()
            ?.takeIf {
                (it.scheme == "http" || it.scheme == "https") &&
                    !it.host.isNullOrBlank() &&
                    it.userInfo == null
            }

    private fun sameOrigin(left: URI, right: URI): Boolean =
        left.scheme.equals(right.scheme, ignoreCase = true) &&
            left.host.equals(right.host, ignoreCase = true) &&
            effectivePort(left) == effectivePort(right)

    private fun effectivePort(uri: URI): Int =
        when {
            uri.port != -1 -> uri.port
            uri.scheme.equals("https", ignoreCase = true) -> 443
            else -> 80
        }
}
