package com.smartdesk.tablet.web

enum class PageHealthRecoveryAction {
    NONE,
    RELOAD,
}

/**
 * Tracks business-page health without depending on Android timing APIs.
 * MainActivity owns probe scheduling; this class only decides when recovery is safe.
 */
class WebViewPageHealthWatchdog(
    private val failureThreshold: Int = 3,
    private val recoveryCooldownMs: Long = 60_000L,
) {
    init {
        require(failureThreshold > 0)
        require(recoveryCooldownMs >= 0L)
    }

    var consecutiveFailures: Int = 0
        private set

    var cooldownUntilMs: Long = Long.MIN_VALUE
        private set

    fun observe(
        isTrustedPage: Boolean,
        isHealthy: Boolean,
        nowMs: Long,
    ): PageHealthRecoveryAction {
        if (!isTrustedPage || isHealthy) {
            consecutiveFailures = 0
            return PageHealthRecoveryAction.NONE
        }

        if (nowMs < cooldownUntilMs) {
            consecutiveFailures = 0
            return PageHealthRecoveryAction.NONE
        }

        consecutiveFailures += 1
        if (consecutiveFailures < failureThreshold) {
            return PageHealthRecoveryAction.NONE
        }

        consecutiveFailures = 0
        cooldownUntilMs = saturatingAdd(nowMs, recoveryCooldownMs)
        return PageHealthRecoveryAction.RELOAD
    }

    /** Clear a partial failure sequence while retaining reload-loop protection. */
    fun resetFailures() {
        consecutiveFailures = 0
    }

    private fun saturatingAdd(left: Long, right: Long): Long {
        if (right > 0L && left > Long.MAX_VALUE - right) {
            return Long.MAX_VALUE
        }
        return left + right
    }
}
