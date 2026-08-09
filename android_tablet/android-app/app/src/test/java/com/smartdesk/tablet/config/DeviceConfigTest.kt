package com.smartdesk.tablet.config

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class DeviceConfigTest {
    @Test
    fun parsesAndNormalizesValidConfiguration() {
        val config = DeviceConfig.parse(
            """
            {
              "seatId": 1,
              "deviceId": "tablet-seat-01",
              "deviceToken": "test-device-secret-token-000001",
              "serverBaseUrl": "http://192.168.1.10:8000/",
              "frontendBaseUrl": "http://192.168.1.10:5173/"
            }
            """.trimIndent()
        )

        assertEquals(1, config.seatId)
        assertEquals("tablet-seat-01", config.deviceId)
        assertEquals(
            "test-device-secret-token-000001",
            config.deviceToken
        )
        assertEquals("http://192.168.1.10:8000", config.serverUrl)
        assertEquals("http://192.168.1.10", config.centralHost())
        assertEquals("tablet-seat-01", config.seatAlias)
        assertEquals("http://192.168.1.10:5173/seat/1", config.seatPageUrl())
    }

    @Test
    fun rejectsSeatOutsideProductRange() {
        assertThrows(IllegalArgumentException::class.java) {
            DeviceConfig.parse(
                """
                {
                  "seatId": 10,
                  "deviceId": "tablet-seat-10",
                  "deviceToken": "test-device-secret-token-000010",
                  "serverUrl": "http://192.168.1.10:8000",
                  "frontendUrl": "http://192.168.1.10:5173"
                }
                """.trimIndent()
            )
        }
    }

    @Test
    fun rejectsUnsafeOrAmbiguousEndpoint() {
        assertThrows(IllegalArgumentException::class.java) {
            DeviceConfig.parse(
                """
                {
                  "seatId": 1,
                  "deviceId": "tablet-seat-01",
                  "deviceToken": "test-device-secret-token-000001",
                  "serverUrl": "file:///tmp/backend",
                  "frontendUrl": "http://192.168.1.10:5173"
                }
                """.trimIndent()
            )
        }
    }

    @Test
    fun preservesExistingSecretWhenReconfiguringPublicFields() {
        val config = DeviceConfig.parse(
            """
            {
              "seatId": 2,
              "deviceId": "tablet-seat-02",
              "serverBaseUrl": "https://meeting.example.test",
              "frontendBaseUrl": "https://ui.example.test"
            }
            """.trimIndent(),
            fallbackDeviceToken = "existing-device-secret-token-0002"
        )

        assertEquals(
            "existing-device-secret-token-0002",
            config.deviceToken
        )
        assertEquals(
            "https://ui.example.test/seat/2",
            config.seatPageUrl()
        )
    }

    @Test
    fun rejectsMissingDeviceTokenOnFirstConfiguration() {
        assertThrows(IllegalArgumentException::class.java) {
            DeviceConfig.parse(
                """
                {
                  "seatId": 1,
                  "deviceId": "tablet-seat-01",
                  "serverBaseUrl": "http://192.168.1.10:8000",
                  "frontendBaseUrl": "http://192.168.1.10:5173"
                }
                """.trimIndent()
            )
        }
    }
}
