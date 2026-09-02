package com.smartdesk.tablet.web

enum class SeatPageLoadStatus {
    IDLE,
    WAITING_CONFIGURATION,
    WAITING_NETWORK,
    WAITING_BACKEND,
    CHECKING_BACKEND,
    VALIDATING_BINDING,
    WAITING_BINDING,
    LOADING,
    WAITING_FRONTEND,
    READY,
}

/**
 * Small deterministic state machine used by MainActivity and JVM tests.
 */
class SeatPageLoadState {
    var status: SeatPageLoadStatus = SeatPageLoadStatus.IDLE
        private set

    fun beginHealthCheck() {
        status = SeatPageLoadStatus.CHECKING_BACKEND
    }

    fun beginPageLoad() {
        status = SeatPageLoadStatus.LOADING
    }

    fun beginBindingValidation() {
        status = SeatPageLoadStatus.VALIDATING_BINDING
    }

    fun ready() {
        status = SeatPageLoadStatus.READY
    }

    fun waitingConfiguration() {
        status = SeatPageLoadStatus.WAITING_CONFIGURATION
    }

    fun waitingNetwork() {
        status = SeatPageLoadStatus.WAITING_NETWORK
    }

    fun waitingBackend() {
        status = SeatPageLoadStatus.WAITING_BACKEND
    }

    fun waitingBinding() {
        status = SeatPageLoadStatus.WAITING_BINDING
    }

    fun waitingFrontend() {
        status = SeatPageLoadStatus.WAITING_FRONTEND
    }

    fun timedOut(): Boolean {
        if (status != SeatPageLoadStatus.LOADING) {
            return false
        }
        status = SeatPageLoadStatus.WAITING_FRONTEND
        return true
    }

    fun retry() {
        status = SeatPageLoadStatus.CHECKING_BACKEND
    }
}
