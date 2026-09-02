package com.smartdesk.tablet.face

import android.util.Log
import com.google.android.gms.tasks.Task
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.face.Face
import com.google.mlkit.vision.face.FaceDetection
import com.google.mlkit.vision.face.FaceDetector
import com.google.mlkit.vision.face.FaceDetectorOptions
import com.google.mlkit.vision.face.FaceLandmark
import java.io.Closeable

class FaceDetectorManager(
    minFaceSize: Float = DEFAULT_MIN_FACE_SIZE,
    performanceMode: Int = FaceDetectorOptions.PERFORMANCE_MODE_FAST,
    trackingEnabled: Boolean = true
) : Closeable {
    private val detector: FaceDetector

    init {
        val options = FaceDetectorOptions.Builder()
            .setPerformanceMode(performanceMode)
            .setLandmarkMode(FaceDetectorOptions.LANDMARK_MODE_ALL)
            .setMinFaceSize(minFaceSize)
            .also { builder ->
                if (trackingEnabled) {
                    builder.enableTracking()
                }
            }
            .build()
        detector = FaceDetection.getClient(options)
        Log.i(
            TAG,
            "Bundled ML Kit face detector initialized: " +
                "landmarks + tracking=$trackingEnabled + " +
                "minFaceSize=$minFaceSize"
        )
    }

    fun process(image: InputImage): Task<List<Face>> = detector.process(image)

    fun hasRequiredLandmarks(face: Face): Boolean =
        face.getLandmark(FaceLandmark.LEFT_EYE) != null &&
            face.getLandmark(FaceLandmark.RIGHT_EYE) != null &&
            face.getLandmark(FaceLandmark.NOSE_BASE) != null &&
            face.getLandmark(FaceLandmark.MOUTH_LEFT) != null &&
            face.getLandmark(FaceLandmark.MOUTH_RIGHT) != null

    override fun close() {
        detector.close()
        Log.i(TAG, "ML Kit face detector released")
    }

    private companion object {
        const val TAG = "SmartDeskTablet"
        const val DEFAULT_MIN_FACE_SIZE = 0.3F
    }
}
