package com.smartdesk.tablet

import android.annotation.SuppressLint
import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.net.Uri
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkRequest
import android.os.Bundle
import android.provider.Settings
import android.util.Log
import android.view.View
import android.widget.Button
import android.widget.FrameLayout
import android.widget.TextView
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import com.smartdesk.tablet.bridge.AndroidBridge
import com.smartdesk.tablet.camera.CameraController
import com.smartdesk.tablet.camera.FillLightOverlayView
import com.smartdesk.tablet.config.DeviceConfigStore
import com.smartdesk.tablet.model.AndroidEvent
import com.smartdesk.tablet.model.ErrorCode
import com.smartdesk.tablet.model.FaceDetectionResult
import com.smartdesk.tablet.model.IdentityStatus
import com.smartdesk.tablet.recognition.FaceRecognitionManager
import org.json.JSONObject

class MainActivity : ComponentActivity() {
    private lateinit var webView: WebView
    private lateinit var cameraOverlay: FrameLayout
    private lateinit var faceDetectionStatusText: TextView
    private lateinit var faceGuideView: com.smartdesk.tablet.camera.FaceGuideView
    private lateinit var fillLightOverlay: FillLightOverlayView
    private lateinit var cameraController: CameraController
    private lateinit var deviceConfigStore: DeviceConfigStore
    private var recognitionManager: FaceRecognitionManager? = null
    private var recognitionInitError: Throwable? = null
    private var cameraState = CameraState.IDLE
    private var lastFaceStatus: String? = null
    private var lastFaceEventAtMs = 0L
    private var originalScreenBrightness: Float? = null
    private var showingDiagnosticPage = false
    private var connectivityManager: ConnectivityManager? = null
    private var networkCallbackRegistered = false
    private val networkCallback = object : ConnectivityManager.NetworkCallback() {
        override fun onAvailable(network: Network) {
            if (
                showingDiagnosticPage &&
                ::deviceConfigStore.isInitialized &&
                deviceConfigStore.load() != null
            ) {
                webView.postDelayed(
                    ::retryConfiguredPageIfNeeded,
                    NETWORK_RETRY_DELAY_MS
                )
            }
        }
    }
    private val cameraPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (cameraState != CameraState.STARTING) {
            Log.i(TAG, "Ignoring camera permission result in state=$cameraState")
            return@registerForActivityResult
        }

        if (granted) {
            Log.i(TAG, "Camera permission granted")
            startCamera()
        } else {
            Log.w(TAG, "Camera permission denied")
            cameraState = CameraState.IDLE
            cameraOverlay.visibility = View.GONE
            emitToReact(
                AndroidEvent.error(
                    ErrorCode.CAMERA_PERMISSION_DENIED,
                    "未获得摄像头权限"
                )
            )
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Log.i(TAG, "App started")
        setContentView(R.layout.activity_main)
        deviceConfigStore = DeviceConfigStore(applicationContext)
        configureIdentityRecognition()
        configureCamera()
        configureWebView()
    }

    private fun configureIdentityRecognition() {
        runCatching {
            FaceRecognitionManager(
                context = applicationContext,
                onStatus = { result ->
                    runOnUiThread {
                        handleIdentityStatus(result)
                    }
                },
                onRequestMetering = {
                    runOnUiThread {
                        if (::cameraController.isInitialized) {
                            cameraController.requestGuideMetering()
                        }
                    }
                },
                onFillLightChanged = { enabled ->
                    runOnUiThread {
                        setFillLightEnabled(enabled)
                    }
                }
            )
        }.onSuccess { manager ->
            recognitionManager = manager
        }.onFailure { error ->
            recognitionInitError = error
            Log.e(TAG, "MobileFaceNet initialization failed", error)
        }
    }

