package com.smartdesk.tablet.audio

object Pcm16FrameEncoder {
    fun encode(samples: ShortArray, count: Int): ByteArray {
        require(count in 0..samples.size)
        return ByteArray(count * Short.SIZE_BYTES).also { bytes ->
            for (index in 0 until count) {
                val value = samples[index].toInt()
                bytes[index * 2] = (value and 0xff).toByte()
                bytes[index * 2 + 1] = ((value ushr 8) and 0xff).toByte()
            }
        }
    }
}
