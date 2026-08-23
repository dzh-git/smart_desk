package com.smartdesk.tablet.recognition

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class FaceMatcherTest {
    private val personA = PersonFaceTemplate(
        personId = "A",
        normalSampleCount = 5,
        fillLightSampleCount = 5,
        normalEmbedding = floatArrayOf(1f, 0f),
        fillLightEmbedding = floatArrayOf(0f, 1f)
    )
    private val personB = PersonFaceTemplate(
        personId = "B",
        normalSampleCount = 5,
        fillLightSampleCount = 5,
        normalEmbedding = floatArrayOf(0f, 1f),
        fillLightEmbedding = floatArrayOf(1f, 0f)
    )

    @Test
    fun singleAssignedTemplateIsEnoughForVerification() {
        val result = FaceMatcher.evaluate(
            List(5) { floatArrayOf(1f, 0f) },
            listOf(personA),
            TemplateKind.NORMAL,
            ThresholdStatus.PROVISIONAL,
            0.8f
        )

        assertEquals("VERIFIED", result.status)
        assertEquals("A", result.top1PersonId)
        assertNull(result.top2PersonId)
        assertNull(result.margin)
    }

    @Test
    fun naturalAndFillLightUseOnlySameConditionTemplates() {
        val frames = List(5) { floatArrayOf(1f, 0f) }

        val natural = FaceMatcher.evaluate(
            frames,
            listOf(personA, personB),
            TemplateKind.NORMAL,
            ThresholdStatus.PROVISIONAL,
            0.8f
        )
        val fill = FaceMatcher.evaluate(
            frames,
            listOf(personA, personB),
            TemplateKind.FILL_LIGHT,
            ThresholdStatus.PROVISIONAL,
            0.8f
        )

        assertEquals("A", natural.top1PersonId)
        assertEquals("B", fill.top1PersonId)
        assertEquals("VERIFIED", natural.status)
        assertEquals("VERIFIED", fill.status)
    }

    @Test
    fun pendingCalibrationNeverReturnsVerified() {
        val result = FaceMatcher.evaluate(
            List(5) { floatArrayOf(1f, 0f) },
            listOf(personA, personB),
            TemplateKind.NORMAL,
            ThresholdStatus.CALIBRATION_PENDING,
            null
        )

        assertEquals("CALIBRATION_PENDING", result.status)
        assertEquals("NONE", result.verificationLevel)
    }

    @Test
    fun insufficientSingleFrameAgreementRequiresRetry() {
        val result = FaceMatcher.evaluate(
            listOf(
                floatArrayOf(1f, 0f),
                floatArrayOf(1f, 0f),
                floatArrayOf(1f, 0f),
                floatArrayOf(0f, 1f),
                floatArrayOf(0f, 1f)
            ),
            listOf(personA, personB),
            TemplateKind.NORMAL,
            ThresholdStatus.PROVISIONAL,
            0.7f
        )

        assertEquals(3, result.agreeingFrames)
        assertEquals("RETRY_REQUIRED", result.status)
        assertEquals("PROTOTYPE", result.verificationLevel)
    }
}
