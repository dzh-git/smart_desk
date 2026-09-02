package com.smartdesk.tablet.recognition

import org.junit.Assert.assertEquals
import org.junit.Test

class FaceTemplateCollectionTest {
    @Test
    fun samePersonIsReplacedWithoutIncreasingCount() {
        val original = template("seat-01", 1f)
        val replacement = template("seat-01", 0.5f)

        val result = FaceTemplateCollection.upsert(
            listOf(original),
            replacement,
            maxCount = 9
        )

        assertEquals(1, result.size)
        assertEquals(0.5f, result.single().normalEmbedding[0], 0f)
    }

    @Test(expected = IllegalArgumentException::class)
    fun tenthPersonIsRejected() {
        val existing = (1..9).map {
            template("seat-$it", 1f)
        }
        FaceTemplateCollection.upsert(
            existing,
            template("seat-10", 1f),
            maxCount = 9
        )
    }

    private fun template(id: String, value: Float) =
        PersonFaceTemplate(
            personId = id,
            normalSampleCount = 5,
            fillLightSampleCount = 5,
            normalEmbedding = floatArrayOf(value, 0f),
            fillLightEmbedding = floatArrayOf(0f, value)
        )
}
