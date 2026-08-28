package com.smartdesk.tablet.config

import com.smartdesk.tablet.security.LocalStringStore
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class HostConsoleAccessStoreTest {
    @Test
    fun authorizationIsDisabledByDefault() {
        assertFalse(HostConsoleAccessStore(MemoryStringStore()).isAuthorized())
    }

    @Test
    fun grantPersistsAcrossStoreInstances() {
        val local = MemoryStringStore()

        HostConsoleAccessStore(local).grant()

        assertTrue(HostConsoleAccessStore(local).isAuthorized())
    }

    @Test
    fun clearRevokesAuthorization() {
        val local = MemoryStringStore()
        val store = HostConsoleAccessStore(local)
        store.grant()

        store.clear()

        assertFalse(HostConsoleAccessStore(local).isAuthorized())
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
