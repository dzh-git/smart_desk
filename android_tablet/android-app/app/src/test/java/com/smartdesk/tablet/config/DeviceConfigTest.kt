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
              "serverUrl": "http://192.168.1.10:8000/",
              "frontendUrl": "http://192.168.1.10:5173/"
            }
            """.trimIndent()
        )

        assertEquals(1, config.seatId)
        assertEquals("tablet-seat-01", config.deviceId)
        assertEquals("http://192.168.1.10:8000", config.serverUrl)
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
                  "serverUrl": "file:///tmp/backend",
                  "frontendUrl": "http://192.168.1.10:5173"
                }
                """.trimIndent()
            )
        }
    }
}
