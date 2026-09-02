package com.smartdesk.tablet.web

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SeatPageLoadStateTest {
    @Test
    fun representsNetworkWaitAndRetryTransitions() {
        val state = SeatPageLoadState()
        state.beginHealthCheck()
        state.waitingNetwork()
        assertEquals(SeatPageLoadStatus.WAITING_NETWORK, state.status)

        state.retry()
        assertEquals(
            SeatPageLoadStatus.CHECKING_BACKEND,
            state.status
        )
        state.beginPageLoad()
        state.ready()
        assertEquals(SeatPageLoadStatus.READY, state.status)
    }

    @Test
    fun timeoutOnlyAppliesToAnActivePageLoad() {
        val state = SeatPageLoadState()
        assertFalse(state.timedOut())
        state.beginPageLoad()
        assertTrue(state.timedOut())
        assertEquals(SeatPageLoadStatus.WAITING_FRONTEND, state.status)
        assertFalse(state.timedOut())
    }

    @Test
    fun blocksSeatLoadingWhenBindingValidationFails() {
        val state = SeatPageLoadState()
        state.beginHealthCheck()
        state.beginBindingValidation()
        assertEquals(
            SeatPageLoadStatus.VALIDATING_BINDING,
            state.status
        )
        state.waitingBinding()
        assertEquals(SeatPageLoadStatus.WAITING_BINDING, state.status)
    }

    @Test
    fun representsBackendAndPageFailureBranches() {
        val state = SeatPageLoadState()
        state.beginHealthCheck()
        state.waitingBackend()
        assertEquals(SeatPageLoadStatus.WAITING_BACKEND, state.status)

        state.retry()
        state.beginBindingValidation()
        state.waitingNetwork()
        assertEquals(SeatPageLoadStatus.WAITING_NETWORK, state.status)

        state.retry()
        state.beginBindingValidation()
        state.beginPageLoad()
        assertTrue(state.timedOut())
        assertEquals(SeatPageLoadStatus.WAITING_FRONTEND, state.status)
    }

    @Test
    fun validatesBackendHealthResponseContract() {
        assertTrue(
            BackendHealthChecker.isHealthyResponse(
                200,
                """{"status":"ok"}"""
            )
        )
        assertFalse(
            BackendHealthChecker.isHealthyResponse(
                503,
                """{"status":"ok"}"""
            )
        )
        assertFalse(
            BackendHealthChecker.isHealthyResponse(
                200,
                """{"status":"starting"}"""
            )
        )
    }
}
