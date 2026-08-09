package com.smartdesk.tablet.web

enum class SeatPageLoadStatus {
    IDLE,
    CHECKING_BACKEND,
    VALIDATING_BINDING,
    LOADING,
    READY,
    OFFLINE,
    SERVER_ERROR,
    BINDING_ERROR,
    TIMED_OUT
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

    fun offline() {
        status = SeatPageLoadStatus.OFFLINE
    }

    fun serverError() {
        status = SeatPageLoadStatus.SERVER_ERROR
    }

    fun bindingError() {
        status = SeatPageLoadStatus.BINDING_ERROR
    }

    fun timedOut(): Boolean {
        if (status != SeatPageLoadStatus.LOADING) {
            return false
        }
        status = SeatPageLoadStatus.TIMED_OUT
        return true
    }

    fun retry() {
        status = SeatPageLoadStatus.CHECKING_BACKEND
    }
}
