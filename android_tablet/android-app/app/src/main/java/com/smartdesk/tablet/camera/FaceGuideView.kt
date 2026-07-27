package com.smartdesk.tablet.camera

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.util.AttributeSet
import android.view.View
import com.smartdesk.tablet.face.FaceGuideGeometry
import kotlin.math.max
import kotlin.math.min

class FaceGuideView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null
) : View(context, attrs) {
    private val density = resources.displayMetrics.density
    private val dimPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.argb(105, 0, 0, 0)
        style = Paint.Style.FILL
    }
    private val ringPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = COLOR_WAITING
        style = Paint.Style.STROKE
        strokeWidth = 4f * density
    }
    private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.WHITE
        textAlign = Paint.Align.CENTER
        textSize = 16f * density
        setShadowLayer(5f * density, 0f, 2f * density, Color.BLACK)
    }
    private var faceStatus = "NO_FACE"
    private var identityStatus: String? = null

    fun updateFaceStatus(status: String) {
        faceStatus = status
        if (status != "ONE_FACE") {
            identityStatus = null
        }
        invalidate()
    }

    fun updateIdentityStatus(status: String) {
        identityStatus = status
        invalidate()
    }

    fun reset() {
        faceStatus = "NO_FACE"
        identityStatus = null
        invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val centerX = width / 2f
        val centerY = height / 2f
        val radius = displayRadius()
        val outsidePath = Path().apply {
            fillType = Path.FillType.EVEN_ODD
            addRect(0f, 0f, width.toFloat(), height.toFloat(), Path.Direction.CW)
            addCircle(centerX, centerY, radius, Path.Direction.CW)
        }
        canvas.drawPath(outsidePath, dimPaint)

        val resolvedStatus = identityStatus ?: faceStatus
        ringPaint.color = when (resolvedStatus) {
            "VERIFIED" -> COLOR_SUCCESS
            "UNKNOWN", "RETRY_REQUIRED", "MULTIPLE_FACES" -> COLOR_ERROR
            "ONE_FACE", "VERIFYING", "ENROLLING" -> COLOR_ACTIVE
            else -> COLOR_WAITING
        }
        canvas.drawCircle(centerX, centerY, radius, ringPaint)

        val message = when (resolvedStatus) {
            "VERIFIED" -> "身份验证通过"
            "UNKNOWN" -> "身份不匹配"
            "RETRY_REQUIRED" -> "请重新验证"
            "CALIBRATION_PENDING" -> "正在记录原型标定分数"
            "MULTIPLE_FACES" -> "圆圈内只允许一人"
            "WAITING_FOR_FACE" -> "请将正脸置于圆圈中央"
            "ENROLLED" -> "人脸模板注册完成"
            "ONE_FACE" -> "请保持正对并稍候"
            "VERIFYING" -> "正在进行本地身份验证"
            "ENROLLING" -> "正在采集人脸模板"
            else -> "请将正脸置于圆圈中央"
        }
        canvas.drawText(
            message,
            centerX,
            min(height - 96f * density, centerY + radius + 34f * density),
            textPaint
        )
    }

    private fun displayRadius(): Float {
        val portrait = height >= width
        val sourceWidth = if (portrait) 3f else 4f
        val sourceHeight = if (portrait) 4f else 3f
        val scale = max(width / sourceWidth, height / sourceHeight)
        return min(sourceWidth, sourceHeight) *
            FaceGuideGeometry.RADIUS_RATIO * scale
    }

    private companion object {
        const val COLOR_WAITING = 0xFFFFFFFF.toInt()
        const val COLOR_ACTIVE = 0xFF4DA3FF.toInt()
        const val COLOR_SUCCESS = 0xFF43D17A.toInt()
        const val COLOR_ERROR = 0xFFFF5A5F.toInt()
    }
}
