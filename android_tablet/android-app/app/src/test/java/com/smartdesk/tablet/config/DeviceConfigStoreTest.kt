package com.smartdesk.tablet.config

import com.smartdesk.tablet.security.LocalStringStore
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

class DeviceConfigStoreTest {
    @Test
    fun persistsAndReloadsCompleteConfiguration() {
        val local = MemoryStringStore()
        val store = DeviceConfigStore(local)

        store.save(validPayload("original-device-secret-token-0001"))
        val loaded = DeviceConfigStore(local).load()

        assertNotNull(loaded)
        assertEquals(1, loaded?.seatId)
        assertEquals("tablet-seat-01", loaded?.deviceId)
        assertEquals(
            "original-device-secret-token-0001",
            loaded?.deviceToken
        )
        assertTrue(local.values.values.single().contains("deviceToken"))
    }

    @Test
    fun reconfigurationPreservesStoredSecretWhenFieldIsBlank() {
        val local = MemoryStringStore()
        val store = DeviceConfigStore(local)
        store.save(validPayload("original-device-secret-token-0001"))

        store.save(
            """
            {
              "seatId": 2,
              "deviceId": "tablet-seat-02",
              "serverBaseUrl": "https://api.example.test",
              "frontendBaseUrl": "https://meeting.example.test"
            }
            """.trimIndent()
        )

        val loaded = DeviceConfigStore(local).load()
        assertEquals(2, loaded?.seatId)
        assertEquals(
            "original-device-secret-token-0001",
            loaded?.deviceToken
        )
    }

    @Test
    fun invalidReconfigurationDoesNotOverwriteStoredConfiguration() {
        val local = MemoryStringStore()
        val store = DeviceConfigStore(local)
        store.save(validPayload("original-device-secret-token-0001"))

        runCatching {
            store.save(
                """
                {
                  "seatId": 10,
                  "deviceId": "tablet-new-physical-id",
                  "deviceToken": "test-replacement-device-token-0001",
                  "serverBaseUrl": "http://192.168.1.20:8000",
                  "frontendBaseUrl": "http://192.168.1.20:5173"
                }
                """.trimIndent()
            )
        }

        val loaded = DeviceConfigStore(local).load()
        assertEquals(1, loaded?.seatId)
        assertEquals("tablet-seat-01", loaded?.deviceId)
        assertEquals(
            "original-device-secret-token-0001",
            loaded?.deviceToken
        )
    }

    private fun validPayload(token: String): String =
        """
        {
          "seatId": 1,
          "deviceId": "tablet-seat-01",
          "deviceToken": "$token",
          "serverBaseUrl": "http://192.168.1.10:8000",
          "frontendBaseUrl": "http://192.168.1.10:5173"
        }
        """.trimIndent()

    private class MemoryStringStore : LocalStringStore {
        val values = mutableMapOf<String, String>()

        override fun getString(key: String): String? = values[key]

        override fun putString(key: String, value: String) {
            values[key] = value
        }

        override fun remove(key: String) {
            values.remove(key)
        }
    }
}
