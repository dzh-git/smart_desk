package com.smartdesk.tablet.web

import com.smartdesk.tablet.config.DeviceConfig
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class WebViewAccessPolicyTest {
    private val config = DeviceConfig(
        seatId = 1,
        deviceId = "tablet-seat-01",
        serverUrl = "http://192.168.1.10:8000",
        frontendUrl = "https://meeting.example.test",
        deviceToken = "test-device-secret-token-000001"
    )

    @Test
    fun grantsAudioOnlyToConfiguredSeatPageAndOrigin() {
        assertTrue(
            WebViewAccessPolicy.mayGrantMicrophone(
                originUrl = "https://meeting.example.test/",
                currentPageUrl = "https://meeting.example.test/seat/1",
                requestedResources = listOf(
                    WebViewAccessPolicy.AUDIO_CAPTURE_RESOURCE
                ),
                config = config,
                androidPermissionGranted = true
            )
        )
    }

    @Test
    fun rejectsWrongSeatExternalOriginAndAdditionalResources() {
        assertFalse(
            WebViewAccessPolicy.mayGrantMicrophone(
                "https://meeting.example.test",
                "https://meeting.example.test/seat/2",
                listOf(WebViewAccessPolicy.AUDIO_CAPTURE_RESOURCE),
                config,
                true
            )
        )
        assertFalse(
            WebViewAccessPolicy.mayGrantMicrophone(
                "https://evil.example.test",
                "https://meeting.example.test/seat/1",
                listOf(WebViewAccessPolicy.AUDIO_CAPTURE_RESOURCE),
                config,
                true
            )
        )
        assertFalse(
            WebViewAccessPolicy.mayGrantMicrophone(
                "https://meeting.example.test",
                "https://meeting.example.test/seat/1",
                listOf(
                    WebViewAccessPolicy.AUDIO_CAPTURE_RESOURCE,
                    "android.webkit.resource.VIDEO_CAPTURE"
                ),
                config,
                true
            )
        )
    }

    @Test
    fun rejectsWhenAndroidRuntimePermissionIsMissing() {
        assertFalse(
            WebViewAccessPolicy.mayGrantMicrophone(
                "https://meeting.example.test",
                "https://meeting.example.test/seat/1",
                listOf(WebViewAccessPolicy.AUDIO_CAPTURE_RESOURCE),
                config,
                false
            )
        )
    }

    @Test
    fun hostFaceTemplatePageRequiresExactSeatOneOriginAndPath() {
        assertTrue(
            WebViewAccessPolicy.isHostFaceTemplatesPage(
                "https://meeting.example.test/seat/1/face-templates",
                config
            )
        )
        assertFalse(
            WebViewAccessPolicy.isHostFaceTemplatesPage(
                "https://evil.example.test/seat/1/face-templates",
                config
            )
        )
        assertFalse(
            WebViewAccessPolicy.isHostFaceTemplatesPage(
                "https://meeting.example.test/seat/1/face-templates/debug",
                config
            )
        )
        assertFalse(
            WebViewAccessPolicy.isHostFaceTemplatesPage(
                "https://meeting.example.test/seat/1/face-templates",
                config.copy(seatId = 2)
            )
        )
    }

    @Test
    fun hostConsoleRequiresExactSeatOneOriginAndPath() {
        assertTrue(
            WebViewAccessPolicy.isTrustedHostConsolePage(
                "https://meeting.example.test/host",
                config
            )
        )
        assertTrue(
            WebViewAccessPolicy.isTrustedOperationalPage(
                "https://meeting.example.test/host",
                config
            )
        )
        assertFalse(
            WebViewAccessPolicy.isTrustedHostConsolePage(
                "https://evil.example.test/host",
                config
            )
        )
        assertFalse(
            WebViewAccessPolicy.isTrustedHostConsolePage(
                "https://meeting.example.test/host/seat",
                config
            )
        )
        assertFalse(
            WebViewAccessPolicy.isTrustedHostConsolePage(
                "https://meeting.example.test/host",
                config.copy(seatId = 2)
            )
        )
    }

    @Test
    fun grantsAudioToTrustedHostConsole() {
        assertTrue(
            WebViewAccessPolicy.mayGrantMicrophone(
                "https://meeting.example.test",
                "https://meeting.example.test/host",
                listOf(WebViewAccessPolicy.AUDIO_CAPTURE_RESOURCE),
                config,
                true
            )
        )
    }

    @Test
    fun startsNativeMicrophoneOnlyFromConfiguredOperationalPages() {
        assertTrue(
            WebViewAccessPolicy.mayStartNativeMicrophone(
                "https://meeting.example.test/seat/1",
                config
            )
        )
        assertTrue(
            WebViewAccessPolicy.mayStartNativeMicrophone(
                "https://meeting.example.test/host",
                config
            )
        )
        assertFalse(
            WebViewAccessPolicy.mayStartNativeMicrophone(
                "https://evil.example.test/host",
                config
            )
        )
        assertFalse(
            WebViewAccessPolicy.mayStartNativeMicrophone(
                "https://meeting.example.test/seat/2",
                config
            )
        )
        assertFalse(
            WebViewAccessPolicy.mayStartNativeMicrophone(
                "https://meeting.example.test/host",
                config.copy(seatId = 2)
            )
        )
    }

    @Test
    fun photoChooserAllowsOnlyAuthorizedHostTemplatePage() {
        assertTrue(
            WebViewAccessPolicy.mayOpenTemplatePhotoChooser(
                currentPageUrl =
                    "https://meeting.example.test/seat/1/face-templates",
                config = config,
                maintenanceAuthorized = true
            )
        )
        assertFalse(
            WebViewAccessPolicy.mayOpenTemplatePhotoChooser(
                currentPageUrl = "file:///android_asset/diagnostic/index.html",
                config = config,
                maintenanceAuthorized = true
            )
        )
        assertFalse(
            WebViewAccessPolicy.mayOpenTemplatePhotoChooser(
                currentPageUrl =
                    "https://meeting.example.test/seat/1/face-templates",
                config = config,
                maintenanceAuthorized = false
            )
        )
        assertFalse(
            WebViewAccessPolicy.mayOpenTemplatePhotoChooser(
                currentPageUrl = "https://evil.example.test/seat/1/face-templates",
                config = config,
                maintenanceAuthorized = true
            )
        )
    }
}
