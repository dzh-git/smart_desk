package com.smartdesk.tablet.web

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SeatPageLoadStateTest {
    @Test
    fun representsOfflineAndRetryTransitions() {
        val state = SeatPageLoadState()
        state.beginHealthCheck()
        state.offline()
        assertEquals(SeatPageLoadStatus.OFFLINE, state.status)

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
        assertEquals(SeatPageLoadStatus.TIMED_OUT, state.status)
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
        state.bindingError()
        assertEquals(SeatPageLoadStatus.BINDING_ERROR, state.status)
    }

    @Test
    fun representsBackendAndPageFailureBranches() {
        val state = SeatPageLoadState()
        state.beginHealthCheck()
        state.serverError()
        assertEquals(SeatPageLoadStatus.SERVER_ERROR, state.status)

        state.retry()
        state.beginBindingValidation()
        state.offline()
        assertEquals(SeatPageLoadStatus.OFFLINE, state.status)

        state.retry()
        state.beginBindingValidation()
        state.beginPageLoad()
        assertTrue(state.timedOut())
        assertEquals(SeatPageLoadStatus.TIMED_OUT, state.status)
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
