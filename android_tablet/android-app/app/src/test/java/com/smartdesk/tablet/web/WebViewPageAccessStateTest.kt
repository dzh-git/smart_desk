package com.smartdesk.tablet.web

import com.smartdesk.tablet.config.DeviceConfig
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class WebViewPageAccessStateTest {
    private val state = WebViewPageAccessState(
        "file:///android_asset/web/"
    )
    private val config = DeviceConfig(
        seatId = 1,
        deviceId = "tablet-seat-01",
        serverUrl = "http://192.168.1.10:8000",
        frontendUrl = "https://meeting.example.test",
        deviceToken = "test-device-secret-token-000001"
    )

    @Test
    fun startsWithNoPrivilegedPage() {
        assertNull(state.currentUrl())
        assertTrue(state.needsInitialPage())
        assertTrue(state.shouldLoadConfiguredSeatPageImmediately(config))
        assertFalse(state.shouldLoadConfiguredSeatPageImmediately(null))
        assertFalse(state.isDiagnosticPage())
        assertFalse(state.isTrustedSeatPage(config))
    }

    @Test
    fun configuredStartupSkipsDiagnosticsButFailuresCanRetryAfterValidation() {
        assertTrue(state.shouldLoadConfiguredSeatPageImmediately(config))

        state.update("https://meeting.example.test/seat/1")
        assertFalse(state.needsSeatPageLoadAfterValidation(true))

        state.update("file:///android_asset/web/index.html?mode=offline")
        assertTrue(state.needsSeatPageLoadAfterValidation(true))
        assertTrue(state.needsSeatPageLoadAfterValidation(false))
    }

    @Test
    fun distinguishesDiagnosticAndConfiguredSeatPages() {
        state.update("file:///android_asset/web/index.html?mode=setup")
        assertFalse(state.needsInitialPage())
        assertTrue(state.isDiagnosticPage())
        assertFalse(state.isTrustedSeatPage(config))

        state.update("https://meeting.example.test/seat/1")
        assertFalse(state.isDiagnosticPage())
        assertTrue(state.isTrustedSeatPage(config))

        state.update("https://meeting.example.test/seat/2")
        assertFalse(state.isTrustedSeatPage(config))
    }

    @Test
    fun onlyBlankPagesNeedAnInitialLoad() {
        state.update("about:blank")
        assertTrue(state.needsInitialPage())

        state.update("   ")
        assertTrue(state.needsInitialPage())

        state.update("file:///android_asset/web/index.html?mode=offline")
        assertFalse(state.needsInitialPage())
    }

    @Test
    fun clearingUrlImmediatelyRevokesPreviousPageAccess() {
        state.update("https://meeting.example.test/seat/1")
        assertTrue(state.isTrustedSeatPage(config))

        state.update(null)

        assertFalse(state.isDiagnosticPage())
        assertFalse(state.isTrustedSeatPage(config))
    }
}
