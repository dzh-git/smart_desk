package com.smartdesk.tablet.recognition

import org.junit.Assert.assertEquals
import org.junit.Test

class RecognitionMathTest {
    @Test
    fun cosineReturnsOneForSameDirection() {
        assertEquals(
            1f,
            RecognitionMath.cosine(
                floatArrayOf(1f, 2f, 3f),
                floatArrayOf(2f, 4f, 6f)
            ),
            0.0001f
        )
    }

    @Test
    fun averageReturnsNormalizedTemplate() {
        val result = RecognitionMath.average(
            listOf(
                floatArrayOf(1f, 0f),
                floatArrayOf(0f, 1f)
            )
        )
        assertEquals(0.7071f, result[0], 0.0001f)
        assertEquals(0.7071f, result[1], 0.0001f)
    }
}
