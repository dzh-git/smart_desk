package com.smartdesk.tablet.config

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class ProvisioningRequestTest {
    @Test
    fun parsesFirstProvisioningRequestWithoutDeviceSecret() {
        val request = ProvisioningRequest.parse(
            """
            {
              "seatId": 3,
              "centralHost": "192.168.1.10",
              "provisioningToken": "admin-provisioning-token-000003",
              "maintenancePin": "123456"
            }
            """.trimIndent(),
            requireMaintenancePin = true
        )

        assertEquals(3, request.seatId)
        assertEquals("http://192.168.1.10:8000", request.endpoints.serverUrl)
        assertEquals("123456", request.maintenancePin)
    }

    @Test
    fun requiresPinOnlyForInitialSetup() {
        val payload = """
            {
              "seatId": 3,
              "centralHost": "192.168.1.10",
              "provisioningToken": "admin-provisioning-token-000003"
            }
        """.trimIndent()

        assertThrows(IllegalArgumentException::class.java) {
            ProvisioningRequest.parse(payload, requireMaintenancePin = true)
        }
        assertEquals(
            3,
            ProvisioningRequest.parse(
                payload,
                requireMaintenancePin = false
            ).seatId
        )
    }
}
