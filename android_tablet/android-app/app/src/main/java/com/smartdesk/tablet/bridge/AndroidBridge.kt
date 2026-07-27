package com.smartdesk.tablet.bridge

import android.os.Build
import android.util.Log
import android.webkit.JavascriptInterface
import com.smartdesk.tablet.config.DeviceConfig
import org.json.JSONObject

class AndroidBridge(
    private val defaultDeviceId: String,
    private val onGetDeviceConfig: () -> DeviceConfig?,
    private val onSaveDeviceConfig: (String) -> String,
    private val onReloadSeatPage: () -> Unit,
    private val onStartFaceDetection: () -> Unit,
    private val onStopFaceDetection: () -> Unit,
    private val onStartFaceEnrollment: (String) -> String,
    private val onStartIdentityVerification: () -> String,
    private val onStopIdentityVerification: () -> String,
    private val onClearFaceTemplate: () -> String,
    private val onRemoveFaceTemplate: (String) -> String,
    private val onGetRegisteredFaces: () -> String,
    private val onSetVerificationThreshold: (Float) -> String,
    private val onSetDiagnosticsEnabled: (Boolean) -> String,
    private val onClearDiagnostics: () -> String,
    private val onGetIdentityStatus: () -> String
) {
    init {
        Log.i(TAG, "Bridge initialized")
    }

    @JavascriptInterface
    fun getDeviceInfo(): String {
        val config = onGetDeviceConfig()
        val payload = JSONObject()
            .put("type", "device_info")
            .put(
                "data",
                JSONObject()
                    .put("deviceId", config?.deviceId ?: defaultDeviceId)
                    .put("seatId", config?.seatId ?: JSONObject.NULL)
                    .put("serverUrl", config?.serverUrl ?: JSONObject.NULL)
                    .put(
                        "frontendUrl",
                        config?.frontendUrl ?: JSONObject.NULL
                    )
                    .put("configured", config != null)
                    .put("manufacturer", Build.MANUFACTURER)
                    .put("model", Build.MODEL)
                    .put("androidVersion", Build.VERSION.RELEASE)
                    .put("sdkInt", Build.VERSION.SDK_INT)
                    .put("bridgeReady", true)
            )

        Log.i(TAG, "Device info requested")
        return payload.toString()
    }

    @JavascriptInterface
    fun getDeviceConfig(): String {
        val config = onGetDeviceConfig()
        return JSONObject()
            .put("type", "device_config")
            .put(
                "data",
                config?.toJson() ?: JSONObject.NULL
            )
            .toString()
    }

    @JavascriptInterface
    fun saveDeviceConfig(configJson: String): String =
        onSaveDeviceConfig(configJson)

    @JavascriptInterface
    fun reloadSeatPage() {
        onReloadSeatPage()
    }

    @JavascriptInterface
    fun startFaceDetection() {
        Log.i(TAG, "Camera start requested from JavaScript")
        onStartFaceDetection()
    }

    @JavascriptInterface
    fun stopFaceDetection() {
        Log.i(TAG, "Camera stop requested from JavaScript")
        onStopFaceDetection()
    }

    @JavascriptInterface
    fun startFaceEnrollment(personId: String): String {
        Log.i(TAG, "Face enrollment requested from JavaScript")
        return onStartFaceEnrollment(personId)
    }

    @JavascriptInterface
    fun startIdentityVerification(): String {
        Log.i(TAG, "Identity verification requested from JavaScript")
        return onStartIdentityVerification()
    }

    @JavascriptInterface
    fun startFaceVerification(): String = startIdentityVerification()

    @JavascriptInterface
    fun stopIdentityVerification(): String =
        onStopIdentityVerification()

    @JavascriptInterface
    fun stopFaceVerification(): String = stopIdentityVerification()

    @JavascriptInterface
    fun clearFaceTemplate(): String = onClearFaceTemplate()

    @JavascriptInterface
    fun removeFaceTemplate(personId: String): String =
        onRemoveFaceTemplate(personId)

    @JavascriptInterface
    fun getRegisteredFaces(): String = onGetRegisteredFaces()

    @JavascriptInterface
    fun setVerificationThreshold(value: Float): String =
        onSetVerificationThreshold(value)

    @JavascriptInterface
    fun applyProvisionalThreshold(value: Float): String =
        onSetVerificationThreshold(value)

    @JavascriptInterface
    fun setFaceDiagnosticsEnabled(enabled: Boolean): String =
        onSetDiagnosticsEnabled(enabled)

    @JavascriptInterface
    fun clearFaceDiagnostics(): String = onClearDiagnostics()

    @JavascriptInterface
    fun getIdentityStatus(): String = onGetIdentityStatus()

    private companion object {
        const val TAG = "SmartDeskTablet"
    }
}
