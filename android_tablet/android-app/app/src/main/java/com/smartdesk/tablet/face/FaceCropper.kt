package com.smartdesk.tablet.face

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Matrix
import android.graphics.Paint
import android.graphics.PointF
import android.os.SystemClock
import androidx.camera.core.ImageProxy
import com.google.mlkit.vision.face.Face
import com.google.mlkit.vision.face.FaceLandmark

object FaceCropper {
    const val OUTPUT_SIZE = 112

    fun cropAndAlign(
        imageProxy: ImageProxy,
        face: Face
    ): FaceCropResult {
        val startedAtMs = SystemClock.elapsedRealtime()
        val rawBitmap = imageProxy.toBitmap()
        val uprightBitmap = rotateBitmap(
            rawBitmap,
            imageProxy.imageInfo.rotationDegrees
        )
        if (uprightBitmap !== rawBitmap) {
            rawBitmap.recycle()
        }

        return try {
            cropAndAlign(uprightBitmap, face, startedAtMs)
        } finally {
            uprightBitmap.recycle()
        }
    }

    fun cropAndAlign(bitmap: Bitmap, face: Face): FaceCropResult =
        cropAndAlign(bitmap, face, SystemClock.elapsedRealtime())

    private fun cropAndAlign(
        bitmap: Bitmap,
        face: Face,
        startedAtMs: Long
    ): FaceCropResult {
        FaceQualityEvaluator.requireAcceptablePose(face)
        val sourcePoints = listOf(
            requireLandmark(face, FaceLandmark.LEFT_EYE, "左眼"),
            requireLandmark(face, FaceLandmark.RIGHT_EYE, "右眼"),
            requireLandmark(face, FaceLandmark.NOSE_BASE, "鼻尖"),
            requireLandmark(face, FaceLandmark.MOUTH_LEFT, "左嘴角"),
            requireLandmark(face, FaceLandmark.MOUTH_RIGHT, "右嘴角")
        )
        val transform = similarityTransform(sourcePoints, CANONICAL_POINTS)
        val output = Bitmap.createBitmap(
            OUTPUT_SIZE,
            OUTPUT_SIZE,
            Bitmap.Config.ARGB_8888
        )
        try {
            Canvas(output).apply {
                drawColor(Color.BLACK)
                drawBitmap(
                    bitmap,
                    transform,
                    Paint(Paint.ANTI_ALIAS_FLAG or Paint.FILTER_BITMAP_FLAG)
                )
            }
            val quality = FaceQualityEvaluator.evaluateAlignedFace(output)
            if (!quality.accepted) {
                throw FaceQualityException(quality.message)
            }
            return FaceCropResult(
                bitmap = output,
                processingTimeMs =
                    SystemClock.elapsedRealtime() - startedAtMs,
                brightness = quality.brightness,
                sharpness = quality.sharpness
            )
        } catch (error: Throwable) {
            output.recycle()
            throw error
        }
    }

    private fun requireLandmark(
        face: Face,
        landmarkType: Int,
        label: String
    ): PointF = requireNotNull(
        face.getLandmark(landmarkType)?.position
    ) { "缺少${label}关键点" }

    private fun similarityTransform(
        source: List<PointF>,
        target: List<PointF>
    ): Matrix {
        require(source.size == target.size && source.size >= 2) {
            "对齐关键点数量不一致"
        }
        val sourceCenterX = source.sumOf { it.x.toDouble() }.toFloat() /
            source.size
        val sourceCenterY = source.sumOf { it.y.toDouble() }.toFloat() /
            source.size
        val targetCenterX = target.sumOf { it.x.toDouble() }.toFloat() /
            target.size
        val targetCenterY = target.sumOf { it.y.toDouble() }.toFloat() /
            target.size
        var denominator = 0f
        var scaleCos = 0f
        var scaleSin = 0f
        source.indices.forEach { index ->
            val sourceX = source[index].x - sourceCenterX
            val sourceY = source[index].y - sourceCenterY
            val targetX = target[index].x - targetCenterX
            val targetY = target[index].y - targetCenterY
            denominator += sourceX * sourceX + sourceY * sourceY
            scaleCos += sourceX * targetX + sourceY * targetY
            scaleSin += sourceX * targetY - sourceY * targetX
        }
        require(denominator > 0f) { "人脸关键点重合，无法对齐" }
        val a = scaleCos / denominator
        val b = scaleSin / denominator
        val translateX =
            targetCenterX - a * sourceCenterX + b * sourceCenterY
        val translateY =
            targetCenterY - b * sourceCenterX - a * sourceCenterY
        return Matrix().apply {
            setValues(
                floatArrayOf(
                    a, -b, translateX,
                    b, a, translateY,
                    0f, 0f, 1f
                )
            )
        }
    }

    private fun rotateBitmap(source: Bitmap, rotationDegrees: Int): Bitmap {
        if (rotationDegrees == 0) {
            return source
        }
        val matrix = Matrix().apply {
            postRotate(rotationDegrees.toFloat())
        }
        return Bitmap.createBitmap(
            source,
            0,
            0,
            source.width,
            source.height,
            matrix,
            true
        )
    }

    private val CANONICAL_POINTS = listOf(
        PointF(38.2946f, 51.6963f),
        PointF(73.5318f, 51.5014f),
        PointF(56.0252f, 71.7366f),
        PointF(41.5493f, 92.3655f),
        PointF(70.7299f, 92.2041f)
    )
}

data class FaceCropResult(
    val bitmap: Bitmap,
    val processingTimeMs: Long,
    val brightness: Float,
    val sharpness: Float
)
