package com.smartdesk.tablet

import java.io.File
import org.junit.Assert.assertTrue
import org.junit.Test

class NativeMicrophoneAccessContractTest {
    private val mainActivity = File(
        "src/main/java/com/smartdesk/tablet/MainActivity.kt"
    ).readText()

    @Test
    fun nativeCaptureUsesOperationalPagePolicy() {
        val requestHandler = mainActivity.substring(
            mainActivity.indexOf(
                "private fun requestStartNativeMicrophoneCapture()"
            ),
            mainActivity.indexOf("private fun startNativeMicrophoneCapture()")
        )

        assertTrue(
            requestHandler.contains(
                "WebViewAccessPolicy.mayStartNativeMicrophone("
            )
        )

    }
    @Test
    fun permissionResultAndCaptureStartRecheckOperationalPage() {
        val permissionHandler = mainActivity.substring(
            mainActivity.indexOf("private val microphonePermissionLauncher"),
            mainActivity.indexOf(
                "private fun requestStartNativeMicrophoneCapture()"
            )
        )
        val startHandler = mainActivity.substring(
            mainActivity.indexOf("private fun startNativeMicrophoneCapture()"),
            mainActivity.indexOf("private fun stopNativeMicrophoneCapture()")
        )

        assertTrue(
            permissionHandler.contains(
                "WebViewAccessPolicy.mayStartNativeMicrophone("
            )
        )
        assertTrue(
            startHandler.contains(
                "WebViewAccessPolicy.mayStartNativeMicrophone("
            )
        )
    }

    @Test
    fun navigationAwayFromOperationalPageStopsNativeCapture() {
        val pageStarted = mainActivity.substring(
            mainActivity.indexOf("override fun onPageStarted("),
            mainActivity.indexOf("override fun onPageFinished(")
        )

        assertTrue(
            pageStarted.contains(
                "WebViewAccessPolicy.mayStartNativeMicrophone("
            )
        )
        assertTrue(pageStarted.contains("stopNativeMicrophoneCapture()"))
    }
}
