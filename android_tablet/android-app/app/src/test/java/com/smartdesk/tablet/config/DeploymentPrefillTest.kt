package com.smartdesk.tablet.config

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class DeploymentPrefillTest {
    @Test
    fun acceptsSeatAndNormalizesNonSecretCentralHost() {
        val prefill = DeploymentPrefill.parse("2", "192.168.137.1")

        assertEquals(2, prefill?.seatId)
        assertEquals("http://192.168.137.1", prefill?.centralHost)
    }

    @Test
    fun rejectsInvalidSeatOrAmbiguousHost() {
        assertNull(DeploymentPrefill.parse("10", "192.168.137.1"))
        assertNull(DeploymentPrefill.parse("2", "http://user@192.168.137.1"))
    }
}
