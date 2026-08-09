package com.smartdesk.tablet.web

import java.io.File
import org.junit.Assert.assertTrue
import org.junit.Test

class ManifestPermissionContractTest {
    @Test
    fun declaresPermissionsRequiredForWebViewMicrophoneCapture() {
        val manifest = File("src/main/AndroidManifest.xml").readText()

        assertTrue(
            manifest.contains("android.permission.RECORD_AUDIO")
        )
        assertTrue(
            manifest.contains("android.permission.MODIFY_AUDIO_SETTINGS")
        )
    }
}
