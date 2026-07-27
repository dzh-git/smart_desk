package com.smartdesk.tablet.face

import android.graphics.Bitmap
import com.google.mlkit.vision.face.Face
import kotlin.math.abs

object FaceQualityEvaluator {
    fun requireAcceptablePose(face: Face) {
        if (
            abs(face.headEulerAngleX) > MAX_PITCH_DEGREES ||
            abs(face.headEulerAngleY) > MAX_YAW_DEGREES ||
            abs(face.headEulerAngleZ) > MAX_ROLL_DEGREES
        ) {
            throw FaceQualityException(
                "请正对摄像头并保持头部水平"
            )
        }
    }

    fun evaluateAlignedFace(bitmap: Bitmap): FaceQualityResult {
        val width = bitmap.width
        val height = bitmap.height
        val pixels = IntArray(width * height)
        bitmap.getPixels(pixels, 0, width, 0, 0, width, height)
        val luminance = IntArray(width * height)
        var brightnessSum = 0L
        var brightnessCount = 0
        for (y in QUALITY_MARGIN until height - QUALITY_MARGIN) {
            for (x in QUALITY_MARGIN until width - QUALITY_MARGIN) {
                val index = y * width + x
                val pixel = pixels[index]
                val value = (
                    77 * (pixel shr 16 and 0xff) +
                        150 * (pixel shr 8 and 0xff) +
                        29 * (pixel and 0xff)
                    ) shr 8
                luminance[index] = value
                brightnessSum += value
                brightnessCount += 1
            }
        }
        val brightness = brightnessSum.toFloat() / brightnessCount
        if (brightness < MIN_BRIGHTNESS) {
            return FaceQualityResult(
                false,
                brightness,
                0f,
                "光线过暗，请增加正面照明"
            )
        }
        if (brightness > MAX_BRIGHTNESS) {
            return FaceQualityResult(
                false,
                brightness,
                0f,
                "画面过曝，请避开强光"
            )
        }

        var laplacianSum = 0.0
        var laplacianSquareSum = 0.0
        var laplacianCount = 0
        for (y in QUALITY_MARGIN + 1 until height - QUALITY_MARGIN - 1) {
            for (x in QUALITY_MARGIN + 1 until width - QUALITY_MARGIN - 1) {
                val index = y * width + x
                val laplacian =
                    4 * luminance[index] -
                        luminance[index - 1] -
                        luminance[index + 1] -
                        luminance[index - width] -
                        luminance[index + width]
                laplacianSum += laplacian
                laplacianSquareSum += laplacian.toDouble() * laplacian
                laplacianCount += 1
            }
        }
        val laplacianMean = laplacianSum / laplacianCount
        val sharpness = (
            laplacianSquareSum / laplacianCount -
                laplacianMean * laplacianMean
            ).toFloat()
        if (sharpness < MIN_SHARPNESS) {
            return FaceQualityResult(
                false,
                brightness,
                sharpness,
                "画面模糊，请保持不动并靠近摄像头"
            )
        }
        return FaceQualityResult(
            true,
            brightness,
            sharpness,
            "质量合格"
        )
    }

    private const val QUALITY_MARGIN = 16
    private const val MAX_PITCH_DEGREES = 12f
    private const val MAX_YAW_DEGREES = 12f
    private const val MAX_ROLL_DEGREES = 15f
    private const val MIN_BRIGHTNESS = 55f
    private const val MAX_BRIGHTNESS = 210f
    private const val MIN_SHARPNESS = 40f
}

data class FaceQualityResult(
    val accepted: Boolean,
    val brightness: Float,
    val sharpness: Float,
    val message: String
)

class FaceQualityException(message: String) :
    IllegalArgumentException(message)
