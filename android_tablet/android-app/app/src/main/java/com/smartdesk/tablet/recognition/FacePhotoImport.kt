package com.smartdesk.tablet.recognition

import android.util.Base64
import org.json.JSONArray

data class FacePhotoInput(
    val name: String,
    val mimeType: String,
    val bytes: ByteArray
)

data class FacePhotoRejection(
    val name: String,
    val reason: String
)

data class FacePhotoImportResult(
    val personId: String,
    val selectedCount: Int,
    val acceptedCount: Int,
    val usedCount: Int,
    val saved: Boolean,
    val message: String,
    val rejected: List<FacePhotoRejection>,
    val registeredPeople: List<String>
)

object FacePhotoImportRequest {
    const val MIN_PHOTO_COUNT = 5
    const val MAX_PHOTO_COUNT = 20
    const val MAX_PHOTO_BYTES = 5 * 1024 * 1024
    const val MAX_TOTAL_BYTES = 50 * 1024 * 1024

    fun parse(photosJson: String): List<FacePhotoInput> {
        require(photosJson.length <= MAX_JSON_CHARS) {
            "照片总负载过大，请减少照片数量或文件大小"
        }
        val array = JSONArray(photosJson)
        require(array.length() in MIN_PHOTO_COUNT..MAX_PHOTO_COUNT) {
            "请选择${MIN_PHOTO_COUNT}–${MAX_PHOTO_COUNT}张照片"
        }
        var totalBytes = 0
        return List(array.length()) { index ->
            val item = array.getJSONObject(index)
            val name = item.optString("name").trim()
            val mimeType = item.optString("mimeType").lowercase()
            require(name.isNotEmpty() && name.length <= 160) {
                "第${index + 1}张照片文件名无效"
            }
            require(mimeType == "image/jpeg" || mimeType == "image/png") {
                "$name：只支持 JPG 或 PNG"
            }
            val encoded = item.getString("base64")
            val bytes = runCatching {
                Base64.decode(encoded, Base64.NO_WRAP)
            }.getOrElse {
                throw IllegalArgumentException("$name：照片数据损坏")
            }
            require(bytes.isNotEmpty() && bytes.size <= MAX_PHOTO_BYTES) {
                "$name：单张照片不得超过 5 MB"
            }
            totalBytes += bytes.size
            require(totalBytes <= MAX_TOTAL_BYTES) {
                "照片总大小不得超过 50 MB"
            }
            FacePhotoInput(name, mimeType, bytes)
        }
    }

    private const val MAX_JSON_CHARS = 70 * 1024 * 1024
}

object FacePhotoTemplateSelector {
    fun selectMostConsistent(
        embeddings: List<FloatArray>,
        count: Int = EmbeddingAggregator.REQUIRED_FRAMES
    ): List<FloatArray> {
        require(embeddings.size >= count) {
            "至少需要${count}张合格照片"
        }
        return embeddings.indices
            .map { index ->
                val consistency = embeddings.indices
                    .filter { it != index }
                    .map { other ->
                        RecognitionMath.cosine(
                            embeddings[index],
                            embeddings[other]
                        )
                    }
                    .average()
                index to consistency
            }
            .sortedByDescending { it.second }
            .take(count)
            .map { embeddings[it.first] }
    }
}
