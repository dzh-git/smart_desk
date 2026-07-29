package com.smartdesk.tablet

import android.annotation.SuppressLint
import android.Manifest
import android.app.AlertDialog
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.net.Uri
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkRequest
import android.os.Bundle
import android.os.Looper
import android.provider.Settings
import android.util.Log
import android.view.View
import android.widget.Button
import android.widget.FrameLayout
import android.widget.TextView
import android.webkit.PermissionRequest
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
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
import com.smartdesk.tablet.web.BackendHealthChecker
import com.smartdesk.tablet.web.SeatPageLoadState
import com.smartdesk.tablet.web.WebViewAccessPolicy
import com.smartdesk.tablet.web.WebViewPageAccessState
import org.json.JSONObject
import java.util.concurrent.Executors

class MainActivity : ComponentActivity() {
    private lateinit var webView: WebView
    private lateinit var maintenanceButton: Button
    private lateinit var cameraOverlay: FrameLayout
    private lateinit var faceDetectionStatusText: TextView
    private lateinit var faceGuideView: com.smartdesk.tablet.camera.FaceGuideView
    private lateinit var fillLightOverlay: FillLightOverlayView
    private lateinit var cameraController: CameraController
    private lateinit var deviceConfigStore: DeviceConfigStore
    private var recognitionManager: FaceRecognitionManager? = null
    private var recognitionInitError: Throwable? = null
    private var lastNativeError: String? = null
    private var cameraState = CameraState.IDLE
    private var lastFaceStatus: String? = null
    private var lastFaceEventAtMs = 0L
    private var originalScreenBrightness: Float? = null
    private val pageAccessState = WebViewPageAccessState(LOCAL_ASSET_PREFIX)
    private var connectivityManager: ConnectivityManager? = null
    private var networkCallbackRegistered = false
    private var pendingMicrophoneRequest: PermissionRequest? = null
    private val pageLoadState = SeatPageLoadState()
    private val backendHealthChecker = BackendHealthChecker()
    private val healthExecutor = Executors.newSingleThreadExecutor()
    private var healthCheckGeneration = 0
    private var pageLoadTimeoutAction: Runnable? = null
    private val networkCallback = object : ConnectivityManager.NetworkCallback() {
        override fun onAvailable(network: Network) {
            if (
                pageAccessState.isDiagnosticPage() &&
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
            lastNativeError = ErrorCode.CAMERA_PERMISSION_DENIED
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
            lastNativeError = (
                error.message ?: ErrorCode.FACE_MODEL_INIT_FAILED
            )
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
                lastNativeError = "$code:${error.message.orEmpty()}"
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
        maintenanceButton = findViewById(R.id.maintenanceButton)
        maintenanceButton.setOnClickListener {
            AlertDialog.Builder(this)
                .setTitle(R.string.device_maintenance_title)
                .setMessage(R.string.device_maintenance_message)
                .setNegativeButton(R.string.cancel, null)
                .setPositiveButton(
                    R.string.device_maintenance_confirm
                ) { _, _ ->
                    openMaintenancePage()
                }
                .show()
        }
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
                onGetRuntimeStatus = ::nativeRuntimeStatus,
                onGetDeviceCredential = ::getDeviceCredential,
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
        webView.webChromeClient = TabletWebChromeClient()
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
            AndroidEvent.event(
                "device_config_saved",
                config.toJson()
            )
        }.getOrElse { error ->
            Log.w(TAG, "Rejected device configuration", error)
            AndroidEvent.error(
                ErrorCode.DEVICE_CONFIG_INVALID,
                error.message ?: "设备配置无效"
            )
        }
    }
    private val microphonePermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        val request = pendingMicrophoneRequest
        pendingMicrophoneRequest = null
        if (request == null) {
            return@registerForActivityResult
        }
        if (granted && mayGrantMicrophone(request, true)) {
            request.grant(arrayOf(PermissionRequest.RESOURCE_AUDIO_CAPTURE))
            if (recognitionManager != null) {
                lastNativeError = null
            }
            Log.i(TAG, "WebView microphone permission granted")
        } else {
            request.deny()
            Log.w(TAG, "WebView microphone permission denied")
            lastNativeError = ErrorCode.MICROPHONE_PERMISSION_DENIED
            emitToReact(
                AndroidEvent.error(
                    ErrorCode.MICROPHONE_PERMISSION_DENIED,
                    "未获得麦克风权限"
                )
            )
        }
    }

    private fun retryConfiguredPageIfNeeded() {
        if (
            pageAccessState.isDiagnosticPage() &&
            deviceConfigStore.load() != null
        ) {
            pageLoadState.retry()
            loadConfiguredPage()
        }
    }

