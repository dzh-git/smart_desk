package com.smartdesk.tablet.recognition

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class FacePhotoTemplateSelectorTest {
    @Test
    fun `selects five mutually consistent embeddings`() {
        val consistent = listOf(
            vector(1f, 0f),
            vector(0.99f, 0.01f),
            vector(0.98f, 0.02f),
            vector(0.97f, 0.03f),
            vector(0.96f, 0.04f)
        )
        val outlier = vector(0f, 1f)

        val selected = FacePhotoTemplateSelector.selectMostConsistent(
            consistent + outlier
        )

        assertEquals(5, selected.size)
        assertFalse(selected.any { it.contentEquals(outlier) })
    }

    @Test(expected = IllegalArgumentException::class)
    fun `requires at least five accepted photos`() {
        FacePhotoTemplateSelector.selectMostConsistent(
            List(4) { vector(1f, 0f) }
        )
    }

    private fun vector(x: Float, y: Float): FloatArray =
        FloatArray(256).also {
            it[0] = x
            it[1] = y
        }
}
