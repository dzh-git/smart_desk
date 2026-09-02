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

class FillLightOverlayView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null
) : View(context, attrs) {
    private val whitePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.WHITE
        style = Paint.Style.FILL
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val outsidePath = Path().apply {
            fillType = Path.FillType.EVEN_ODD
            addRect(
                0f,
                0f,
                width.toFloat(),
                height.toFloat(),
                Path.Direction.CW
            )
            addCircle(
                width / 2f,
                height / 2f,
                displayRadius(),
                Path.Direction.CW
            )
        }
        canvas.drawPath(outsidePath, whitePaint)
    }

    private fun displayRadius(): Float {
        val portrait = height >= width
        val sourceWidth = if (portrait) 3f else 4f
        val sourceHeight = if (portrait) 4f else 3f
        val scale = max(width / sourceWidth, height / sourceHeight)
        return min(sourceWidth, sourceHeight) *
            FaceGuideGeometry.RADIUS_RATIO * scale
    }
}
