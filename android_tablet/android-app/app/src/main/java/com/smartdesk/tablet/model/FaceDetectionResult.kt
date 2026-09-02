package com.smartdesk.tablet.model

data class FaceDetectionResult(
    val faceCount: Int,
    val processingTimeMs: Long
) {
    val status: String
        get() = when (faceCount) {
            0 -> "NO_FACE"
            1 -> "ONE_FACE"
            else -> "MULTIPLE_FACES"
        }
}
