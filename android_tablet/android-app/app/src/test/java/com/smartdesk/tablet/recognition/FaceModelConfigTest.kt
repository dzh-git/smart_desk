package com.smartdesk.tablet.recognition

import org.junit.Assert.assertEquals
import org.junit.Test

class FaceModelConfigTest {
    @Test
    fun rgbNormalizationMatchesPinnedModel() {
        val config = validConfig()

        assertEquals(-0.99609375f, config.normalizeChannel(0), 0.000001f)
        assertEquals(0.99609375f, config.normalizeChannel(255), 0.000001f)
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsClassificationOutputDimension() {
        validConfig().copy(embeddingDimension = 85_742)
    }

    private fun validConfig() = FaceModelConfig(
        modelVersion = "test",
        assetFile = "model.tflite",
        sourceFile = "model.h5",
        sourceSha256 = "b".repeat(64),
        modelSha256 = "a".repeat(64),
        inputSize = 112,
        colorOrder = "RGB",
        normalizationMean = 127.5f,
        normalizationStd = 128f,
        embeddingDimension = 256,
        l2Normalize = true,
        alignmentVersion = "five-point-insightface-v1",
        pipelineVersion = 3,
        licenseLevel = "NON_COMMERCIAL_RESEARCH_PROTOTYPE"
    )
}
