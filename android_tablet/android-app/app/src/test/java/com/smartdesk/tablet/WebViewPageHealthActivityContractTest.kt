package com.smartdesk.tablet

import java.io.File
import org.junit.Assert.assertTrue
import org.junit.Test

class WebViewPageHealthActivityContractTest {
    private val mainActivity = File(
        "src/main/java/com/smartdesk/tablet/MainActivity.kt"
    ).readText()

    @Test
    fun trustedPageCompletionStartsHealthMonitoring() {
        val pageFinished = mainActivity.substring(
            mainActivity.indexOf("override fun onPageFinished("),
            mainActivity.indexOf("override fun shouldOverrideUrlLoading(")
        )

        assertTrue(
            pageFinished.contains(
                "WebViewAccessPolicy.isTrustedOperationalPage("
            )
        )
        assertTrue(
            pageFinished.contains(
                "schedulePageHealthProbe(PAGE_HEALTH_INITIAL_GRACE_MS)"
            )
        )
    }

    @Test
    fun probeHasIndependentTimeoutAndReloadRecovery() {
        val healthMonitoring = mainActivity.substring(
            mainActivity.indexOf("private fun schedulePageHealthProbe("),
            mainActivity.indexOf("private fun scheduleOfflineRetry()")
        )

        assertTrue(healthMonitoring.contains("webView.evaluateJavascript("))
        assertTrue(
            healthMonitoring.contains("PAGE_HEALTH_PROBE_TIMEOUT_MS")
        )
        assertTrue(healthMonitoring.contains("val probeDurationMs ="))
        assertTrue(healthMonitoring.contains(".coerceAtLeast(0L)"))
        assertTrue(
            healthMonitoring.contains(
                "recoveryAction == PageHealthRecoveryAction.RELOAD"
            )
        )
        assertTrue(healthMonitoring.contains("beginSeatPageLoad(currentUrl)"))
    }

    @Test
    fun navigationAndActivityPauseCancelMonitoring() {
        val pageStarted = mainActivity.substring(
            mainActivity.indexOf("override fun onPageStarted("),
            mainActivity.indexOf("override fun onPageFinished(")
        )
        val onPause = mainActivity.substring(
            mainActivity.indexOf("override fun onPause()"),
            mainActivity.indexOf("private fun setFillLightEnabled(")
        )

        assertTrue(pageStarted.contains("cancelPageHealthMonitoring()"))
        assertTrue(onPause.contains("cancelPageHealthMonitoring()"))
    }

    @Test
    fun productionTimingAndMaintenanceCancellationStayExplicit() {
        assertTrue(
            mainActivity.contains(
                "const val PAGE_HEALTH_INITIAL_GRACE_MS = 20_000L"
            )
        )
        assertTrue(
            mainActivity.contains(
                "const val PAGE_HEALTH_PROBE_INTERVAL_MS = 15_000L"
            )
        )
        assertTrue(
            mainActivity.contains(
                "const val PAGE_HEALTH_PROBE_TIMEOUT_MS = 5_000L"
            )
        )

        val maintenanceNavigation = mainActivity.substring(
            mainActivity.indexOf("private fun openMaintenancePage()"),
            mainActivity.indexOf("private fun scheduleMaintenanceExpiry()")
        )
        assertTrue(
            maintenanceNavigation.indexOf("cancelPageHealthMonitoring()") <
                maintenanceNavigation.indexOf("webView.loadUrl(")
        )
    }
}
