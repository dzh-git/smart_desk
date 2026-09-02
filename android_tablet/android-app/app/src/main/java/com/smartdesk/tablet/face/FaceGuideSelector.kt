package com.smartdesk.tablet.face

import com.google.mlkit.vision.face.Face

object FaceGuideSelector {
    fun select(
        faces: List<Face>,
        imageWidth: Int,
        imageHeight: Int,
        rotationDegrees: Int,
        relaxed: Boolean = false
    ): List<Face> {
        val uprightWidth = if (rotationDegrees % 180 == 0) {
            imageWidth
        } else {
            imageHeight
        }
        val uprightHeight = if (rotationDegrees % 180 == 0) {
            imageHeight
        } else {
            imageWidth
        }
        return faces.filter { face ->
            val bounds = face.boundingBox
            FaceGuideGeometry.accepts(
                faceCenterX = bounds.exactCenterX(),
                faceCenterY = bounds.exactCenterY(),
                faceWidth = bounds.width().toFloat(),
                faceHeight = bounds.height().toFloat(),
                imageWidth = uprightWidth,
                imageHeight = uprightHeight,
                relaxed = relaxed
            )
        }
    }
}
