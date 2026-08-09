package com.smartdesk.tablet.bridge

import android.os.Build
import android.util.Log
import android.webkit.JavascriptInterface
import com.smartdesk.tablet.BuildConfig
import com.smartdesk.tablet.config.DeviceConfig
import com.smartdesk.tablet.model.AndroidEvent
import org.json.JSONObject

class AndroidBridge(
    private val defaultDeviceId: String,
    private val onGetDeviceConfig: () -> DeviceConfig?,
    private val onGetRuntimeStatus: () -> JSONObject,
    private val onGetDeviceCredential: () -> String,
    private val onProvisionDeviceConfig: (String) -> String,
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
        val data = JSONObject()
            .put("deviceId", config?.deviceId ?: defaultDeviceId)
            .put("seatId", config?.seatId ?: JSONObject.NULL)
            .put("seatAlias", config?.seatAlias ?: JSONObject.NULL)
            .put("centralHost", config?.centralHost() ?: JSONObject.NULL)
            .put("serverUrl", config?.serverUrl ?: JSONObject.NULL)
            .put("serverBaseUrl", config?.serverUrl ?: JSONObject.NULL)
            .put("frontendUrl", config?.frontendUrl ?: JSONObject.NULL)
            .put(
                "frontendBaseUrl",
                config?.frontendUrl ?: JSONObject.NULL
            )
            .put("configured", config != null)
            .put("deviceTokenConfigured", config != null)
            .put("manufacturer", Build.MANUFACTURER)
            .put("model", Build.MODEL)
            .put("androidVersion", Build.VERSION.RELEASE)
            .put("sdkInt", Build.VERSION.SDK_INT)
            .put("appVersion", BuildConfig.VERSION_NAME)
            .put("bridgeReady", true)
            .also { payload ->
                val runtime = onGetRuntimeStatus()
                runtime.keys().forEach { key ->
                    payload.put(key, runtime.get(key))
                }
            }

        Log.i(TAG, "Device info requested")
        return AndroidEvent.event("device_info", data)
    }

    @JavascriptInterface
    fun getDeviceConfig(): String {
        val config = onGetDeviceConfig()
        return AndroidEvent.event(
            "device_config",
            config?.toJson() ?: JSONObject()
        )
    }

    @JavascriptInterface
    fun getDeviceCredential(): String = onGetDeviceCredential()

    @JavascriptInterface
    fun provisionDeviceConfig(configJson: String): String =
        onProvisionDeviceConfig(configJson)

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
