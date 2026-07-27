package com.smartdesk.tablet.camera

import android.os.SystemClock
import android.util.Log
import androidx.camera.core.ExperimentalGetImage
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.face.Face
import com.smartdesk.tablet.face.FaceCropResult
import com.smartdesk.tablet.face.FaceCropper
import com.smartdesk.tablet.face.FaceDetectorManager
import com.smartdesk.tablet.face.FaceGuideSelector
import com.smartdesk.tablet.face.FaceQualityException
import com.smartdesk.tablet.model.FaceDetectionResult
import java.io.Closeable
import java.util.concurrent.Executor
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong

class FaceFrameAnalyzer(
    private val detectorManager: FaceDetectorManager,
    private val onResult: (FaceDetectionResult) -> Unit,
    private val shouldProduceFaceCrop: () -> Boolean,
    private val onFaceCrop: (FaceCropResult) -> Unit,
    private val onQualityRejected: (String) -> Unit,
    private val onCropError: (Throwable) -> Unit,
    private val onError: (Throwable) -> Unit
) : ImageAnalysis.Analyzer, Closeable {
    private val active = AtomicBoolean(true)
    private val processing = AtomicBoolean(false)
    private val detectorClosed = AtomicBoolean(false)
    private val analyzedFrameCount = AtomicLong(0)
    private var lastSubmittedAtMs = 0L
    private var lastLoggedFaceCount: Int? = null
    private var candidateStatus: String? = null
    private var consecutiveStatusCount = 0
    private var lastFaceCropAtMs = 0L
    private var guideFaceLatched = false
    private var guideTrackingId: Int? = null
    private var lastGuideFaceAtMs = 0L

    @ExperimentalGetImage
    override fun analyze(imageProxy: ImageProxy) {
        if (!active.get()) {
            imageProxy.close()
            return
        }

        val now = SystemClock.elapsedRealtime()
        if (
            now - lastSubmittedAtMs < MIN_ANALYSIS_INTERVAL_MS ||
            !processing.compareAndSet(false, true)
        ) {
            imageProxy.close()
            return
        }

        val mediaImage = imageProxy.image
        if (mediaImage == null) {
            processing.set(false)
            imageProxy.close()
            return
        }

        lastSubmittedAtMs = now
        val startedAtMs = SystemClock.elapsedRealtime()
        val rotationDegrees = imageProxy.imageInfo.rotationDegrees
        val inputImage = InputImage.fromMediaImage(mediaImage, rotationDegrees)

        try {
            detectorManager.process(inputImage)
                .addOnSuccessListener(DIRECT_EXECUTOR) { faces ->
                    if (!active.get()) {
                        return@addOnSuccessListener
                    }

                    val strictGuideFaces = FaceGuideSelector.select(
                        faces = faces,
                        imageWidth = imageProxy.width,
                        imageHeight = imageProxy.height,
                        rotationDegrees = rotationDegrees
                    )
                    val guideFaces = selectWithHysteresis(
                        faces = faces,
                        strictGuideFaces = strictGuideFaces,
                        imageWidth = imageProxy.width,
                        imageHeight = imageProxy.height,
                        rotationDegrees = rotationDegrees,
                        nowMs = now
                    )
                    val holdingGuideGrace =
                        guideFaces.isEmpty() && guideFaceLatched
                    val effectiveGuideFaceCount = if (holdingGuideGrace) {
                        1
                    } else {
                        guideFaces.size
                    }
                    val acceptedFaces = guideFaces.filter(
                        detectorManager::hasRequiredLandmarks
                    )
                    val processingTimeMs =
                        SystemClock.elapsedRealtime() - startedAtMs
                    val result = FaceDetectionResult(
                        faceCount = effectiveGuideFaceCount,
                        processingTimeMs = processingTimeMs
                    )
                    val currentFrame = analyzedFrameCount.incrementAndGet()

                    if (
                        lastLoggedFaceCount != effectiveGuideFaceCount ||
                        currentFrame % LOG_INTERVAL_RESULTS == 0L
                    ) {
                        Log.i(
                            TAG,
                                "Face detection result=${result.status} " +
                                "count=${result.faceCount} " +
                                "globalCount=${faces.size} " +
                                "outsideIgnored=" +
                                "${faces.size - guideFaces.size} " +
                                "guideGrace=$holdingGuideGrace " +
                                "guideQualified=${acceptedFaces.size} " +
                                "duration=${result.processingTimeMs}ms " +
                                "size=${imageProxy.width}x${imageProxy.height} " +
                                "rotation=$rotationDegrees " +
                                "thread=${Thread.currentThread().name}"
                        )
                        lastLoggedFaceCount = effectiveGuideFaceCount
                    }

                    if (candidateStatus == result.status) {
                        consecutiveStatusCount += 1
                    } else {
                        candidateStatus = result.status
                        consecutiveStatusCount = 1
                    }
                    if (
                        result.status != "ONE_FACE" ||
                        consecutiveStatusCount >= MIN_CONSECUTIVE_RESULTS
                    ) {
                        onResult(result)
                    }
                    if (
                        guideFaces.size == 1 &&
                        acceptedFaces.size == 1 &&
                        shouldProduceFaceCrop() &&
                        now - lastFaceCropAtMs >= MIN_FACE_CROP_INTERVAL_MS
                    ) {
                        lastFaceCropAtMs = now
                        runCatching {
                            FaceCropper.cropAndAlign(
                                imageProxy,
                                acceptedFaces.single()
                            )
                        }.onSuccess { crop ->
                            Log.i(
                                TAG,
                                "Aligned face accepted; brightness=" +
                                    String.format("%.1f", crop.brightness) +
                                    " sharpness=" +
                                    String.format("%.1f", crop.sharpness)
                            )
                            try {
                                onFaceCrop(crop)
                            } finally {
                                crop.bitmap.recycle()
                            }
                        }.onFailure { error ->
                            if (error is FaceQualityException) {
                                Log.i(
                                    TAG,
                                    "Face quality rejected: ${error.message}"
                                )
                                onQualityRejected(
                                    error.message ?: "人脸质量不合格"
                                )
                            } else {
                                Log.e(
                                    TAG,
                                    "Face crop/alignment failed",
                                    error
                                )
                                onCropError(error)
                            }
                        }
                    } else if (
                        guideFaces.size == 1 &&
                        acceptedFaces.isEmpty() &&
                        shouldProduceFaceCrop() &&
                        now - lastFaceCropAtMs >= MIN_FACE_CROP_INTERVAL_MS
                    ) {
                        lastFaceCropAtMs = now
                        onQualityRejected(
                            "请正对摄像头，确保五官清晰可见"
                        )
                    }
                }
                .addOnFailureListener(DIRECT_EXECUTOR) { error ->
                    if (active.get()) {
                        Log.e(TAG, "Face detection failed", error)
                        onError(error)
                    }
                }
                .addOnCompleteListener(DIRECT_EXECUTOR) {
                    processing.set(false)
                    imageProxy.close()
                    if (!active.get()) {
                        closeDetectorOnce()
                    }
                }
        } catch (error: Throwable) {
            processing.set(false)
            imageProxy.close()
            if (!active.get()) {
                closeDetectorOnce()
            }
            Log.e(TAG, "Unable to submit frame for face detection", error)
            if (active.get()) {
                onError(error)
            }
        }
    }

    override fun close() {
        active.set(false)
        if (!processing.get()) {
            closeDetectorOnce()
        }
    }

    private fun selectWithHysteresis(
        faces: List<Face>,
        strictGuideFaces: List<Face>,
        imageWidth: Int,
        imageHeight: Int,
        rotationDegrees: Int,
        nowMs: Long
    ): List<Face> {
        if (strictGuideFaces.size > 1) {
            clearGuideLatch()
            return strictGuideFaces
        }
        if (strictGuideFaces.size == 1) {
            val face = strictGuideFaces.single()
            guideFaceLatched = true
            guideTrackingId = face.trackingId
            lastGuideFaceAtMs = nowMs
            return strictGuideFaces
        }
        if (!guideFaceLatched) {
            return emptyList()
        }

        val relaxedFaces = FaceGuideSelector.select(
            faces = faces,
            imageWidth = imageWidth,
            imageHeight = imageHeight,
            rotationDegrees = rotationDegrees,
            relaxed = true
        )
        val continuedFace = guideTrackingId?.let { expectedId ->
            relaxedFaces.singleOrNull { it.trackingId == expectedId }
        } ?: relaxedFaces.singleOrNull()
        if (continuedFace != null) {
            guideTrackingId = continuedFace.trackingId ?: guideTrackingId
            lastGuideFaceAtMs = nowMs
            return listOf(continuedFace)
        }
        if (nowMs - lastGuideFaceAtMs >= GUIDE_EXIT_GRACE_MS) {
            clearGuideLatch()
        }
        return emptyList()
    }

    private fun clearGuideLatch() {
        guideFaceLatched = false
        guideTrackingId = null
        lastGuideFaceAtMs = 0L
    }

    private fun closeDetectorOnce() {
        if (detectorClosed.compareAndSet(false, true)) {
            detectorManager.close()
        }
    }

    private companion object {
        const val TAG = "SmartDeskTablet"
        const val MIN_ANALYSIS_INTERVAL_MS = 150L
        const val MIN_FACE_CROP_INTERVAL_MS = 180L
        const val MIN_CONSECUTIVE_RESULTS = 3
        const val GUIDE_EXIT_GRACE_MS = 750L
        const val LOG_INTERVAL_RESULTS = 30L
        val DIRECT_EXECUTOR = Executor { command -> command.run() }
    }
}
