package com.smartdesk.tablet.config

import com.smartdesk.tablet.security.LocalStringStore
import org.junit.Assert.assertEquals
import org.junit.Test

class DeviceIdentityStoreTest {
    @Test
    fun generatesIdentityOnlyOnce() {
        val local = MemoryStringStore()
        var generated = 0
        val store = DeviceIdentityStore(local) {
            generated += 1
            "tablet-00000000-0000-0000-0000-000000000001"
        }

        val first = store.getOrCreate()
        val second = DeviceIdentityStore(local) {
            "tablet-00000000-0000-0000-0000-000000000002"
        }.getOrCreate()

        assertEquals(first, second)
        assertEquals(1, generated)
    }

    @Test
    fun migratesLegacyConfiguredDeviceId() {
        val local = MemoryStringStore()
        val id = DeviceIdentityStore(local) {
            "tablet-should-not-be-used"
        }.getOrCreate("tablet-seat-01")

        assertEquals("tablet-seat-01", id)
    }

    private class MemoryStringStore : LocalStringStore {
        private val values = mutableMapOf<String, String>()
        override fun getString(key: String): String? = values[key]
        override fun putString(key: String, value: String) {
            values[key] = value
        }
        override fun remove(key: String) {
            values.remove(key)
        }
    }
}
