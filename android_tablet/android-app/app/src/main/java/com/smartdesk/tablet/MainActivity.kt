package com.smartdesk.tablet

import android.annotation.SuppressLint
import android.Manifest
import android.app.AlertDialog
import android.content.Intent
import android.content.res.Configuration
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.net.Uri
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkRequest
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Log
import android.text.InputType
import android.view.MotionEvent
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.ImageButton
import android.widget.TextView
import android.widget.Toast
import android.webkit.PermissionRequest
import android.webkit.ValueCallback
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
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import com.smartdesk.tablet.bridge.AndroidBridge
import com.smartdesk.tablet.audio.NativeMicrophoneCapture
import com.smartdesk.tablet.camera.CameraController
import com.smartdesk.tablet.camera.FillLightOverlayView
import com.smartdesk.tablet.config.DeviceConfig
import com.smartdesk.tablet.config.DeviceConfigStore
import com.smartdesk.tablet.config.DeviceIdentityStore
import com.smartdesk.tablet.config.HostConsoleAccessStore
import com.smartdesk.tablet.config.MaintenancePinStore
import com.smartdesk.tablet.config.ProvisioningRequest
import com.smartdesk.tablet.model.AndroidEvent
import com.smartdesk.tablet.model.ErrorCode
import com.smartdesk.tablet.model.FaceDetectionResult
import com.smartdesk.tablet.model.IdentityStatus
import com.smartdesk.tablet.recognition.FacePhotoImportRequest
import com.smartdesk.tablet.recognition.FaceTemplateSyncClient
import com.smartdesk.tablet.recognition.FaceRecognitionManager
import com.smartdesk.tablet.provisioning.DeviceTokenGenerator
import com.smartdesk.tablet.provisioning.TabletApiResult
import com.smartdesk.tablet.provisioning.TabletDeviceClient
import com.smartdesk.tablet.web.BackendHealthChecker
import com.smartdesk.tablet.web.PageHealthRecoveryAction
import com.smartdesk.tablet.web.SeatPageLoadState
import com.smartdesk.tablet.web.WebViewAccessPolicy
import com.smartdesk.tablet.web.WebViewPageHealthWatchdog
import com.smartdesk.tablet.web.WebViewPageAccessState
import org.json.JSONObject
import java.util.concurrent.Executors

