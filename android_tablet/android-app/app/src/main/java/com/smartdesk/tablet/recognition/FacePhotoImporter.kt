package com.smartdesk.tablet.recognition

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import androidx.exifinterface.media.ExifInterface
import com.google.android.gms.tasks.Tasks
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.face.FaceDetectorOptions
import com.smartdesk.tablet.face.FaceCropper
import com.smartdesk.tablet.face.FaceDetectorManager
import java.io.ByteArrayInputStream
import java.util.concurrent.TimeUnit

class FacePhotoImporter(
    private val engine: MobileFaceNetEngine,
    private val templateStore: FaceTemplateStore
) {
    fun import(
        personId: String,
        photos: List<FacePhotoInput>
    ): FacePhotoImportResult {
        val detector = FaceDetectorManager(
            minFaceSize = 0.1f,
            performanceMode =
                FaceDetectorOptions.PERFORMANCE_MODE_ACCURATE,
            trackingEnabled = false
        )
        val acceptedEmbeddings = mutableListOf<FloatArray>()
        val rejected = mutableListOf<FacePhotoRejection>()
        try {
            photos.forEach { photo ->
                runCatching {
                    processPhoto(photo, detector)
                }.onSuccess(acceptedEmbeddings::add)
                    .onFailure { error ->
                        rejected += FacePhotoRejection(
                            name = photo.name,
                            reason = error.message ?: "照片处理失败"
                        )
                    }
            }
        } finally {
            detector.close()
        }

        if (
            acceptedEmbeddings.size <
            FacePhotoImportRequest.MIN_PHOTO_COUNT
        ) {
            return FacePhotoImportResult(
                personId = personId,
                selectedCount = photos.size,
                acceptedCount = acceptedEmbeddings.size,
                usedCount = 0,
                saved = false,
                message = "合格照片不足5张，原有模板未修改",
                rejected = rejected,
                registeredPeople = templateStore.loadAll()
                    .map(PersonFaceTemplate::personId)
            )
        }

        val selected = FacePhotoTemplateSelector.selectMostConsistent(
            acceptedEmbeddings
        )
        val aggregate = EmbeddingAggregator.aggregate(selected)
        templateStore.upsert(
            PersonFaceTemplate(
                personId = personId,
                normalSampleCount = selected.size,
                fillLightSampleCount = selected.size,
                normalEmbedding = aggregate.embedding,
                fillLightEmbedding = aggregate.embedding
            )
        )
        return FacePhotoImportResult(
            personId = personId,
            selectedCount = photos.size,
            acceptedCount = acceptedEmbeddings.size,
            usedCount = selected.size,
            saved = true,
            message = "照片模板已加密保存；仅限原型验证",
            rejected = rejected,
            registeredPeople = templateStore.loadAll()
                .map(PersonFaceTemplate::personId)
        )
    }

    private fun processPhoto(
        photo: FacePhotoInput,
        detector: FaceDetectorManager
    ): FloatArray {
        val bitmap = decodeUprightBitmap(photo.bytes)
        try {
            val faces = Tasks.await(
                detector.process(InputImage.fromBitmap(bitmap, 0)),
                DETECTION_TIMEOUT_SECONDS,
                TimeUnit.SECONDS
            )
            require(faces.size == 1) {
                when {
                    faces.isEmpty() -> "未检测到人脸"
                    else -> "照片中必须恰好有一张人脸"
                }
            }
            val face = faces.single()
            require(detector.hasRequiredLandmarks(face)) {
                "缺少完整五官关键点"
            }
            val crop = FaceCropper.cropAndAlign(bitmap, face)
            try {
                return engine.embed(crop.bitmap).embedding
            } finally {
                crop.bitmap.recycle()
            }
        } finally {
            bitmap.recycle()
        }
    }

    private fun decodeUprightBitmap(bytes: ByteArray): Bitmap {
        val bounds = BitmapFactory.Options().apply {
            inJustDecodeBounds = true
        }
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
        require(bounds.outWidth > 0 && bounds.outHeight > 0) {
            "无法解码图片"
        }
        require(
            bounds.outWidth <= MAX_SOURCE_DIMENSION &&
                bounds.outHeight <= MAX_SOURCE_DIMENSION
        ) { "图片尺寸过大" }
        var sampleSize = 1
        while (
            bounds.outWidth / sampleSize > MAX_DECODE_DIMENSION ||
            bounds.outHeight / sampleSize > MAX_DECODE_DIMENSION
        ) {
            sampleSize *= 2
        }
        val decoded = requireNotNull(
            BitmapFactory.decodeByteArray(
                bytes,
                0,
                bytes.size,
                BitmapFactory.Options().apply {
                    inSampleSize = sampleSize
                    inPreferredConfig = Bitmap.Config.ARGB_8888
                }
            )
        ) { "无法解码图片" }
        val orientation = runCatching {
            ExifInterface(ByteArrayInputStream(bytes)).getAttributeInt(
                ExifInterface.TAG_ORIENTATION,
                ExifInterface.ORIENTATION_NORMAL
            )
        }.getOrDefault(ExifInterface.ORIENTATION_NORMAL)
        val upright = applyOrientation(decoded, orientation)
        val minimumSide = minOf(upright.width, upright.height)
        if (minimumSide >= MIN_PROCESSING_SIDE) {
            return upright
        }
        val scale = MIN_PROCESSING_SIDE.toFloat() / minimumSide
        val scaled = Bitmap.createScaledBitmap(
            upright,
            (upright.width * scale).toInt(),
            (upright.height * scale).toInt(),
            true
        )
        if (scaled !== upright) {
            upright.recycle()
        }
        return scaled
    }

    private fun applyOrientation(bitmap: Bitmap, orientation: Int): Bitmap {
        val matrix = Matrix()
        when (orientation) {
            ExifInterface.ORIENTATION_FLIP_HORIZONTAL ->
                matrix.setScale(-1f, 1f)
            ExifInterface.ORIENTATION_ROTATE_180 ->
                matrix.setRotate(180f)
            ExifInterface.ORIENTATION_FLIP_VERTICAL ->
                matrix.setScale(1f, -1f)
            ExifInterface.ORIENTATION_TRANSPOSE -> {
                matrix.setRotate(90f)
                matrix.postScale(-1f, 1f)
            }
            ExifInterface.ORIENTATION_ROTATE_90 ->
                matrix.setRotate(90f)
            ExifInterface.ORIENTATION_TRANSVERSE -> {
                matrix.setRotate(-90f)
                matrix.postScale(-1f, 1f)
            }
            ExifInterface.ORIENTATION_ROTATE_270 ->
                matrix.setRotate(-90f)
            else -> return bitmap
        }
        val oriented = Bitmap.createBitmap(
            bitmap,
            0,
            0,
            bitmap.width,
            bitmap.height,
            matrix,
            true
        )
        if (oriented !== bitmap) {
            bitmap.recycle()
        }
        return oriented
    }

    private companion object {
        const val DETECTION_TIMEOUT_SECONDS = 15L
        const val MAX_SOURCE_DIMENSION = 12_000
        const val MAX_DECODE_DIMENSION = 2_048
        const val MIN_PROCESSING_SIDE = 320
    }
}
