package com.smartdesk.tablet.camera

import android.util.Log
import androidx.activity.ComponentActivity
import androidx.camera.core.Camera
import androidx.camera.core.CameraSelector
import androidx.camera.core.FocusMeteringAction
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import com.smartdesk.tablet.face.FaceDetectorManager
import com.smartdesk.tablet.face.FaceCropResult
import com.smartdesk.tablet.model.ErrorCode
import com.smartdesk.tablet.model.FaceDetectionResult
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

class CameraController(
    private val activity: ComponentActivity,
    private val previewView: PreviewView,
    private val onStarted: () -> Unit,
    private val onFacesDetected: (FaceDetectionResult) -> Unit,
    private val shouldProduceFaceCrop: () -> Boolean,
    private val onFaceCrop: (FaceCropResult) -> Unit,
    private val onQualityRejected: (String) -> Unit,
    private val onCropError: (Throwable) -> Unit,
    private val onDetectionError: (Throwable) -> Unit,
    private val onError: (String, Throwable) -> Unit
) {
    private var cameraProvider: ProcessCameraProvider? = null
    private var camera: Camera? = null
    private var imageAnalysis: ImageAnalysis? = null
    private var faceFrameAnalyzer: FaceFrameAnalyzer? = null
    private var startRequested = false
    private var requestGeneration = 0
    private val analysisExecutor: ExecutorService =
        Executors.newSingleThreadExecutor { runnable ->
            Thread(runnable, "SmartDesk-ImageAnalysis")
        }

    fun start() {
        if (startRequested) {
            Log.i(TAG, "Camera start ignored because it is already requested")
            return
        }

        startRequested = true
        val generation = ++requestGeneration
        Log.i(TAG, "Requesting CameraX provider")

        val providerFuture = ProcessCameraProvider.getInstance(activity)
        providerFuture.addListener(
            {
                if (!startRequested || generation != requestGeneration) {
                    Log.i(TAG, "Ignoring stale CameraX provider result")
                    return@addListener
                }

                val analyzer = runCatching {
                    val detectorManager = FaceDetectorManager()
                    FaceFrameAnalyzer(
                        detectorManager = detectorManager,
                        onResult = onFacesDetected,
                        shouldProduceFaceCrop = shouldProduceFaceCrop,
                        onFaceCrop = onFaceCrop,
                        onQualityRejected = onQualityRejected,
                        onCropError = onCropError,
                        onError = onDetectionError
                    )
                }.getOrElse { error ->
                    startRequested = false
                    Log.e(TAG, "Face detector initialization failed", error)
                    onError(ErrorCode.FACE_DETECTOR_INIT_FAILED, error)
                    return@addListener
                }

                runCatching {
                    val provider = providerFuture.get()
                    if (!provider.hasCamera(CameraSelector.DEFAULT_FRONT_CAMERA)) {
                        throw FrontCameraUnavailableException()
                    }
                    val preview = Preview.Builder().build().also {
                        it.surfaceProvider = previewView.surfaceProvider
                    }
                    val analysis = ImageAnalysis.Builder()
                        .setBackpressureStrategy(
                            ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST
                        )
                        .build()
                        .also {
                            it.setAnalyzer(analysisExecutor, analyzer)
                        }

                    provider.unbindAll()
                    val camera = provider.bindToLifecycle(
                        activity,
                        CameraSelector.DEFAULT_FRONT_CAMERA,
                        preview,
                        analysis
                    )
                    cameraProvider = provider
                    this.camera = camera
                    imageAnalysis = analysis
                    faceFrameAnalyzer = analyzer
                    requestGuideMetering()
                    Log.i(
                        TAG,
                        "CameraX Preview + ImageAnalysis bound; " +
                            "lensFacing=${camera.cameraInfo.lensFacing}, " +
                            "backpressure=KEEP_ONLY_LATEST"
                    )
                }.onSuccess {
                    onStarted()
                }.onFailure { error ->
                    startRequested = false
                    imageAnalysis?.clearAnalyzer()
                    imageAnalysis = null
                    analyzer.close()
                    faceFrameAnalyzer = null
                    cameraProvider?.unbindAll()
                    cameraProvider = null
                    camera = null
                    Log.e(TAG, "CameraX bind failed", error)
                    val code = if (error is FrontCameraUnavailableException) {
                        ErrorCode.CAMERA_NOT_AVAILABLE
                    } else {
                        ErrorCode.CAMERA_BIND_FAILED
                    }
                    onError(code, error)
                }
            },
            ContextCompat.getMainExecutor(activity)
        )
    }

    fun stop() {
        requestGeneration += 1
        startRequested = false
        imageAnalysis?.clearAnalyzer()
        imageAnalysis = null
        faceFrameAnalyzer?.close()
        faceFrameAnalyzer = null
        cameraProvider?.unbindAll()
        cameraProvider = null
        camera = null
        Log.i(TAG, "CameraX resources released")
    }

    fun release() {
        stop()
        analysisExecutor.shutdown()
        Log.i(TAG, "ImageAnalysis executor shut down")
    }

    fun requestGuideMetering() {
        requestGuideMetering(attempt = 0)
    }

    private fun requestGuideMetering(attempt: Int) {
        if (!startRequested) {
            return
        }
        val activeCamera = camera ?: run {
            Log.w(TAG, "Guide metering skipped because camera is not bound")
            return
        }
        previewView.post {
            if (!startRequested) {
                return@post
            }
            if (previewView.width <= 0 || previewView.height <= 0) {
                if (attempt < MAX_METERING_LAYOUT_RETRIES) {
                    previewView.postDelayed(
                        { requestGuideMetering(attempt + 1) },
                        METERING_LAYOUT_RETRY_DELAY_MS
                    )
                } else {
                    Log.w(
                        TAG,
                        "Guide metering skipped because PreviewView did not become ready"
                    )
                }
                return@post
            }
            val centerPoint = previewView.meteringPointFactory.createPoint(
                previewView.width / 2f,
                previewView.height / 2f,
                GUIDE_METERING_SIZE
            )
            val meteringCandidates = listOf(
                "AF/AE/AWB" to (
                    FocusMeteringAction.FLAG_AF or
                        FocusMeteringAction.FLAG_AE or
                        FocusMeteringAction.FLAG_AWB
                    ),
                "AE/AWB" to (
                    FocusMeteringAction.FLAG_AE or
                        FocusMeteringAction.FLAG_AWB
                    ),
                "AE" to FocusMeteringAction.FLAG_AE
            ).map { (label, flags) ->
                label to FocusMeteringAction.Builder(
                    centerPoint,
                    flags
                ).disableAutoCancel().build()
            }
            val supportedCandidate = meteringCandidates.firstOrNull {
                activeCamera.cameraInfo.isFocusMeteringSupported(it.second)
            } ?: run {
                Log.w(TAG, "Device does not support guide-centered metering")
                return@post
            }
            val (meteringModes, action) = supportedCandidate
            val meteringFuture =
                activeCamera.cameraControl.startFocusAndMetering(action)
            meteringFuture.addListener(
                {
                    runCatching {
                        meteringFuture.get()
                    }.onSuccess {
                    Log.i(
                        TAG,
                        "Guide-centered $meteringModes metering active; " +
                            "size=$GUIDE_METERING_SIZE"
                    )
                    }.onFailure { error ->
                        Log.w(
                            TAG,
                            "Guide-centered metering failed",
                            error
                        )
                    }
                },
                ContextCompat.getMainExecutor(activity)
            )
        }
    }

    private companion object {
        const val TAG = "SmartDeskTablet"
        const val GUIDE_METERING_SIZE = 0.35f
        const val MAX_METERING_LAYOUT_RETRIES = 5
        const val METERING_LAYOUT_RETRY_DELAY_MS = 100L
    }

    private class FrontCameraUnavailableException :
        IllegalStateException("设备没有可用的前置摄像头")
}
