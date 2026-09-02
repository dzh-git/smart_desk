package com.smartdesk.tablet.web

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class WebViewPageHealthWatchdogTest {
    private val watchdog = WebViewPageHealthWatchdog(
        failureThreshold = 3,
        recoveryCooldownMs = 60_000L
    )

    @Test
    fun reloadsOnlyAfterThreeConsecutiveUnhealthyProbes() {
        assertEquals(
            PageHealthRecoveryAction.NONE,
            watchdog.observe(isTrustedPage = true, isHealthy = false, nowMs = 0L)
        )
        assertEquals(
            PageHealthRecoveryAction.NONE,
            watchdog.observe(isTrustedPage = true, isHealthy = false, nowMs = 15_000L)
        )
        assertEquals(
            PageHealthRecoveryAction.RELOAD,
            watchdog.observe(isTrustedPage = true, isHealthy = false, nowMs = 30_000L)
        )
    }

    @Test
    fun healthyProbeResetsFailureSequence() {
        watchdog.observe(isTrustedPage = true, isHealthy = false, nowMs = 0L)
        watchdog.observe(isTrustedPage = true, isHealthy = false, nowMs = 15_000L)

        assertEquals(
            PageHealthRecoveryAction.NONE,
            watchdog.observe(isTrustedPage = true, isHealthy = true, nowMs = 30_000L)
        )
        assertEquals(0, watchdog.consecutiveFailures)
        assertEquals(
            PageHealthRecoveryAction.NONE,
            watchdog.observe(isTrustedPage = true, isHealthy = false, nowMs = 45_000L)
        )
    }

    @Test
    fun neverRecoversAnUntrustedOrDiagnosticPage() {
        repeat(5) { index ->
            assertEquals(
                PageHealthRecoveryAction.NONE,
                watchdog.observe(
                    isTrustedPage = false,
                    isHealthy = false,
                    nowMs = index * 15_000L
                )
            )
        }
        assertEquals(0, watchdog.consecutiveFailures)
    }

    @Test
    fun cooldownPreventsReloadLoopAfterRecovery() {
        watchdog.observe(isTrustedPage = true, isHealthy = false, nowMs = 0L)
        watchdog.observe(isTrustedPage = true, isHealthy = false, nowMs = 15_000L)
        assertEquals(
            PageHealthRecoveryAction.RELOAD,
            watchdog.observe(isTrustedPage = true, isHealthy = false, nowMs = 30_000L)
        )

        repeat(4) { index ->
            assertEquals(
                PageHealthRecoveryAction.NONE,
                watchdog.observe(
                    isTrustedPage = true,
                    isHealthy = false,
                    nowMs = 40_000L + index * 10_000L
                )
            )
        }
        assertEquals(0, watchdog.consecutiveFailures)
    }

    @Test
    fun failuresCanTriggerRecoveryAgainAfterCooldown() {
        watchdog.observe(isTrustedPage = true, isHealthy = false, nowMs = 0L)
        watchdog.observe(isTrustedPage = true, isHealthy = false, nowMs = 15_000L)
        watchdog.observe(isTrustedPage = true, isHealthy = false, nowMs = 30_000L)

        assertEquals(
            PageHealthRecoveryAction.NONE,
            watchdog.observe(isTrustedPage = true, isHealthy = false, nowMs = 90_000L)
        )
        assertEquals(
            PageHealthRecoveryAction.NONE,
            watchdog.observe(isTrustedPage = true, isHealthy = false, nowMs = 105_000L)
        )
        assertEquals(
            PageHealthRecoveryAction.RELOAD,
            watchdog.observe(isTrustedPage = true, isHealthy = false, nowMs = 120_000L)
        )
        assertTrue(watchdog.cooldownUntilMs > 120_000L)
    }

    @Test
    fun navigationResetKeepsCooldownButClearsPendingFailures() {
        watchdog.observe(isTrustedPage = true, isHealthy = false, nowMs = 0L)
        watchdog.resetFailures()

        assertEquals(0, watchdog.consecutiveFailures)
        assertEquals(
            PageHealthRecoveryAction.NONE,
            watchdog.observe(isTrustedPage = true, isHealthy = false, nowMs = 15_000L)
        )
    }
}
