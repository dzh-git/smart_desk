package com.smartdesk.tablet.provisioning

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test
import java.util.Base64

class DeviceTokenGeneratorTest {
    @Test
    fun createsIndependentUrlSafeTokens() {
        var seed = 1
        val generator = DeviceTokenGenerator(
            randomBytes = { size ->
                ByteArray(size) { seed.toByte() }.also { seed += 1 }
            },
            encoder = {
                Base64.getUrlEncoder().withoutPadding().encodeToString(it)
            }
        )

        val first = generator.generate()
        val second = generator.generate()

        assertEquals(43, first.length)
        assertEquals(43, second.length)
        assertFalse(first == second)
    }
}