class MainActivity : ComponentActivity() {
    private lateinit var webView: WebView
    private lateinit var maintenanceButton: ImageButton
    private lateinit var cameraOverlay: FrameLayout
    private lateinit var faceDetectionStatusText: TextView
    private lateinit var faceGuideView: com.smartdesk.tablet.camera.FaceGuideView
    private lateinit var fillLightOverlay: FillLightOverlayView
    private lateinit var cameraController: CameraController
    private lateinit var deviceConfigStore: DeviceConfigStore
    private lateinit var deviceIdentityStore: DeviceIdentityStore
    private lateinit var hostConsoleAccessStore: HostConsoleAccessStore
    private lateinit var maintenancePinStore: MaintenancePinStore
    private lateinit var stableDeviceId: String
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
    private var pendingFileChooser: ValueCallback<Array<Uri>>? = null
    private var pendingNativeMicrophoneStart = false
    private val nativeMicrophoneCapture by lazy {
        NativeMicrophoneCapture(
            onFrame = { pcm16 ->
                emitToReact(AndroidEvent.microphoneAudio(pcm16))
            },
            onError = { error ->
                lastNativeError = ErrorCode.MICROPHONE_CAPTURE_FAILED
                emitToReact(
                    AndroidEvent.error(
                        ErrorCode.MICROPHONE_CAPTURE_FAILED,
                        error.message ?: "Android 麦克风采集失败"
                    )
                )
            }
        )
    }
    private val pageLoadState = SeatPageLoadState()
    private val pageHealthWatchdog = WebViewPageHealthWatchdog()
    private val backendHealthChecker = BackendHealthChecker()
    private val healthExecutor = Executors.newSingleThreadExecutor()
    private val provisioningExecutor = Executors.newSingleThreadExecutor()
    private val mainHandler = Handler(Looper.getMainLooper())
    private val tabletDeviceClient = TabletDeviceClient()
    private val faceTemplateSyncClient = FaceTemplateSyncClient()
    private val deviceTokenGenerator = DeviceTokenGenerator()
    private var healthCheckGeneration = 0
    private var provisioningInProgress = false
    @Volatile
    private var identityMode = "formal"
    private var maintenanceAuthorized = false
    private var maintenanceUnlockAction: Runnable? = null
    private var maintenanceExpiryAction: Runnable? = null
    private var offlineRetryAction: Runnable? = null
    private var pageLoadTimeoutAction: Runnable? = null
    private var pageHealthProbeAction: Runnable? = null
    private var pageHealthProbeTimeoutAction: Runnable? = null
    private var pageHealthProbeGeneration = 0
    private var pageHealthProbeStartedAtMs = 0L
    private var activityResumed = false
    private val networkCallback = object : ConnectivityManager.NetworkCallback() {
        override fun onAvailable(network: Network) {
            if (
                isWaitingPage() &&
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

    private val fileChooserLauncher = registerForActivityResult(
        ActivityResultContracts.OpenMultipleDocuments()
    ) { uris ->
        val callback = pendingFileChooser
        pendingFileChooser = null
        callback?.onReceiveValue(uris.toTypedArray())
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Log.i(TAG, "App started")
        hideSystemNavigationBar()
        setContentView(R.layout.activity_main)
        deviceConfigStore = DeviceConfigStore(applicationContext)
        deviceIdentityStore = DeviceIdentityStore(applicationContext)
        hostConsoleAccessStore = HostConsoleAccessStore(this)
        stableDeviceId = deviceIdentityStore.getOrCreate(
            deviceConfigStore.load()?.deviceId
        )
        maintenancePinStore = MaintenancePinStore(applicationContext)
        configureIdentityRecognition()
        configureCamera()
        configureWebView()
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) {
            hideSystemNavigationBar()
        }
    }

    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        hideSystemNavigationBar()
        if (::webView.isInitialized) {
            webView.invalidate()
        }
    }

    /**
     * Keep the meeting surface clear of the persistent three-button bar.
     * A swipe from the bottom temporarily reveals the system navigation,
     * so kiosk users can still leave the app when maintenance requires it.
     */
    private fun hideSystemNavigationBar() {
        WindowInsetsControllerCompat(window, window.decorView).apply {
            hide(WindowInsetsCompat.Type.navigationBars())
            systemBarsBehavior =
                WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        }
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
        IdentityCameraOverlayPolicy.closeDelayMs(result.status)?.let { delayMs ->
            mainHandler.postDelayed(
                {
                    if (
                        cameraState == CameraState.RUNNING &&
                        recognitionManager?.currentStatus()?.status == "VERIFIED"
                    ) {
                        stopCamera()
                    }
                },
                delayMs
            )
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    @Suppress("DEPRECATION")
    private fun configureWebView() {
        webView = findViewById(R.id.webView)
        maintenanceButton = findViewById(R.id.maintenanceButton)
        configureMaintenanceGesture()
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
                defaultDeviceId = stableDeviceId,
                onGetDeviceConfig = deviceConfigStore::load,
                onGetRuntimeStatus = ::nativeRuntimeStatus,
                onGetDeviceCredential = ::getDeviceCredential,
                onProvisionDeviceConfig = ::provisionDeviceConfiguration,
                onReloadSeatPage = {
                    runOnUiThread(::loadConfiguredPage)
                },
                onBeginMaintenanceHold = {
                    runOnUiThread {
                        if (isTrustedOperationalPage()) {
                            scheduleMaintenanceUnlock()
                        }
                    }
                },
                onCancelMaintenanceHold = {
                    runOnUiThread(::cancelMaintenanceUnlock)
                },
                onGetHostConsoleAccess = ::hostConsoleAccessStatus,
                onRequestHostConsoleAccess = ::requestHostConsoleAccess,
                onStartMicrophoneCapture = {
                    runOnUiThread(::requestStartNativeMicrophoneCapture)
                },
                onStopMicrophoneCapture = {
                    runOnUiThread(::stopNativeMicrophoneCapture)
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
                onStartIdentityVerification = { personId ->
                    performIdentityAction(ErrorCode.FACE_TEMPLATE_NOT_FOUND) {
                        val result = requireRecognitionManager()
                            .startVerification(personId)
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
                    performMaintenanceIdentityAction(
                        ErrorCode.UNKNOWN_ERROR
                    ) {
                        AndroidEvent.identityStatus(
                            requireRecognitionManager()
                                .removeTemplate(personId)
                        )
                    }
                },
                onImportFacePhotos = { personId, photosJson ->
                    performMaintenanceIdentityAction(
                        ErrorCode.FACE_PHOTO_IMPORT_FAILED
                    ) {
                        val photos = FacePhotoImportRequest.parse(photosJson)
                        AndroidEvent.facePhotoImportResult(
                            requireRecognitionManager().importFacePhotos(
                                personId,
                                photos
                            )
                        )
                    }
                },
                onPublishCentralFaceTemplate = { personId, photosJson ->
                    performHostFaceTemplateAction(
                        ErrorCode.FACE_PHOTO_IMPORT_FAILED
                    ) {
                        val config = requireNotNull(deviceConfigStore.load())
                        val photos = FacePhotoImportRequest.parse(photosJson)
                        val manager = requireRecognitionManager()
                        val generated = manager.generateCentralTemplate(
                            personId,
                            photos
                        )
                        val data = faceTemplateSyncClient.publishFromHost(
                            config,
                            personId,
                            generated,
                            manager
                        )
                        AndroidEvent.event("central_face_template_result", data)
                    }
                },
                onSyncFaceTemplates = { meetingId ->
                    performParticipantTemplateSync(
                        ErrorCode.FACE_TEMPLATE_NOT_FOUND
                    ) {
                        val config = requireNotNull(deviceConfigStore.load())
                        val data = faceTemplateSyncClient.syncActiveMeeting(
                            config,
                            meetingId,
                            requireRecognitionManager()
                        )
                        AndroidEvent.event("face_template_sync", data)
                    }
                },
                onOpenLocalDiagnostics = {
                    runOnUiThread {
                        if (isHostFaceTemplatesPage() && maintenanceAuthorized) {
                            loadDiagnosticPage("maintenance")
                        }
                    }
                },
                onCloseHostFaceTemplates = {
                    runOnUiThread {
                        clearMaintenanceAuthorization()
                        loadConfiguredPage()
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
                onGetDefaultHostIdentity = {
                    performIdentityAction(ErrorCode.UNKNOWN_ERROR) {
                        hostIdentityEvent(requireRecognitionManager())
                    }
                },
                onSetDefaultHostIdentity = { personId ->
                    performHostFaceTemplateAction(ErrorCode.UNKNOWN_ERROR) {
                        val manager = requireRecognitionManager()
                        manager.setDefaultHostPersonId(personId)
                        hostIdentityEvent(manager)
                    }
                },
                onSetVerificationThreshold = { value ->
                    performHostFaceTemplateAction(
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

    private fun provisionDeviceConfiguration(payload: String): String {
        val existingConfig = deviceConfigStore.load()
        if (
            !isDiagnosticPage() ||
            (existingConfig != null && !maintenanceAuthorized)
        ) {
            return AndroidEvent.error(
                ErrorCode.BRIDGE_ACTION_FORBIDDEN,
                "设备配置只能在管理员验证后的本地页面修改"
            )
        }
        if (provisioningInProgress) {
            return AndroidEvent.error(
                ErrorCode.DEVICE_PROVISIONING_IN_PROGRESS,
                "设备预配正在进行，请勿重复提交"
            )
        }
        val request = runCatching {
            ProvisioningRequest.parse(
                payload,
                requireMaintenancePin = !maintenancePinStore.hasPin()
            )
        }.getOrElse { error ->
            Log.w(TAG, "Rejected device configuration", error)
            return AndroidEvent.error(
                ErrorCode.DEVICE_CONFIG_INVALID,
                error.message ?: "设备配置无效"
            )
        }
        val deviceToken = deviceTokenGenerator.generate()
        val candidate = runCatching {
            DeviceConfig.parse(
                JSONObject()
                    .put("seatId", request.seatId)
                    .put("deviceId", stableDeviceId)
                    .put("deviceToken", deviceToken)
                    .put("serverBaseUrl", request.endpoints.serverUrl)
                    .put("frontendBaseUrl", request.endpoints.frontendUrl)
                    .toString()
            )
        }.getOrElse { error ->
            return AndroidEvent.error(
                ErrorCode.DEVICE_CONFIG_INVALID,
                error.message ?: "设备配置无效"
            )
        }

        provisioningInProgress = true
        provisioningExecutor.execute {
            val result = tabletDeviceClient.provision(
                serverBaseUrl = candidate.serverUrl,
                deviceId = stableDeviceId,
                seatId = candidate.seatId,
                deviceToken = deviceToken,
                provisioningToken = request.provisioningToken,
                replaceExisting = request.replaceExisting
            )
            webView.post {
                provisioningInProgress = false
                handleProvisioningResult(result, candidate, request)
            }
        }
        return AndroidEvent.event(
            "device_provisioning_started",
            JSONObject()
                .put("deviceId", stableDeviceId)
                .put("seatId", candidate.seatId)
                .put("seatAlias", candidate.seatAlias)
        )
    }

    private fun handleProvisioningResult(
        result: TabletApiResult,
        candidate: DeviceConfig,
        request: ProvisioningRequest
    ) {
        when (result) {
            is TabletApiResult.Success -> {
                val binding = result.binding
                if (
                    binding.deviceId != candidate.deviceId ||
                    binding.seatId != candidate.seatId ||
                    binding.seatAlias != candidate.seatAlias ||
                    !binding.enabled
                ) {
                    emitToReact(
                        AndroidEvent.error(
                            ErrorCode.DEVICE_BINDING_INVALID,
                            "中央主机返回的设备绑定与本机配置不一致"
                        )
                    )
                    return
                }
                identityMode = binding.identityMode
                runCatching {
                    if (!maintenancePinStore.hasPin()) {
                        maintenancePinStore.set(
                            requireNotNull(request.maintenancePin)
                        )
                    }
                    deviceConfigStore.save(
                        candidate.toJson(includeSecret = true).toString()
                    )
                }.onSuccess { config ->
                    maintenanceAuthorized = false
                    hostConsoleAccessStore.clear()
                    emitToReact(
                        AndroidEvent.event(
                            "device_config_saved",
                            config.toJson()
                        )
                    )
                    webView.postDelayed(
                        ::loadConfiguredPage,
                        CONFIG_RELOAD_DELAY_MS
                    )
                }.onFailure { error ->
                    Log.e(TAG, "Unable to persist provisioned device", error)
                    emitToReact(
                        AndroidEvent.error(
                            ErrorCode.DEVICE_CONFIG_INVALID,
                            "绑定已完成，但本地配置保存失败，请重试"
                        )
                    )
                }
            }
            is TabletApiResult.Conflict -> emitToReact(
                AndroidEvent.error(result.code, result.message)
            )
            is TabletApiResult.Rejected -> emitToReact(
                AndroidEvent.error(result.code, result.message)
            )
            is TabletApiResult.ServerError -> emitToReact(
                AndroidEvent.error(
                    ErrorCode.DEVICE_PROVISIONING_FAILED,
                    result.message
                )
            )
            TabletApiResult.Offline -> emitToReact(
                AndroidEvent.error(
                    ErrorCode.DEVICE_PROVISIONING_FAILED,
                    "无法连接中央主机，请检查地址和网络"
                )
            )
        }
    }
    private val microphonePermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        val request = pendingMicrophoneRequest
        pendingMicrophoneRequest = null
        val nativeStartRequested = pendingNativeMicrophoneStart
        pendingNativeMicrophoneStart = false
        if (request != null) {
            if (granted && mayGrantMicrophone(request, true)) {
                request.grant(arrayOf(PermissionRequest.RESOURCE_AUDIO_CAPTURE))
                if (recognitionManager != null) {
                    lastNativeError = null
                }
                Log.i(TAG, "WebView microphone permission granted")
            } else {
                request.deny()
                reportMicrophonePermissionDenied()
            }
            return@registerForActivityResult
        }
        if (nativeStartRequested) {
            if (
                granted && WebViewAccessPolicy.mayStartNativeMicrophone(
                    pageAccessState.currentUrl(),
                    deviceConfigStore.load()
                )
            ) {
                startNativeMicrophoneCapture()
            } else if (!granted) {
                reportMicrophonePermissionDenied()
            } else {
                reportNativeMicrophonePageForbidden()
            }
        }
    }

    private fun requestStartNativeMicrophoneCapture() {
        if (
            !WebViewAccessPolicy.mayStartNativeMicrophone(
                pageAccessState.currentUrl(),
                deviceConfigStore.load()
            )
        ) {
            reportNativeMicrophonePageForbidden()
            return
        }
        if (nativeMicrophoneCapture.isRunning) {
            emitToReact(AndroidEvent.microphoneStatus("STARTED"))
            return
        }
        if (
            ContextCompat.checkSelfPermission(
                this,
                Manifest.permission.RECORD_AUDIO
            ) == PackageManager.PERMISSION_GRANTED
        ) {
            startNativeMicrophoneCapture()
            return
        }
        pendingNativeMicrophoneStart = true
        microphonePermissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
    }

    private fun startNativeMicrophoneCapture() {
        if (
            !WebViewAccessPolicy.mayStartNativeMicrophone(
                pageAccessState.currentUrl(),
                deviceConfigStore.load()
            )
        ) {
            reportNativeMicrophonePageForbidden()
            return
        }
        if (
            ContextCompat.checkSelfPermission(
                this,
                Manifest.permission.RECORD_AUDIO
            ) != PackageManager.PERMISSION_GRANTED
        ) {
            reportMicrophonePermissionDenied()
            return
        }
        runCatching {
            nativeMicrophoneCapture.start()
        }.onSuccess {
            lastNativeError = null
            emitToReact(AndroidEvent.microphoneStatus("STARTED"))
            Log.i(TAG, "Native microphone capture started")
        }.onFailure { error ->
            lastNativeError = ErrorCode.MICROPHONE_CAPTURE_FAILED
            emitToReact(
                AndroidEvent.error(
                    ErrorCode.MICROPHONE_CAPTURE_FAILED,
                    error.message ?: "Android 麦克风采集启动失败"
                )
            )
        }
    }

    private fun stopNativeMicrophoneCapture() {
        pendingNativeMicrophoneStart = false
        if (!nativeMicrophoneCapture.isRunning) return
        nativeMicrophoneCapture.stop()
        emitToReact(AndroidEvent.microphoneStatus("STOPPED"))
        Log.i(TAG, "Native microphone capture stopped")
    }

    private fun reportNativeMicrophonePageForbidden() {
        emitToReact(
            AndroidEvent.error(
                ErrorCode.BRIDGE_ACTION_FORBIDDEN,
                "原生麦克风只能从已绑定的正式业务页面启动"
            )
        )
    }

    private fun reportMicrophonePermissionDenied() {
        Log.w(TAG, "Microphone permission denied")
        lastNativeError = ErrorCode.MICROPHONE_PERMISSION_DENIED
        emitToReact(
            AndroidEvent.error(
                ErrorCode.MICROPHONE_PERMISSION_DENIED,
                "未获得麦克风权限"
            )
        )
    }

    private fun retryConfiguredPageIfNeeded() {
        if (
            isWaitingPage() &&
            deviceConfigStore.load() != null
        ) {
            pageLoadState.retry()
            loadConfiguredPage()
        }
    }

    @SuppressLint("ClickableViewAccessibility")
    private fun configureMaintenanceGesture() {
        maintenanceButton.setOnTouchListener { _, event ->
            when (event.actionMasked) {
                MotionEvent.ACTION_DOWN -> scheduleMaintenanceUnlock()
                MotionEvent.ACTION_UP,
                MotionEvent.ACTION_CANCEL -> cancelMaintenanceUnlock()
            }
            true
        }
    }

    private fun scheduleMaintenanceUnlock() {
        cancelMaintenanceUnlock()
        val action = Runnable(::requestMaintenanceAccess)
        maintenanceUnlockAction = action
        mainHandler.postDelayed(action, MAINTENANCE_HOLD_MS)
    }

    private fun cancelMaintenanceUnlock() {
        maintenanceUnlockAction?.let(mainHandler::removeCallbacks)
        maintenanceUnlockAction = null
    }

    private fun requestMaintenanceAccess() {
        maintenanceUnlockAction = null
        if (!isTrustedOperationalPage() && !pageAccessState.isDiagnosticPage()) {
            return
        }
        if (!maintenancePinStore.hasPin()) {
            maintenanceAuthorized = true
            scheduleMaintenanceExpiry()
            openMaintenancePage()
            return
        }
        val input = EditText(this).apply {
            inputType = InputType.TYPE_CLASS_NUMBER or
                InputType.TYPE_NUMBER_VARIATION_PASSWORD
            hint = getString(R.string.device_maintenance_pin_hint)
        }
        AlertDialog.Builder(this)
            .setTitle(R.string.device_maintenance_pin_title)
            .setView(input)
            .setNegativeButton(R.string.cancel, null)
            .setPositiveButton(
                R.string.device_maintenance_confirm
            ) { _, _ ->
                if (maintenancePinStore.verify(input.text.toString())) {
                    maintenanceAuthorized = true
                    scheduleMaintenanceExpiry()
                    openMaintenancePage()
                } else {
                    Toast.makeText(
                        this,
                        R.string.device_maintenance_pin_invalid,
                        Toast.LENGTH_SHORT
                    ).show()
                }
            }
            .show()
    }

    private fun hostConsoleAccessStatus(): String {
        val config = deviceConfigStore.load()
        if (!isTrustedHostConsolePage() || config?.seatId != 1) {
            return AndroidEvent.error(
                ErrorCode.BRIDGE_ACTION_FORBIDDEN,
                "主持人控制台授权只能从已绑定的 Seat 1 页面查询"
            )
        }
        return hostConsoleAccessEvent(
            hostConsoleAccessStore.isAuthorized(),
            pending = false
        )
    }

    private fun requestHostConsoleAccess(): String {
        val config = deviceConfigStore.load()
        if (!isTrustedHostConsolePage() || config?.seatId != 1) {
            return AndroidEvent.error(
                ErrorCode.BRIDGE_ACTION_FORBIDDEN,
                "主持人控制台只能由已绑定的 Seat 1 平板解锁"
            )
        }
        if (hostConsoleAccessStore.isAuthorized()) {
            return hostConsoleAccessEvent(granted = true, pending = false)
        }
        if (!maintenancePinStore.hasPin()) {
            return AndroidEvent.error(
                ErrorCode.DEVICE_CONFIG_INVALID,
                "尚未设置维护 PIN，请长按维护入口完成配置"
            )
        }
        runOnUiThread(::showHostConsolePinDialog)
        return hostConsoleAccessEvent(granted = false, pending = true)
    }

    private fun showHostConsolePinDialog() {
        val input = EditText(this).apply {
            inputType = InputType.TYPE_CLASS_NUMBER or
                InputType.TYPE_NUMBER_VARIATION_PASSWORD
            hint = getString(R.string.device_maintenance_pin_hint)
        }
        AlertDialog.Builder(this)
            .setTitle("解锁主持人控制台")
            .setView(input)
            .setNegativeButton(R.string.cancel) { _, _ ->
                emitHostConsoleAccess(
                    granted = false,
                    message = "已取消主持人控制台解锁"
                )
            }
            .setPositiveButton(R.string.device_maintenance_confirm) { _, _ ->
                val granted = maintenancePinStore.verify(input.text.toString())
                if (granted) {
                    hostConsoleAccessStore.grant()
                } else {
                    Toast.makeText(
                        this,
                        R.string.device_maintenance_pin_invalid,
                        Toast.LENGTH_SHORT
                    ).show()
                }
                emitHostConsoleAccess(
                    granted = granted,
                    message = if (granted) {
                        "主持人控制台已解锁"
                    } else {
                        "维护 PIN 错误"
                    }
                )
            }
            .show()
    }

    private fun emitHostConsoleAccess(granted: Boolean, message: String) {
        emitToReact(
            AndroidEvent.event(
                "host_console_access",
                JSONObject()
                    .put("granted", granted)
                    .put("pending", false)
                    .put("message", message)
            )
        )
    }

    private fun hostConsoleAccessEvent(
        granted: Boolean,
        pending: Boolean
    ): String = AndroidEvent.event(
        "host_console_access",
        JSONObject()
            .put("granted", granted)
            .put("pending", pending)
    )

    private fun getDeviceCredential(): String {
        if (!isTrustedOperationalPage() && !(isHostFaceTemplatesPage() && maintenanceAuthorized)) {
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
        cancelPageHealthMonitoring()
        cancelOfflineRetry()
        identityMode = "formal"
        val config = deviceConfigStore.load()
        if (config == null) {
            pageLoadState.waitingConfiguration()
            loadWaitingPage("waiting-config", retry = false)
            return
        }

        cancelSeatPageLoadTimeout()
        pageLoadState.beginHealthCheck()
        loadWaitingPage("checking", retry = false)
        val generation = ++healthCheckGeneration
        runCatching {
            healthExecutor.execute {
                val healthResult = backendHealthChecker.check(config.serverUrl)
                val bindingResult = if (
                    healthResult == BackendHealthChecker.Result.HEALTHY
                ) {
                    pageLoadState.beginBindingValidation()
                    tabletDeviceClient.validate(config, BuildConfig.VERSION_NAME)
                } else {
                    null
                }
                webView.post {
                    if (generation != healthCheckGeneration || isFinishing) {
                        return@post
                    }
                    when (healthResult) {
                        BackendHealthChecker.Result.HEALTHY -> {
                            when (bindingResult) {
                                is TabletApiResult.Success -> {
                                    val binding = bindingResult.binding
                                    if (
                                        binding.deviceId == config.deviceId &&
                                        binding.seatId == config.seatId &&
                                        binding.seatAlias == config.seatAlias &&
                                        binding.enabled
                                    ) {
                                        identityMode = binding.identityMode
                                        beginSeatPageLoad(config.operationalPageUrl())
                                    } else {
                                        pageLoadState.waitingBinding()
                                        loadWaitingPage("waiting-binding")
                                    }
                                }
                                TabletApiResult.Offline -> {
                                    pageLoadState.waitingNetwork()
                                    loadWaitingPage("waiting-network")
                                }
                                is TabletApiResult.Conflict,
                                is TabletApiResult.Rejected -> {
                                    pageLoadState.waitingBinding()
                                    loadWaitingPage("waiting-binding")
                                }
                                is TabletApiResult.ServerError,
                                null -> {
                                    pageLoadState.waitingBackend()
                                    loadWaitingPage("waiting-backend")
                                }
                            }
                        }
                        BackendHealthChecker.Result.OFFLINE -> {
                            pageLoadState.waitingNetwork()
                            loadWaitingPage("waiting-network")
                        }
                        BackendHealthChecker.Result.SERVER_ERROR -> {
                            pageLoadState.waitingBackend()
                            loadWaitingPage("waiting-backend")
                        }
                    }
                }
            }
        }.onFailure {
            webView.post {
                pageLoadState.waitingNetwork()
                loadWaitingPage("waiting-network")
            }
        }
    }

    private fun beginSeatPageLoad(url: String) {
        cancelPageHealthMonitoring()
        maintenanceAuthorized = false
        maintenanceButton.visibility = View.GONE
        cancelOfflineRetry()
        pageAccessState.update(null)
        pageLoadState.beginPageLoad()
        Log.i(TAG, "Loading configured seat page: $url")
        webView.loadUrl(url)
        cancelSeatPageLoadTimeout()
        val timeoutAction = Runnable {
            if (pageLoadState.timedOut()) {
                Log.e(TAG, "WebView seat page load timed out")
                webView.stopLoading()
                loadWaitingPage("waiting-frontend")
            }
        }
        pageLoadTimeoutAction = timeoutAction
        webView.postDelayed(timeoutAction, PAGE_LOAD_TIMEOUT_MS)
    }

    private fun loadDiagnosticPage(mode: String) {
        cancelPageHealthMonitoring()
        cancelSeatPageLoadTimeout()
        cancelOfflineRetry()
        maintenanceButton.visibility = View.GONE
        val url = "$LOCAL_PAGE_URL?mode=${Uri.encode(mode)}"
        val previousUrl = pageAccessState.currentUrl()
        if (previousUrl != url) {
            pageAccessState.update(null)
            Log.i(TAG, "Loading local diagnostic page: $mode")
            webView.loadUrl(url)
        }
    }

    private fun loadWaitingPage(mode: String, retry: Boolean = true) {
        cancelPageHealthMonitoring()
        cancelSeatPageLoadTimeout()
        if (retry) scheduleOfflineRetry() else cancelOfflineRetry()
        maintenanceButton.visibility = View.VISIBLE
        val url = "$LOCAL_PAGE_URL?mode=${Uri.encode(mode)}"
        if (pageAccessState.currentUrl() != url) {
            pageAccessState.update(null)
            Log.i(TAG, "Loading local connection page: $mode")
            webView.loadUrl(url)
        }
    }

    private fun isWaitingPage(): Boolean {
        val current = pageAccessState.currentUrl() ?: return false
        if (!current.startsWith(LOCAL_ASSET_PREFIX)) return false
        val mode = Uri.parse(current).getQueryParameter("mode") ?: return false
        return mode == "checking" || mode.startsWith("waiting-")
    }

    private fun cancelSeatPageLoadTimeout() {
        pageLoadTimeoutAction?.let(webView::removeCallbacks)
        pageLoadTimeoutAction = null
    }

    private fun schedulePageHealthProbe(delayMs: Long) {
        pageHealthProbeAction?.let(mainHandler::removeCallbacks)
        pageHealthProbeAction = null
        if (!activityResumed || !isTrustedOperationalPage()) {
            pageHealthWatchdog.resetFailures()
            return
        }

        val generation = pageHealthProbeGeneration
        val action = Runnable {
            pageHealthProbeAction = null
            if (
                generation != pageHealthProbeGeneration ||
                !activityResumed ||
                !isTrustedOperationalPage()
            ) {
                pageHealthWatchdog.resetFailures()
                return@Runnable
            }
            runPageHealthProbe(generation)
        }
        pageHealthProbeAction = action
        mainHandler.postDelayed(action, delayMs)
    }

    private fun runPageHealthProbe(generation: Int) {
        pageHealthProbeStartedAtMs = SystemClock.elapsedRealtime()
        val timeoutAction = Runnable {
            completePageHealthProbe(
                generation = generation,
                isHealthy = false,
                failureReason = "JavaScript probe timed out"
            )
        }
        pageHealthProbeTimeoutAction = timeoutAction
        mainHandler.postDelayed(
            timeoutAction,
            PAGE_HEALTH_PROBE_TIMEOUT_MS
        )

        runCatching {
            webView.evaluateJavascript(PAGE_HEALTH_JAVASCRIPT) { result ->
                completePageHealthProbe(
                    generation = generation,
                    isHealthy = result == "true",
                    failureReason = "rendered root is empty"
                )
            }
        }.onFailure { error ->
            Log.w(TAG, "Unable to evaluate WebView health", error)
            completePageHealthProbe(
                generation = generation,
                isHealthy = false,
                failureReason = "JavaScript probe failed"
            )
        }
    }

    private fun completePageHealthProbe(
        generation: Int,
        isHealthy: Boolean,
        failureReason: String,
    ) {
        if (generation != pageHealthProbeGeneration) {
            return
        }
        pageHealthProbeGeneration += 1
        pageHealthProbeTimeoutAction?.let(mainHandler::removeCallbacks)
        pageHealthProbeTimeoutAction = null

        val completedAtMs = SystemClock.elapsedRealtime()
        val isTrustedPage = isTrustedOperationalPage()
        val recoveryAction = pageHealthWatchdog.observe(
            isTrustedPage = isTrustedPage,
            isHealthy = isHealthy,
            nowMs = completedAtMs
        )
        if (!activityResumed || !isTrustedPage) {
            return
        }

        if (!isHealthy && recoveryAction == PageHealthRecoveryAction.NONE) {
            Log.w(
                TAG,
                "WebView health check failed: $failureReason; " +
                    "consecutive=${pageHealthWatchdog.consecutiveFailures}"
            )
        }

        if (recoveryAction == PageHealthRecoveryAction.RELOAD) {
            val currentUrl = pageAccessState.currentUrl() ?: return
            Log.e(
                TAG,
                "Reloading trusted business page after repeated blank or stalled probes"
            )
            beginSeatPageLoad(currentUrl)
            return
        }

        val probeDurationMs = completedAtMs - pageHealthProbeStartedAtMs
        schedulePageHealthProbe(
            (PAGE_HEALTH_PROBE_INTERVAL_MS - probeDurationMs)
                .coerceAtLeast(0L)
        )
    }

    private fun cancelPageHealthMonitoring() {
        pageHealthProbeGeneration += 1
        pageHealthProbeAction?.let(mainHandler::removeCallbacks)
        pageHealthProbeAction = null
        pageHealthProbeTimeoutAction?.let(mainHandler::removeCallbacks)
        pageHealthProbeTimeoutAction = null
        pageHealthProbeStartedAtMs = 0L
        pageHealthWatchdog.resetFailures()
    }

    private fun scheduleOfflineRetry() {
        cancelOfflineRetry()
        if (deviceConfigStore.load() == null) return
        val action = Runnable {
            offlineRetryAction = null
            retryConfiguredPageIfNeeded()
        }
        offlineRetryAction = action
        mainHandler.postDelayed(action, OFFLINE_RETRY_INTERVAL_MS)
    }

    private fun cancelOfflineRetry() {
        offlineRetryAction?.let(mainHandler::removeCallbacks)
        offlineRetryAction = null
    }

    private fun openMaintenancePage() {
        healthCheckGeneration += 1
        cancelPageHealthMonitoring()
        cancelPendingMicrophoneRequest()
        stopNativeMicrophoneCapture()
        emitToReact(AndroidEvent.appLifecycle("PAUSED", "maintenance"))
        val config = deviceConfigStore.load()
        if (config == null) {
            loadDiagnosticPage("setup")
        } else if (config.seatId == 1 && isTrustedHostConsolePage()) {
            webView.loadUrl("${config.frontendUrl.trimEnd('/')}/seat/1/face-templates")
        } else {
            loadDiagnosticPage("maintenance")
        }
    }

    private fun scheduleMaintenanceExpiry() {
        maintenanceExpiryAction?.let(mainHandler::removeCallbacks)
        val action = Runnable {
            maintenanceExpiryAction = null
            if (isHostFaceTemplatesPage()) {
                clearMaintenanceAuthorization()
                loadConfiguredPage()
            } else {
                maintenanceAuthorized = false
            }
        }
        maintenanceExpiryAction = action
        mainHandler.postDelayed(action, HOST_MAINTENANCE_SESSION_MS)
    }

    private fun clearMaintenanceAuthorization() {
        maintenanceExpiryAction?.let(mainHandler::removeCallbacks)
        maintenanceExpiryAction = null
        maintenanceAuthorized = false
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
            .put("identityMode", identityMode)
            .put("maintenancePinConfigured", maintenancePinStore.hasPin())
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

    private inline fun performMaintenanceIdentityAction(
        errorCode: String,
        action: () -> String
    ): String {
        if (
            !WebViewAccessPolicy.mayOpenTemplatePhotoChooser(
                currentPageUrl = pageAccessState.currentUrl(),
                config = deviceConfigStore.load(),
                maintenanceAuthorized = maintenanceAuthorized
            )
        ) {
            return AndroidEvent.error(
                ErrorCode.BRIDGE_ACTION_FORBIDDEN,
                "本机人脸模板只能在管理员验证后的维护页面管理"
            )
        }
        scheduleMaintenanceExpiry()
        return performIdentityAction(errorCode, action)
    }

    private inline fun performHostFaceTemplateAction(
        errorCode: String,
        action: () -> String
    ): String {
        if (!isHostFaceTemplatesPage() || !maintenanceAuthorized) {
            return AndroidEvent.error(
                ErrorCode.BRIDGE_ACTION_FORBIDDEN,
                "中央人脸模板只能由验证后的主持人平板管理"
            )
        }
        scheduleMaintenanceExpiry()
        return performIdentityAction(errorCode, action)
    }

    private inline fun performParticipantTemplateSync(
        errorCode: String,
        action: () -> String
    ): String {
        val config = deviceConfigStore.load()
        if (!isTrustedSeatPage() || config?.seatId !in 2..9) {
            return AndroidEvent.error(
                ErrorCode.BRIDGE_ACTION_FORBIDDEN,
                "只有正式参会者席位页面可以同步会议模板"
            )
        }
        return performIdentityAction(errorCode, action)
    }

    private fun isDiagnosticPage(): Boolean =
        pageAccessState.isDiagnosticPage()

    private fun isTrustedSeatPage(): Boolean {
        return pageAccessState.isTrustedSeatPage(deviceConfigStore.load())
    }

    private fun isTrustedHostConsolePage(): Boolean =
        pageAccessState.isTrustedHostConsolePage(deviceConfigStore.load())

    private fun isTrustedOperationalPage(): Boolean =
        pageAccessState.isTrustedOperationalPage(deviceConfigStore.load())

    private fun isHostFaceTemplatesPage(): Boolean =
        WebViewAccessPolicy.isHostFaceTemplatesPage(
            pageAccessState.currentUrl(),
            deviceConfigStore.load()
        )

    private fun hostIdentityEvent(
        manager: FaceRecognitionManager
    ): String = AndroidEvent.event(
        "host_identity",
        JSONObject()
            .put(
                "defaultPersonId",
                manager.defaultHostPersonId() ?: JSONObject.NULL
            )
            .put(
                "registeredPersonIds",
                org.json.JSONArray(manager.registeredPeople())
            )
    )

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
        cancelPageHealthMonitoring()
        cancelMaintenanceUnlock()
        cancelOfflineRetry()
        cancelSeatPageLoadTimeout()
        cancelPendingMicrophoneRequest()
        pendingFileChooser?.onReceiveValue(null)
        pendingFileChooser = null
        stopNativeMicrophoneCapture()
        healthExecutor.shutdownNow()
        provisioningExecutor.shutdownNow()
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
        activityResumed = true
        hideSystemNavigationBar()
        if (::webView.isInitialized) {
            webView.onResume()
            emitToReact(AndroidEvent.appLifecycle("RESUMED"))
            schedulePageHealthProbe(PAGE_HEALTH_INITIAL_GRACE_MS)
        }
    }

    override fun onPause() {
        activityResumed = false
        cancelPageHealthMonitoring()
        cancelPendingMicrophoneRequest()
        stopNativeMicrophoneCapture()
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
            cancelPageHealthMonitoring()
            pageAccessState.update(url)
            if (
                !WebViewAccessPolicy.mayStartNativeMicrophone(
                    url,
                    deviceConfigStore.load()
                )
            ) {
                stopNativeMicrophoneCapture()
            }
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
                val mode = Uri.parse(url).getQueryParameter("mode")
                maintenanceButton.visibility = if (
                    mode == "checking" || mode?.startsWith("waiting-") == true
                ) View.VISIBLE else View.GONE
            } else if (
                WebViewAccessPolicy.isTrustedOperationalPage(
                    url,
                    deviceConfigStore.load()
                )
            ) {
                cancelSeatPageLoadTimeout()
                pageLoadState.ready()
                maintenanceButton.visibility = View.GONE
                schedulePageHealthProbe(PAGE_HEALTH_INITIAL_GRACE_MS)
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
                    pageLoadState.waitingNetwork()
                    view.post {
                        loadWaitingPage("waiting-network")
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
                pageLoadState.waitingFrontend()
                view.post {
                    loadWaitingPage("waiting-frontend")
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
        override fun onShowFileChooser(
            webView: WebView,
            filePathCallback: ValueCallback<Array<Uri>>,
            fileChooserParams: FileChooserParams
        ): Boolean {
            if (
                !WebViewAccessPolicy.mayOpenTemplatePhotoChooser(
                    currentPageUrl = pageAccessState.currentUrl(),
                    config = deviceConfigStore.load(),
                    maintenanceAuthorized = maintenanceAuthorized
                )
            ) {
                filePathCallback.onReceiveValue(null)
                return true
            }
            pendingFileChooser?.onReceiveValue(null)
            pendingFileChooser = filePathCallback
            return runCatching {
                fileChooserLauncher.launch(
                    arrayOf("image/jpeg", "image/png")
                )
                true
            }.getOrElse { error ->
                Log.e(TAG, "Unable to open photo picker", error)
                pendingFileChooser = null
                filePathCallback.onReceiveValue(null)
                true
            }
        }

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
        const val MAINTENANCE_HOLD_MS = 5_000L
        const val HOST_MAINTENANCE_SESSION_MS = 10 * 60 * 1_000L
        const val NETWORK_RETRY_DELAY_MS = 1_000L
        const val OFFLINE_RETRY_INTERVAL_MS = 5_000L
        const val PAGE_LOAD_TIMEOUT_MS = 15_000L
        const val PAGE_HEALTH_INITIAL_GRACE_MS = 20_000L
        const val PAGE_HEALTH_PROBE_INTERVAL_MS = 15_000L
        const val PAGE_HEALTH_PROBE_TIMEOUT_MS = 5_000L
        const val PAGE_HEALTH_JAVASCRIPT =
            "(function(){var root=document.getElementById('root');" +
                "if(document.readyState!=='complete'||!root||" +
                "root.childElementCount===0){return false;}" +
                "var child=root.firstElementChild;var rect=child.getBoundingClientRect();" +
                "return rect.width>0&&rect.height>0;})()"
    }

    private enum class CameraState {
        IDLE,
        STARTING,
        RUNNING,
        STOPPING
    }
}
