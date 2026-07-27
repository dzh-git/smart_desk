package com.smartdesk.tablet.recognition

import org.junit.Assert.assertEquals
import org.junit.Test

class ExposureStabilityGateTest {
    @Test
    fun waitsForMeteringAndThreeStableFrames() {
        val gate = ExposureStabilityGate()
        gate.start(100L)

        assertEquals(
            ExposureGateResult.WAITING_FOR_METERING,
            gate.observe(100f, 499L)
        )
        assertEquals(
            ExposureGateResult.WAITING_FOR_STABILITY,
            gate.observe(100f, 500L)
        )
        assertEquals(
            ExposureGateResult.WAITING_FOR_STABILITY,
            gate.observe(108f, 680L)
        )
        assertEquals(
            ExposureGateResult.READY,
            gate.observe(112f, 860L)
        )
    }

    @Test
    fun timesOutInsteadOfLoweringRequirement() {
        val gate = ExposureStabilityGate()
        gate.start(100L)

        assertEquals(
            ExposureGateResult.TIMED_OUT,
            gate.observe(100f, 1_501L)
        )
    }
}
