package com.smartdesk.tablet.recognition

enum class ExposureGateResult {
    WAITING_FOR_METERING,
    WAITING_FOR_STABILITY,
    READY,
    TIMED_OUT
}

class ExposureStabilityGate {
    private var meteringStartedAtMs = 0L
    private val brightnessWindow = ArrayDeque<Float>()
    private var ready = false

    fun start(nowMs: Long) {
        meteringStartedAtMs = nowMs
        brightnessWindow.clear()
        ready = false
    }

    fun observe(
        brightness: Float,
        nowMs: Long
    ): ExposureGateResult {
        require(meteringStartedAtMs > 0L) {
            "必须先启动曝光稳定检查"
        }
        if (ready) {
            return ExposureGateResult.READY
        }
        val elapsed = nowMs - meteringStartedAtMs
        if (elapsed < METERING_WAIT_MS) {
            return ExposureGateResult.WAITING_FOR_METERING
        }
        if (elapsed > METERING_WAIT_MS + MAX_STABILITY_WAIT_MS) {
            return ExposureGateResult.TIMED_OUT
        }
        brightnessWindow.addLast(brightness)
        while (brightnessWindow.size > STABILITY_FRAME_COUNT) {
            brightnessWindow.removeFirst()
        }
        if (
            brightnessWindow.size == STABILITY_FRAME_COUNT &&
            brightnessWindow.max() - brightnessWindow.min() <
            MAX_BRIGHTNESS_RANGE
        ) {
            ready = true
            return ExposureGateResult.READY
        }
        return ExposureGateResult.WAITING_FOR_STABILITY
    }

    fun reset() {
        meteringStartedAtMs = 0L
        brightnessWindow.clear()
        ready = false
    }

    companion object {
        const val METERING_WAIT_MS = 400L
        const val MAX_STABILITY_WAIT_MS = 3_000L
        const val STABILITY_FRAME_COUNT = 3
        const val MAX_BRIGHTNESS_RANGE = 15f
    }
}