    private fun configureCamera() {
        cameraOverlay = findViewById(R.id.cameraOverlay)
        faceDetectionStatusText = findViewById(R.id.faceDetectionStatusText)
        faceGuideView = findViewById(R.id.faceGuideView)
        fillLightOverlay = findViewById(R.id.fillLightOverlay)
        val previewView = findViewById<PreviewView>(R.id.previewView).apply {
            implementationMode = PreviewView.ImplementationMode.COMPATIBLE
            scaleType = PreviewView.ScaleType.FILL_CENTER
        }
        findViewById<Button>(R.id.stopCameraButton).setOnClickListener {
            stopCamera()
        }
        cameraController = CameraController(
            activity = this,
            previewView = previewView,
            onStarted = {
                cameraState = CameraState.RUNNING
                lastFaceStatus = null
                lastFaceEventAtMs = 0L
                faceGuideView.reset()
                faceDetectionStatusText.setText(R.string.camera_preview_hint)
                emitToReact(AndroidEvent.cameraStatus("CAMERA_RUNNING"))
                Log.i(TAG, "Front camera preview running")
            },
            onFacesDetected = { result ->
                runOnUiThread {
                    handleFaceDetectionResult(result)
                }
            },
            shouldProduceFaceCrop = {
                recognitionManager?.needsFaceCrop() == true
            },
            onFaceCrop = { crop ->
                try {
                    recognitionManager?.processFace(
                        crop.bitmap,
                        crop.processingTimeMs,
                        crop.brightness,
                        crop.sharpness
                    )
                } catch (error: Throwable) {
                    Log.e(TAG, "Face embedding/verification failed", error)
                    recognitionManager?.reportProcessingError(
                        error.message ?: "人脸特征提取失败"
                    )
                    emitToReact(
                        AndroidEvent.error(
                            ErrorCode.FACE_EMBEDDING_FAILED,
                            error.message ?: "人脸特征提取失败",
                            cameraStillRunning = true
                        )
                    )
                }
            },
            onQualityRejected = { message ->
                recognitionManager?.reportQualityHint(message)
            },
            onCropError = { error ->
                recognitionManager?.reportProcessingError(
                    error.message ?: "人脸裁剪与对齐失败"
                )
                emitToReact(
                    AndroidEvent.error(
                        ErrorCode.FACE_CROP_FAILED,
                        error.message ?: "人脸裁剪与对齐失败",
                        cameraStillRunning = true
                    )
                )
            },
            onDetectionError = { error ->
                runOnUiThread {
                    faceDetectionStatusText.setText(R.string.face_status_error)
                }
                emitToReact(
                    AndroidEvent.error(
                        ErrorCode.FACE_DETECTION_FAILED,
                        error.message ?: "人脸检测失败",
                        cameraStillRunning = true
                    )
                )
            },
            onError = { code, error ->
                cameraOverlay.visibility = View.GONE
                cameraState = CameraState.IDLE
                emitToReact(
                    AndroidEvent.error(
                        code,
                        error.message ?: "前置摄像头启动失败"
                    )
                )
            }
        )
    }

    private fun handleFaceDetectionResult(result: FaceDetectionResult) {
        if (cameraState != CameraState.RUNNING) {
            return
        }

        val now = System.currentTimeMillis()
        faceGuideView.updateFaceStatus(result.status)
        if (result.status != "ONE_FACE") {
            recognitionManager?.reportGuideInterruption(result.faceCount)
        }
        if (
            result.status != lastFaceStatus ||
            now - lastFaceEventAtMs >= FACE_EVENT_HEARTBEAT_MS
        ) {
            val identityActive =
                recognitionManager?.needsFaceCrop() == true
            if (!identityActive || result.status != "ONE_FACE") {
                faceDetectionStatusText.text = when (result.status) {
                "NO_FACE" -> getString(R.string.face_status_none)
                "ONE_FACE" -> getString(
                    R.string.face_status_one,
                    result.processingTimeMs
                )
                else -> getString(
                    R.string.face_status_multiple,
                    result.faceCount,
                    result.processingTimeMs
                )
                }
            }
            emitToReact(AndroidEvent.faceDetectionStatus(result))
            lastFaceStatus = result.status
            lastFaceEventAtMs = now
        }
    }

