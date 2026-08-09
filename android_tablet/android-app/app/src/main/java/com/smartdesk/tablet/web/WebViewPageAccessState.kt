package com.smartdesk.tablet.web

import com.smartdesk.tablet.config.DeviceConfig
import java.util.concurrent.atomic.AtomicReference

/**
 * Thread-safe snapshot of the WebView's main-frame URL.
 *
 * WebViewClient callbacks update this state on the main thread. JavaScript
 * interface callbacks run on WebView's JavaBridge thread and must consult this
 * snapshot instead of calling WebView methods directly.
 */
class WebViewPageAccessState(
    private val localAssetPrefix: String
) {
    private val currentPageUrl = AtomicReference<String?>(null)

    fun update(url: String?) {
        currentPageUrl.set(url)
    }

    fun currentUrl(): String? = currentPageUrl.get()

    fun needsInitialPage(): Boolean =
        currentUrl().isNullOrBlank() || currentUrl() == "about:blank"

    fun isDiagnosticPage(): Boolean =
        currentUrl()?.startsWith(localAssetPrefix) == true

    fun isTrustedSeatPage(config: DeviceConfig?): Boolean =
        WebViewAccessPolicy.isTrustedSeatPage(currentUrl(), config)
}