    private fun getDeviceCredential(): String {
        if (!isTrustedSeatPage()) {
            return AndroidEvent.error(
                ErrorCode.BRIDGE_ACTION_FORBIDDEN,
                "设备凭据只能提供给已配置的正式席位页面"
            )
        }
        val config = deviceConfigStore.load()
            ?: return AndroidEvent.error(
                ErrorCode.DEVICE_CONFIG_INVALID,
                "设备尚未完成配置"
            )
        return AndroidEvent.event(
            "device_credential",
            JSONObject().put("deviceToken", config.deviceToken)
        )
    }

    private fun loadConfiguredPage() {
        val config = deviceConfigStore.load()
        if (config == null) {
            loadDiagnosticPage("setup")
            return
        }

        cancelSeatPageLoadTimeout()
        pageLoadState.beginHealthCheck()
        val generation = ++healthCheckGeneration
        if (
            pageAccessState.currentUrl().isNullOrBlank() ||
            pageAccessState.currentUrl() == "about:blank" ||
            pageAccessState.isDiagnosticPage()
        ) {
            loadDiagnosticPage("checking")
        }
        runCatching {
            healthExecutor.execute {
                val result = backendHealthChecker.check(config.serverUrl)
                webView.post {
                    if (generation != healthCheckGeneration || isFinishing) {
                        return@post
                    }
                    when (result) {
                        BackendHealthChecker.Result.HEALTHY ->
                            beginSeatPageLoad(config.seatPageUrl())
                        BackendHealthChecker.Result.OFFLINE -> {
                            pageLoadState.offline()
                            loadDiagnosticPage("offline")
                        }
                        BackendHealthChecker.Result.SERVER_ERROR -> {
                            pageLoadState.serverError()
                            loadDiagnosticPage("server-error")
                        }
                    }
                }
            }
        }.onFailure {
            pageLoadState.offline()
            loadDiagnosticPage("offline")
        }
    }

    private fun beginSeatPageLoad(url: String) {
        pageAccessState.update(null)
        pageLoadState.beginPageLoad()
        Log.i(TAG, "Loading configured seat page: $url")
        webView.loadUrl(url)
        cancelSeatPageLoadTimeout()
        val timeoutAction = Runnable {
            if (pageLoadState.timedOut()) {
                Log.e(TAG, "WebView seat page load timed out")
                webView.stopLoading()
                loadDiagnosticPage("timeout")
            }
        }
        pageLoadTimeoutAction = timeoutAction
        webView.postDelayed(timeoutAction, PAGE_LOAD_TIMEOUT_MS)
    }

    private fun loadDiagnosticPage(mode: String) {
        cancelSeatPageLoadTimeout()
        if (::maintenanceButton.isInitialized) {
            maintenanceButton.visibility = View.GONE
        }
        val url = "$LOCAL_PAGE_URL?mode=${Uri.encode(mode)}"
        val previousUrl = pageAccessState.currentUrl()
        if (previousUrl != url) {
            pageAccessState.update(null)
            Log.i(TAG, "Loading local diagnostic page: $mode")
            webView.loadUrl(url)
        }
    }

    private fun cancelSeatPageLoadTimeout() {
        pageLoadTimeoutAction?.let(webView::removeCallbacks)
        pageLoadTimeoutAction = null
    }

    private fun openMaintenancePage() {
        healthCheckGeneration += 1
        cancelPendingMicrophoneRequest()
        emitToReact(AndroidEvent.appLifecycle("PAUSED", "maintenance"))
        loadDiagnosticPage("maintenance")
    }

    private fun defaultDeviceId(): String {
        val androidId = Settings.Secure.getString(
            contentResolver,
            Settings.Secure.ANDROID_ID
        ).orEmpty()
        val suffix = androidId.takeLast(8).ifBlank { "unconfigured" }
        return "tablet-$suffix"
    }

