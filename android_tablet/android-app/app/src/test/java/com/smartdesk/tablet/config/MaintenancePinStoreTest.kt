package com.smartdesk.tablet.config

import com.smartdesk.tablet.security.LocalStringStore
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Base64

class MaintenancePinStoreTest {
    @Test
    fun storesVerifierAndValidatesPin() {
        val local = MemoryStringStore()
        val store = store(local)

        store.set("123456")

        assertTrue(store.hasPin())
        assertTrue(store.verify("123456"))
        assertFalse(store.verify("654321"))
        assertFalse(local.values.values.single().contains("123456"))
    }

    @Test
    fun rejectsWeakPin() {
        assertThrows(IllegalArgumentException::class.java) {
            store(MemoryStringStore()).set("12345")
        }
        assertThrows(IllegalArgumentException::class.java) {
            store(MemoryStringStore()).set("abcdef")
        }
    }

    private fun store(local: MemoryStringStore) = MaintenancePinStore(
        secureStore = local,
        randomBytes = { size -> ByteArray(size) { 7 } },
        encoder = { Base64.getEncoder().encodeToString(it) },
        decoder = { Base64.getDecoder().decode(it) }
    )

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
