package com.smartdesk.tablet

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class IdentityCameraOverlayPolicyTest {
    @Test
    fun closesCameraOverlayAfterVerifiedIdentity() {
        assertEquals(
            IdentityCameraOverlayPolicy.VERIFIED_CLOSE_DELAY_MS,
            IdentityCameraOverlayPolicy.closeDelayMs("VERIFIED")
        )
    }

    @Test
    fun keepsCameraOverlayOpenForNonTerminalIdentityStates() {
        listOf(
            "VERIFYING",
            "WAITING_FOR_FACE",
            "MULTIPLE_FACES",
            "UNKNOWN",
            "RETRY_REQUIRED",
            "ERROR"
        ).forEach { status ->
            assertNull(IdentityCameraOverlayPolicy.closeDelayMs(status))
        }
    }
}
