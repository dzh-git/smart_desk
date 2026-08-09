package com.smartdesk.tablet.audio

import android.Manifest
import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import androidx.annotation.RequiresPermission
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.max

class NativeMicrophoneCapture(
    private val onFrame: (ByteArray) -> Unit,
    private val onError: (Throwable) -> Unit
) {
    private val running = AtomicBoolean(false)
    private var audioRecord: AudioRecord? = null
    private var captureThread: Thread? = null

    val isRunning: Boolean
        get() = running.get()

    @SuppressLint("MissingPermission")
    @RequiresPermission(Manifest.permission.RECORD_AUDIO)
    @Synchronized
    fun start() {
        if (running.get()) return

        val minimumBufferBytes = AudioRecord.getMinBufferSize(
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT
        )
        check(minimumBufferBytes > 0) {
            "Unable to determine a valid microphone buffer size"
        }
        val recorder = AudioRecord(
            MediaRecorder.AudioSource.VOICE_RECOGNITION,
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            max(minimumBufferBytes, FRAME_SAMPLES * Short.SIZE_BYTES * 2)
        )
        check(recorder.state == AudioRecord.STATE_INITIALIZED) {
            recorder.release()
            "Unable to initialize Android microphone capture"
        }

        recorder.startRecording()
        check(recorder.recordingState == AudioRecord.RECORDSTATE_RECORDING) {
            recorder.release()
            "Android microphone did not enter the recording state"
        }

        audioRecord = recorder
        running.set(true)
        captureThread = Thread(
            { captureLoop(recorder) },
            "smartdesk-native-microphone"
        ).apply {
            isDaemon = true
            start()
        }
    }

    @Synchronized
    fun stop() {
        running.set(false)
        val recorder = audioRecord
        audioRecord = null
        runCatching { recorder?.stop() }
        captureThread?.let { thread ->
            if (thread !== Thread.currentThread()) {
                runCatching { thread.join(STOP_JOIN_TIMEOUT_MS) }
            }
        }
        captureThread = null
        runCatching { recorder?.release() }
    }

    private fun captureLoop(recorder: AudioRecord) {
        val samples = ShortArray(FRAME_SAMPLES)
        var filled = 0
        try {
            while (running.get()) {
                val read = recorder.read(
                    samples,
                    filled,
                    samples.size - filled,
                    AudioRecord.READ_BLOCKING
                )
                if (read < 0) {
                    if (running.get()) {
                        error("Android microphone read failed: $read")
                    }
                    break
                }
                if (read == 0) continue
                filled += read
                if (filled == samples.size) {
                    onFrame(Pcm16FrameEncoder.encode(samples, filled))
                    filled = 0
                }
            }
        } catch (error: Throwable) {
            if (running.getAndSet(false)) {
                onError(error)
            }
        }
    }

    private companion object {
        const val SAMPLE_RATE = 16_000
        const val FRAME_SAMPLES = 1_600
        const val STOP_JOIN_TIMEOUT_MS = 500L
    }
}