    private fun nativeRuntimeStatus(): JSONObject =
        JSONObject()
            .put(
                "cameraReady",
                packageManager.hasSystemFeature(
                    PackageManager.FEATURE_CAMERA_FRONT
                )
            )
            .put("faceModelReady", recognitionManager != null)
            .put(
                "microphoneReady",
                packageManager.hasSystemFeature(
                    PackageManager.FEATURE_MICROPHONE
                )
            )
            .put(
                "nativeLastError",
                lastNativeError ?: JSONObject.NULL
            )

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
        val dispatch = Runnable {
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
        if (Looper.myLooper() == Looper.getMainLooper()) {
            dispatch.run()
        } else {
            webView.post(dispatch)
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
        pageAccessState.isDiagnosticPage()

    private fun isTrustedSeatPage(): Boolean {
        return pageAccessState.isTrustedSeatPage(deviceConfigStore.load())
    }

    private fun mayGrantMicrophone(
        request: PermissionRequest,
        androidPermissionGranted: Boolean
    ): Boolean = WebViewAccessPolicy.mayGrantMicrophone(
        originUrl = request.origin?.toString(),
        currentPageUrl = pageAccessState.currentUrl(),
        requestedResources = request.resources?.toList().orEmpty(),
        config = deviceConfigStore.load(),
        androidPermissionGranted = androidPermissionGranted
    )

    private fun cancelPendingMicrophoneRequest() {
        pendingMicrophoneRequest?.deny()
        pendingMicrophoneRequest = null
    }

    override fun onDestroy() {
        healthCheckGeneration += 1
        cancelSeatPageLoadTimeout()
        cancelPendingMicrophoneRequest()
        healthExecutor.shutdownNow()
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

    override fun onResume() {
        super.onResume()
        if (::webView.isInitialized) {
            webView.onResume()
            emitToReact(AndroidEvent.appLifecycle("RESUMED"))
        }
    }

    override fun onPause() {
        cancelPendingMicrophoneRequest()
        if (::webView.isInitialized) {
            emitToReact(AndroidEvent.appLifecycle("PAUSED", "activity"))
            webView.onPause()
        }
        if (
            ::cameraController.isInitialized &&
            cameraState != CameraState.IDLE
        ) {
            stopCamera()
        } else {
            setFillLightEnabled(false)
        }
        super.onPause()
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
            pageAccessState.update(url)
            Log.i(TAG, "WebView loading: $url")
        }

        override fun onPageFinished(view: WebView, url: String) {
            Log.i(TAG, "WebView loaded: $url")
            if (view.url != url) {
                Log.i(TAG, "Ignoring stale WebView completion: $url")
                return
            }
            pageAccessState.update(url)
            if (pageAccessState.isDiagnosticPage()) {
                maintenanceButton.visibility = View.GONE
            } else if (
                WebViewAccessPolicy.isTrustedSeatPage(
                    url,
                    deviceConfigStore.load()
                )
            ) {
                cancelSeatPageLoadTimeout()
                pageLoadState.ready()
                maintenanceButton.visibility = View.VISIBLE
            }
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
                    cancelSeatPageLoadTimeout()
                    pageLoadState.offline()
                    view.post {
                        loadDiagnosticPage("offline")
                    }
                }
            }
        }

        override fun onReceivedHttpError(
            view: WebView,
            request: WebResourceRequest,
            errorResponse: WebResourceResponse
        ) {
            if (
                request.isForMainFrame &&
                errorResponse.statusCode >= 400 &&
                !request.url.toString().startsWith(LOCAL_ASSET_PREFIX)
            ) {
                Log.e(
                    TAG,
                    "WebView main frame HTTP ${errorResponse.statusCode}"
                )
                cancelSeatPageLoadTimeout()
                pageLoadState.serverError()
                view.post {
                    loadDiagnosticPage("server-error")
                }
            }
        }

        private fun isConfiguredFrontendUri(uri: Uri): Boolean {
            return WebViewAccessPolicy.isTrustedFrontendOrigin(
                uri.toString(),
                deviceConfigStore.load()
            )
        }

    }

    private inner class TabletWebChromeClient : WebChromeClient() {
        override fun onPermissionRequest(request: PermissionRequest) {
            runOnUiThread {
                if (!mayGrantMicrophone(request, true)) {
                    Log.w(
                        TAG,
                        "Blocked WebView resource request from ${request.origin}"
                    )
                    request.deny()
                    return@runOnUiThread
                }

                if (
                    ContextCompat.checkSelfPermission(
                        this@MainActivity,
                        Manifest.permission.RECORD_AUDIO
                    ) == PackageManager.PERMISSION_GRANTED
                ) {
                    request.grant(
                        arrayOf(PermissionRequest.RESOURCE_AUDIO_CAPTURE)
                    )
                    return@runOnUiThread
                }

                cancelPendingMicrophoneRequest()
                pendingMicrophoneRequest = request
                microphonePermissionLauncher.launch(
                    Manifest.permission.RECORD_AUDIO
                )
            }
        }

        override fun onPermissionRequestCanceled(request: PermissionRequest) {
            runOnUiThread {
                if (pendingMicrophoneRequest === request) {
                    pendingMicrophoneRequest = null
                }
            }
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
        const val PAGE_LOAD_TIMEOUT_MS = 15_000L
    }

    private enum class CameraState {
        IDLE,
        STARTING,
        RUNNING,
        STOPPING
    }
}
