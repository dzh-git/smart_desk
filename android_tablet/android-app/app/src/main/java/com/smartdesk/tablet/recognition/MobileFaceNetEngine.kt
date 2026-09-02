package com.smartdesk.tablet.recognition

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Color
import android.os.SystemClock
import android.util.Log
import com.smartdesk.tablet.face.FaceCropper
import org.tensorflow.lite.DataType
import org.tensorflow.lite.Interpreter
import java.io.FileInputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.MappedByteBuffer
import java.nio.channels.FileChannel
import java.security.MessageDigest

class MobileFaceNetEngine(context: Context) : AutoCloseable {
    val config = FaceModelConfig.load(context)
    private val interpreter = Interpreter(
        loadAndVerifyModel(context, config),
        Interpreter.Options().apply {
            setNumThreads(NUM_THREADS)
        }
    )
    private val inputBuffer = ByteBuffer.allocateDirect(
        1 * FaceCropper.OUTPUT_SIZE * FaceCropper.OUTPUT_SIZE *
            RGB_CHANNELS * Float.SIZE_BYTES
    ).order(ByteOrder.nativeOrder())
    private val pixels = IntArray(
        FaceCropper.OUTPUT_SIZE * FaceCropper.OUTPUT_SIZE
    )
    val embeddingSize: Int

    init {
        val inputShape = interpreter.getInputTensor(0).shape()
        val outputShape = interpreter.getOutputTensor(0).shape()
        require(
            inputShape.contentEquals(
                intArrayOf(
                    1,
                    config.inputSize,
                    config.inputSize,
                    RGB_CHANNELS
                )
            )
        ) {
            "MobileFaceNet 输入不匹配：${inputShape.contentToString()}"
        }
        require(
            outputShape.contentEquals(
                intArrayOf(1, config.embeddingDimension)
            )
        ) {
            "特征模型必须输出[1,256] embedding，禁止使用分类logits：" +
                outputShape.contentToString()
        }
        require(
            interpreter.getInputTensor(0).dataType() == DataType.FLOAT32 &&
                interpreter.getOutputTensor(0).dataType() == DataType.FLOAT32
        ) {
            "特征模型输入和输出必须为float32"
        }
        embeddingSize = outputShape[1]
        Log.i(
            TAG,
            "SE-MobileFaceNet embedding model ready; " +
                "version=${config.modelVersion} " +
                "input=${inputShape.contentToString()}, " +
                "output=${outputShape.contentToString()}, threads=$NUM_THREADS"
        )
        val warmupBitmap = Bitmap.createBitmap(
            FaceCropper.OUTPUT_SIZE,
            FaceCropper.OUTPUT_SIZE,
            Bitmap.Config.ARGB_8888
        ).apply {
            eraseColor(Color.rgb(127, 127, 127))
        }
        try {
            val warmup = embed(warmupBitmap)
            Log.i(
                TAG,
                "MobileFaceNet warm-up inference completed in " +
                    "${warmup.processingTimeMs}ms"
            )
        } finally {
            warmupBitmap.recycle()
        }
    }

    @Synchronized
    fun embed(bitmap: Bitmap): EmbeddingResult {
        require(
            bitmap.width == FaceCropper.OUTPUT_SIZE &&
                bitmap.height == FaceCropper.OUTPUT_SIZE
        ) { "人脸图像必须为 112x112" }
        val startedAtMs = SystemClock.elapsedRealtime()
        bitmap.getPixels(
            pixels,
            0,
            bitmap.width,
            0,
            0,
            bitmap.width,
            bitmap.height
        )
        inputBuffer.rewind()
        pixels.forEach { pixel ->
            inputBuffer.putFloat(
                config.normalizeChannel(pixel shr 16 and 0xff)
            )
            inputBuffer.putFloat(
                config.normalizeChannel(pixel shr 8 and 0xff)
            )
            inputBuffer.putFloat(
                config.normalizeChannel(pixel and 0xff)
            )
        }
        val output = Array(1) { FloatArray(embeddingSize) }
        interpreter.run(inputBuffer, output)
        require(output[0].all(Float::isFinite)) {
            "特征模型输出包含NaN或Inf"
        }
        return EmbeddingResult(
            embedding = RecognitionMath.normalize(output[0]),
            processingTimeMs =
                SystemClock.elapsedRealtime() - startedAtMs
        )
    }

    override fun close() {
        interpreter.close()
        Log.i(TAG, "MobileFaceNet released")
    }

    private companion object {
        const val TAG = "SmartDeskTablet"
        const val NUM_THREADS = 4
        const val RGB_CHANNELS = 3

        fun loadAndVerifyModel(
            context: Context,
            config: FaceModelConfig
        ): MappedByteBuffer {
            val digest = MessageDigest.getInstance("SHA-256")
            context.assets.open(config.assetFile).use { stream ->
                val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
                while (true) {
                    val count = stream.read(buffer)
                    if (count < 0) {
                        break
                    }
                    digest.update(buffer, 0, count)
                }
            }
            val actualHash = digest.digest().joinToString("") {
                "%02x".format(it)
            }
            require(actualHash == config.modelSha256) {
                "特征模型SHA-256不匹配，拒绝启动"
            }
            val descriptor = context.assets.openFd(config.assetFile)
            FileInputStream(descriptor.fileDescriptor).use { stream ->
                return stream.channel.map(
                    FileChannel.MapMode.READ_ONLY,
                    descriptor.startOffset,
                    descriptor.declaredLength
                )
            }
        }
    }
}

data class EmbeddingResult(
    val embedding: FloatArray,
    val processingTimeMs: Long
)
