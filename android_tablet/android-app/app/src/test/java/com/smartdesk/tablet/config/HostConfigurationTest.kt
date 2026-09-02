package com.smartdesk.tablet.config

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class HostConfigurationTest {
    @Test
    fun derivesDefaultEndpointsFromBareHost() {
        val config = HostConfiguration.parse("192.168.1.10")

        assertEquals("http://192.168.1.10", config.centralHost)
        assertEquals("http://192.168.1.10:8000", config.serverUrl)
        assertEquals("http://192.168.1.10:5173", config.frontendUrl)
    }

    @Test
    fun acceptsHttpsAndAdvancedOverrides() {
        val config = HostConfiguration.parse(
            centralHost = "https://meeting.example.test/",
            serverOverride = "https://api.example.test/v1",
            frontendOverride = "https://ui.example.test"
        )

        assertEquals("https://meeting.example.test", config.centralHost)
        assertEquals("https://api.example.test/v1", config.serverUrl)
        assertEquals("https://ui.example.test", config.frontendUrl)
    }

    @Test
    fun rejectsAmbiguousCentralHost() {
        assertThrows(IllegalArgumentException::class.java) {
            HostConfiguration.parse("http://192.168.1.10:9000")
        }
        assertThrows(IllegalArgumentException::class.java) {
            HostConfiguration.parse("http://user@192.168.1.10")
        }
    }
}
