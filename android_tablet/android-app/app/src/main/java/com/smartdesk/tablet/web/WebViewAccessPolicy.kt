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

    fun isHostFaceTemplatesPage(
        currentUrl: String?,
        config: DeviceConfig?
    ): Boolean {
        if (currentUrl.isNullOrBlank() || config == null || config.seatId != 1) {
            return false
        }
        val current = parseHttpUri(currentUrl) ?: return false
        val frontend = parseHttpUri(config.frontendUrl) ?: return false
        return sameOrigin(current, frontend) &&
            current.path.trimEnd('/') == "/seat/1/face-templates"
    }

    fun isTrustedHostConsolePage(
        currentUrl: String?,
        config: DeviceConfig?
    ): Boolean {
        if (currentUrl.isNullOrBlank() || config == null || config.seatId != 1) {
            return false
        }
        val current = parseHttpUri(currentUrl) ?: return false
        val frontend = parseHttpUri(config.frontendUrl) ?: return false
        return sameOrigin(current, frontend) &&
            current.path.trimEnd('/') == "/host"
    }

    fun isTrustedOperationalPage(
        currentUrl: String?,
        config: DeviceConfig?
    ): Boolean =
        isTrustedSeatPage(currentUrl, config) ||
            isTrustedHostConsolePage(currentUrl, config)

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

    fun mayOpenTemplatePhotoChooser(
        currentPageUrl: String?,
        config: DeviceConfig?,
        maintenanceAuthorized: Boolean
    ): Boolean =
        maintenanceAuthorized &&
            isHostFaceTemplatesPage(currentPageUrl, config)

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
            isTrustedOperationalPage(currentPageUrl, config)

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