    private fun handleIdentityStatus(result: IdentityStatus) {
        faceGuideView.updateIdentityStatus(result.status)
        if (cameraState == CameraState.RUNNING) {
            val similarity = result.similarity ?: 0f
            faceDetectionStatusText.text = when (result.status) {
                "ENROLLING" -> if (
                    result.message.startsWith("光线") ||
                    result.message.startsWith("画面") ||
                    result.message.startsWith("请正对") ||
                    result.message.startsWith("样本")
                ) {
                    result.message
                } else {
                    getString(
                        R.string.face_enrolling,
                        result.sampleCount,
                        result.requiredSamples
                    )
                }
                "ENROLLED" -> getString(R.string.face_enrolled)
                "VERIFYING" -> if (
                    result.message.startsWith("光线") ||
                    (
                        result.similarity == null &&
                            (
                                result.message.startsWith("画面") ||
                                    result.message.startsWith("请正对")
                                )
                        )
                ) {
                    result.message
                } else {
                    getString(
                        R.string.face_verifying,
                        similarity
                    )
                }
                "VERIFIED" -> getString(
                    R.string.face_verified,
                    similarity
                )
                "UNKNOWN" -> getString(
                    R.string.face_unknown,
                    similarity
                )
                "RETRY_REQUIRED" -> result.message
                "CALIBRATION_PENDING" -> result.message
                "MULTIPLE_FACES" ->
                    getString(R.string.face_status_guide_multiple)
                "WAITING_FOR_FACE" ->
                    getString(R.string.face_status_guide_waiting)
                "ERROR" -> result.message
                else -> faceDetectionStatusText.text
            }
        }
        emitToReact(AndroidEvent.identityStatus(result))
    }

