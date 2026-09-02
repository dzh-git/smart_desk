package com.smartdesk.tablet.recognition

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class HostIdentityDefaultPolicyTest {
    @Test
    fun soleTemplateBecomesDefault() {
        assertEquals(
            "host-a",
            HostIdentityDefaultPolicy.resolve(null, listOf("host-a"))
        )
    }

    @Test
    fun existingDefaultSurvivesWhenMoreTemplatesAreAdded() {
        assertEquals(
            "host-a",
            HostIdentityDefaultPolicy.resolve(
                "host-a",
                listOf("host-a", "host-b")
            )
        )
    }

    @Test
    fun deletingDefaultRequiresSelectionWhenSeveralRemain() {
        assertNull(
            HostIdentityDefaultPolicy.resolve(
                "host-a",
                listOf("host-b", "host-c")
            )
        )
    }

    @Test
    fun deletingDefaultSelectsTheOnlyRemainingTemplate() {
        assertEquals(
            "host-b",
            HostIdentityDefaultPolicy.resolve("host-a", listOf("host-b"))
        )
    }

    @Test
    fun clearingTemplatesClearsDefault() {
        assertNull(HostIdentityDefaultPolicy.resolve("host-a", emptyList()))
    }
}
