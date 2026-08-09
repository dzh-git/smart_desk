package com.smartdesk.tablet.audio

import org.junit.Assert.assertArrayEquals
import org.junit.Test

class Pcm16FrameEncoderTest {
    @Test
    fun encodesSignedSamplesAsLittleEndianPcm16() {
        val encoded = Pcm16FrameEncoder.encode(
            shortArrayOf(0, 1, -1, Short.MIN_VALUE, Short.MAX_VALUE),
            5
        )

        assertArrayEquals(
            byteArrayOf(
                0x00, 0x00,
                0x01, 0x00,
                0xff.toByte(), 0xff.toByte(),
                0x00, 0x80.toByte(),
                0xff.toByte(), 0x7f
            ),
            encoded
        )
    }

    @Test
    fun encodesOnlyTheReportedSampleCount() {
        assertArrayEquals(
            byteArrayOf(0x34, 0x12),
            Pcm16FrameEncoder.encode(shortArrayOf(0x1234, 0x5678), 1)
        )
    }
}
