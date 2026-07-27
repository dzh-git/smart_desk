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
}
