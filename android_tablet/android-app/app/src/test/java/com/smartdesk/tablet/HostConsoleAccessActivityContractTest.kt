package com.smartdesk.tablet

import java.io.File
import org.junit.Assert.assertTrue
import org.junit.Test

class HostConsoleAccessActivityContractTest {
    private val mainActivity = File(
        "src/main/java/com/smartdesk/tablet/MainActivity.kt"
    ).readText()

    @Test
    fun hostAuthorizationUsesPersistentStore() {
        assertTrue(mainActivity.contains("HostConsoleAccessStore(this)"))
        assertTrue(mainActivity.contains("hostConsoleAccessStore.isAuthorized()"))
        assertTrue(mainActivity.contains("hostConsoleAccessStore.grant()"))
    }

    @Test
    fun successfulProvisioningClearsHostAuthorization() {
        val provisioningHandler = mainActivity.substring(
            mainActivity.indexOf("private fun handleProvisioningResult("),
            mainActivity.indexOf("private val microphonePermissionLauncher")
        )

        assertTrue(provisioningHandler.contains("hostConsoleAccessStore.clear()"))
    }
}
