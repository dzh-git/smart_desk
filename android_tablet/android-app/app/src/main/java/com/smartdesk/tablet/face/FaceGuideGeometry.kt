package com.smartdesk.tablet.face

import kotlin.math.min
import kotlin.math.sqrt

object FaceGuideGeometry {
    const val RADIUS_RATIO = 0.25f

    fun radius(imageWidth: Int, imageHeight: Int): Float =
        min(imageWidth, imageHeight) * RADIUS_RATIO

    fun accepts(
        faceCenterX: Float,
        faceCenterY: Float,
        faceWidth: Float,
        faceHeight: Float,
        imageWidth: Int,
        imageHeight: Int,
        relaxed: Boolean = false
    ): Boolean {
        val guideRadius = radius(imageWidth, imageHeight)
        val deltaX = faceCenterX - imageWidth / 2f
        val deltaY = faceCenterY - imageHeight / 2f
        val centerDistance = sqrt(deltaX * deltaX + deltaY * deltaY)
        val tolerance = if (relaxed) RELAXED_TOLERANCE else 1f
        return centerDistance <=
            guideRadius * MAX_CENTER_OFFSET_RATIO * tolerance &&
            faceWidth in (
                guideRadius * MIN_FACE_WIDTH_RATIO / tolerance
                )..(
                guideRadius * MAX_FACE_WIDTH_RATIO * tolerance
                ) &&
            faceHeight in (
                guideRadius * MIN_FACE_HEIGHT_RATIO / tolerance
                )..(
                guideRadius * MAX_FACE_HEIGHT_RATIO * tolerance
                )
    }

    private const val MAX_CENTER_OFFSET_RATIO = 0.42f
    private const val MIN_FACE_WIDTH_RATIO = 0.55f
    private const val MAX_FACE_WIDTH_RATIO = 1.90f
    private const val MIN_FACE_HEIGHT_RATIO = 0.70f
    private const val MAX_FACE_HEIGHT_RATIO = 2.25f
    private const val RELAXED_TOLERANCE = 1.18f
}
