package com.smartdesk.tablet

import java.io.File
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class LauncherManifestContractTest {
    private val manifest = File("src/main/AndroidManifest.xml").readText()

    @Test
    fun declaresMainActivityAsDefaultHomeLauncher() {
        assertTrue(manifest.contains("android.intent.category.HOME"))
        assertTrue(manifest.contains("android.intent.category.DEFAULT"))
        assertTrue(manifest.contains("android:launchMode=\"singleTask\""))
    }

    @Test
    fun doesNotLaunchActivityFromBootReceiver() {
        assertFalse(manifest.contains("android.permission.RECEIVE_BOOT_COMPLETED"))
        assertFalse(manifest.contains(".BootCompletedReceiver"))
    }
}
