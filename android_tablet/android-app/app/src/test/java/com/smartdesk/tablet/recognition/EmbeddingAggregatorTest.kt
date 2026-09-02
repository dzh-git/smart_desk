package com.smartdesk.tablet.recognition

import org.junit.Assert.assertEquals
import org.junit.Test

class EmbeddingAggregatorTest {
    @Test
    fun removesLeastConsistentFrameAndAveragesFour() {
        val result = EmbeddingAggregator.aggregate(
            listOf(
                floatArrayOf(1f, 0f),
                floatArrayOf(1f, 0f),
                floatArrayOf(1f, 0f),
                floatArrayOf(1f, 0f),
                floatArrayOf(0f, 1f)
            )
        )

        assertEquals(4, result.removedIndex)
        assertEquals(1f, result.embedding[0], 0.0001f)
        assertEquals(0f, result.embedding[1], 0.0001f)
    }
}
