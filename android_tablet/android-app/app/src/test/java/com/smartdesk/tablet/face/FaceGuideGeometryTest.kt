package com.smartdesk.tablet.face

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class FaceGuideGeometryTest {
    @Test
    fun acceptsCenteredFaceWithExpectedSize() {
        assertTrue(
            FaceGuideGeometry.accepts(
                faceCenterX = 240f,
                faceCenterY = 320f,
                faceWidth = 150f,
                faceHeight = 190f,
                imageWidth = 480,
                imageHeight = 640
            )
        )
    }

    @Test
    fun rejectsBackgroundFaceOutsideGuide() {
        assertFalse(
            FaceGuideGeometry.accepts(
                faceCenterX = 390f,
                faceCenterY = 180f,
                faceWidth = 80f,
                faceHeight = 100f,
                imageWidth = 480,
                imageHeight = 640
            )
        )
    }

    @Test
    fun relaxedRuleKeepsSmallBoundaryJitterAfterEntry() {
        assertFalse(
            FaceGuideGeometry.accepts(
                faceCenterX = 295f,
                faceCenterY = 320f,
                faceWidth = 150f,
                faceHeight = 190f,
                imageWidth = 480,
                imageHeight = 640
            )
        )
        assertTrue(
            FaceGuideGeometry.accepts(
                faceCenterX = 295f,
                faceCenterY = 320f,
                faceWidth = 150f,
                faceHeight = 190f,
                imageWidth = 480,
                imageHeight = 640,
                relaxed = true
            )
        )
    }
}