    @SuppressLint("SetJavaScriptEnabled")
    @Suppress("DEPRECATION")
    private fun configureWebView() {
        webView = findViewById(R.id.webView)
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = true
            allowContentAccess = false
            // Vite emits ES modules under the same trusted android_asset tree.
            allowFileAccessFromFileURLs = true
            allowUniversalAccessFromFileURLs = false
        }
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG)
        webView.addJavascriptInterface(
            AndroidBridge(
                defaultDeviceId = defaultDeviceId(),
                onGetDeviceConfig = deviceConfigStore::load,
                onSaveDeviceConfig = ::saveDeviceConfiguration,
                onReloadSeatPage = {
                    runOnUiThread(::loadConfiguredPage)
                },
                onStartFaceDetection = {
                    runOnUiThread(::requestStartCamera)
                },
                onStopFaceDetection = {
                    runOnUiThread(::stopCamera)
                },
                onStartFaceEnrollment = { personId ->
                    performDiagnosticIdentityAction(
                        ErrorCode.FACE_MODEL_INIT_FAILED
                    ) {
                        val result = requireRecognitionManager()
                            .startEnrollment(personId)
                        runOnUiThread(::requestStartCamera)
                        AndroidEvent.identityStatus(result)
                    }
                },
                onStartIdentityVerification = {
                    performIdentityAction(ErrorCode.FACE_TEMPLATE_NOT_FOUND) {
                        val result = requireRecognitionManager()
                            .startVerification()
                        runOnUiThread(::requestStartCamera)
                        AndroidEvent.identityStatus(result)
                    }
                },
                onStopIdentityVerification = {
                    performIdentityAction(ErrorCode.UNKNOWN_ERROR) {
                        val result = requireRecognitionManager().stop()
                        runOnUiThread(::stopCamera)
                        AndroidEvent.identityStatus(result)
                    }
                },
                onClearFaceTemplate = {
                    performDiagnosticIdentityAction(
                        ErrorCode.UNKNOWN_ERROR
                    ) {
                        AndroidEvent.identityStatus(
                            requireRecognitionManager().clearTemplates()
                        )
                    }
                },
                onRemoveFaceTemplate = { personId ->
                    performDiagnosticIdentityAction(
                        ErrorCode.UNKNOWN_ERROR
                    ) {
                        AndroidEvent.identityStatus(
                            requireRecognitionManager()
                                .removeTemplate(personId)
                        )
                    }
                },
                onGetRegisteredFaces = {
                    performIdentityAction(ErrorCode.UNKNOWN_ERROR) {
                        AndroidEvent.registeredPeople(
                            requireRecognitionManager()
                                .registeredPeople()
                        )
                    }
                },
                onSetVerificationThreshold = { value ->
                    performDiagnosticIdentityAction(
                        ErrorCode.UNKNOWN_ERROR
                    ) {
                        AndroidEvent.identityStatus(
                            requireRecognitionManager()
                                .applyProvisionalThreshold(value)
                        )
                    }
                },
                onSetDiagnosticsEnabled = { enabled ->
                    performDiagnosticIdentityAction(
                        ErrorCode.UNKNOWN_ERROR
                    ) {
                        AndroidEvent.identityStatus(
                            requireRecognitionManager()
                                .setDiagnosticsEnabled(enabled)
                        )
                    }
                },
                onClearDiagnostics = {
                    performDiagnosticIdentityAction(
                        ErrorCode.UNKNOWN_ERROR
                    ) {
                        AndroidEvent.identityStatus(
                            requireRecognitionManager()
                                .clearDiagnostics()
                        )
                    }
                },
                onGetIdentityStatus = {
                    performIdentityAction(ErrorCode.FACE_MODEL_INIT_FAILED) {
                        AndroidEvent.identityStatus(
                            requireRecognitionManager().currentStatus()
                        )
                    }
                }
            ),
            BRIDGE_NAME
        )
        webView.webViewClient = TabletWebViewClient()
        registerNetworkRetry()
        loadConfiguredPage()
    }

    private fun saveDeviceConfiguration(payload: String): String {
        if (!isDiagnosticPage()) {
            return AndroidEvent.error(
                ErrorCode.BRIDGE_ACTION_FORBIDDEN,
                "设备配置只能从本地诊断页面修改"
            )
        }
        return runCatching {
            val config = deviceConfigStore.save(payload)
            webView.postDelayed(::loadConfiguredPage, CONFIG_RELOAD_DELAY_MS)
            JSONObject()
                .put("type", "device_config_saved")
                .put("data", config.toJson())
                .toString()
        }.getOrElse { error ->
            Log.w(TAG, "Rejected device configuration", error)
            AndroidEvent.error(
                ErrorCode.DEVICE_CONFIG_INVALID,
                error.message ?: "设备配置无效"
            )
        }
    }

    private fun retryConfiguredPageIfNeeded() {
        if (showingDiagnosticPage && deviceConfigStore.load() != null) {
            loadConfiguredPage()
        }
    }

    private fun loadConfiguredPage() {
        val config = deviceConfigStore.load()
        if (config == null) {
            loadDiagnosticPage("setup")
            return
        }

        showingDiagnosticPage = false
        val url = config.seatPageUrl()
        Log.i(TAG, "Loading configured seat page: $url")
        webView.loadUrl(url)
    }

    private fun loadDiagnosticPage(mode: String) {
        showingDiagnosticPage = true
        val url = "$LOCAL_PAGE_URL?mode=${Uri.encode(mode)}"
        if (webView.url != url) {
            Log.i(TAG, "Loading local diagnostic page: $mode")
            webView.loadUrl(url)
        }
    }

    private fun defaultDeviceId(): String {
        val androidId = Settings.Secure.getString(
            contentResolver,
            Settings.Secure.ANDROID_ID
        ).orEmpty()
        val suffix = androidId.takeLast(8).ifBlank { "unconfigured" }
        return "tablet-$suffix"
    }

    private fun registerNetworkRetry() {
        val manager = getSystemService(ConnectivityManager::class.java)
        connectivityManager = manager
        runCatching {
            manager.registerNetworkCallback(
                NetworkRequest.Builder().build(),
                networkCallback
            )
            networkCallbackRegistered = true
        }.onFailure {
            Log.w(TAG, "Network retry callback unavailable", it)
        }
    }

    private fun requestStartCamera() {
        if (cameraState != CameraState.IDLE) {
            Log.i(TAG, "Camera start ignored in state=$cameraState")
            return
        }

        cameraState = CameraState.STARTING
        emitToReact(AndroidEvent.cameraStatus("CAMERA_STARTING"))

        if (
            ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) ==
            PackageManager.PERMISSION_GRANTED
        ) {
            Log.i(TAG, "Camera permission already granted")
            startCamera()
        } else {
            Log.i(TAG, "Requesting camera permission")
            cameraPermissionLauncher.launch(Manifest.permission.CAMERA)
        }
    }

    private fun startCamera() {
        if (cameraState != CameraState.STARTING) {
            Log.i(TAG, "Camera start skipped in state=$cameraState")
            return
        }
        cameraOverlay.visibility = View.VISIBLE
        cameraController.start()
    }

    private fun stopCamera() {
        recognitionManager?.stop()
        setFillLightEnabled(false)
        if (cameraState == CameraState.IDLE) {
            Log.i(TAG, "Camera stop ignored because it is already idle")
            return
        }

        cameraState = CameraState.STOPPING
        emitToReact(AndroidEvent.cameraStatus("CAMERA_STOPPING"))
        cameraController.stop()
        cameraOverlay.visibility = View.GONE
        faceGuideView.reset()
        lastFaceStatus = null
        cameraState = CameraState.IDLE
        emitToReact(AndroidEvent.cameraStatus(cameraState.name))
    }

    private fun emitToReact(payload: String) {
        if (!::webView.isInitialized) {
            Log.w(TAG, "Cannot emit event before WebView initialization")
            return
        }

        val quotedPayload = JSONObject.quote(payload)
        webView.post {
            webView.evaluateJavascript(
                """
                (() => {
                  const detail = JSON.parse($quotedPayload);
                  window.dispatchEvent(
                    new CustomEvent("smartdesk-native-event", { detail })
                  );
                })();
                """.trimIndent(),
                null
            )
        }
    }

    private fun requireRecognitionManager(): FaceRecognitionManager =
        recognitionManager ?: throw IllegalStateException(
            recognitionInitError?.message ?: "MobileFaceNet 尚未初始化"
        )

    private inline fun performIdentityAction(
        errorCode: String,
        action: () -> String
    ): String = runCatching(action).getOrElse { error ->
        Log.e(TAG, "Identity action failed", error)
        AndroidEvent.error(
            errorCode,
            error.message ?: "身份验证操作失败",
            cameraStillRunning = cameraState == CameraState.RUNNING
        )
    }

    private inline fun performDiagnosticIdentityAction(
        errorCode: String,
        action: () -> String
    ): String {
        if (!isDiagnosticPage()) {
            return AndroidEvent.error(
                ErrorCode.BRIDGE_ACTION_FORBIDDEN,
                "该操作只能从本地诊断页面执行"
            )
        }
        return performIdentityAction(errorCode, action)
    }

    private fun isDiagnosticPage(): Boolean =
        ::webView.isInitialized &&
            webView.url?.startsWith(LOCAL_ASSET_PREFIX) == true

    override fun onDestroy() {
        setFillLightEnabled(false)
        if (::cameraController.isInitialized) {
            cameraController.release()
        }
        recognitionManager?.close()
        if (networkCallbackRegistered) {
            runCatching {
                connectivityManager?.unregisterNetworkCallback(networkCallback)
            }
            networkCallbackRegistered = false
        }
        if (::webView.isInitialized) {
            webView.stopLoading()
            webView.loadUrl("about:blank")
            webView.clearHistory()
            webView.removeAllViews()
            webView.destroy()
        }
        super.onDestroy()
    }

    override fun onStop() {
        if (
            ::cameraController.isInitialized &&
            cameraState != CameraState.IDLE
        ) {
            stopCamera()
        } else {
            setFillLightEnabled(false)
        }
        super.onStop()
    }

    private fun setFillLightEnabled(enabled: Boolean) {
        if (!::fillLightOverlay.isInitialized) {
            return
        }
        if (enabled) {
            if (originalScreenBrightness == null) {
                originalScreenBrightness =
                    window.attributes.screenBrightness
            }
            window.attributes = window.attributes.apply {
                screenBrightness = 1f
            }
            fillLightOverlay.visibility = View.VISIBLE
        } else {
            fillLightOverlay.visibility = View.GONE
            val previous = originalScreenBrightness ?: return
            window.attributes = window.attributes.apply {
                screenBrightness = previous
            }
            originalScreenBrightness = null
        }
    }

    private inner class TabletWebViewClient : WebViewClient() {
        override fun onPageStarted(view: WebView, url: String, favicon: Bitmap?) {
            Log.i(TAG, "WebView loading: $url")
        }

        override fun onPageFinished(view: WebView, url: String) {
            Log.i(TAG, "WebView loaded: $url")
            showingDiagnosticPage = url.startsWith(LOCAL_ASSET_PREFIX)
        }

        override fun shouldOverrideUrlLoading(
            view: WebView,
            request: WebResourceRequest
        ): Boolean {
            val uri = request.url
            if (uri.toString().startsWith(LOCAL_ASSET_PREFIX)) {
                return false
            }

            if (isConfiguredFrontendUri(uri)) {
                return false
            }

            if (uri.scheme == "http" || uri.scheme == "https") {
                runCatching {
                    startActivity(Intent(Intent.ACTION_VIEW, uri))
                }.onFailure {
                    Log.e(TAG, "Unable to open external URL: $uri", it)
                }
            } else {
                Log.w(TAG, "Blocked WebView navigation: $uri")
            }
            return true
        }

        override fun onReceivedError(
            view: WebView,
            request: WebResourceRequest,
            error: WebResourceError
        ) {
            if (request.isForMainFrame) {
                Log.e(
                    TAG,
                    "WebView main frame error ${error.errorCode}: ${error.description}"
                )
                emitToReact(
                    AndroidEvent.error(
                        ErrorCode.WEBVIEW_LOAD_FAILED,
                        error.description.toString()
                    )
                )
                if (!request.url.toString().startsWith(LOCAL_ASSET_PREFIX)) {
                    view.post {
                        loadDiagnosticPage("offline")
                    }
                }
            }
        }

        private fun isConfiguredFrontendUri(uri: Uri): Boolean {
            val config = deviceConfigStore.load() ?: return false
            val configured = Uri.parse(config.frontendUrl)
            return uri.scheme == configured.scheme &&
                uri.host == configured.host &&
                effectivePort(uri) == effectivePort(configured)
        }

        private fun effectivePort(uri: Uri): Int =
            if (uri.port != -1) {
                uri.port
            } else if (uri.scheme == "https") {
                443
            } else {
                80
            }
    }

    private companion object {
        const val TAG = "SmartDeskTablet"
        const val BRIDGE_NAME = "SmartDeskNative"
        const val LOCAL_ASSET_PREFIX = "file:///android_asset/web/"
        const val LOCAL_PAGE_URL = "${LOCAL_ASSET_PREFIX}index.html"
        const val FACE_EVENT_HEARTBEAT_MS = 1_000L
        const val CONFIG_RELOAD_DELAY_MS = 250L
        const val NETWORK_RETRY_DELAY_MS = 1_000L
    }

    private enum class CameraState {
        IDLE,
        STARTING,
        RUNNING,
        STOPPING
    }
}
