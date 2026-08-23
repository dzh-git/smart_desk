package com.smartdesk.tablet.recognition

import java.security.spec.MGF1ParameterSpec
import org.junit.Assert.assertEquals
import org.junit.Test

class FaceTransportCryptoContractTest {
    @Test
    fun oaepContractMatchesAndroidKeystoreDefaultMgf1Digest() {
        val spec = faceTransportOaepSpec()

        assertEquals("SHA-256", spec.digestAlgorithm)
        assertEquals("MGF1", spec.mgfAlgorithm)
        assertEquals(
            "SHA-1",
            (spec.mgfParameters as MGF1ParameterSpec).digestAlgorithm
        )
    }
}
