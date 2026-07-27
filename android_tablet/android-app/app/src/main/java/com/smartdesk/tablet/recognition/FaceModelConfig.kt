package com.smartdesk.tablet.recognition

import android.content.Context
import org.json.JSONObject

data class FaceModelConfig(
    val modelVersion: String,
    val assetFile: String,
    val sourceFile: String,
    val sourceSha256: String,
    val modelSha256: String,
    val inputSize: Int,
    val colorOrder: String,
    val normalizationMean: Float,
    val normalizationStd: Float,
    val embeddingDimension: Int,
    val l2Normalize: Boolean,
    val alignmentVersion: String,
    val pipelineVersion: Int,
    val licenseLevel: String
) {
    init {
        require(inputSize == 112) { "特征模型输入必须为112x112" }
        require(colorOrder == "RGB") { "特征模型颜色顺序必须为RGB" }
        require(embeddingDimension == 256) {
            "必须部署256维embedding模型，禁止使用分类logits"
        }
        require(l2Normalize) { "embedding必须执行L2归一化" }
        require(modelSha256.matches(Regex("[0-9a-f]{64}"))) {
            "模型SHA-256配置无效"
        }
    }

    fun normalizeChannel(value: Int): Float =
        (value - normalizationMean) / normalizationStd

    companion object {
        private const val CONFIG_ASSET =
            "models/face_model_config.json"

        fun load(context: Context): FaceModelConfig {
            val raw = context.assets.open(CONFIG_ASSET)
                .bufferedReader(Charsets.UTF_8)
                .use { it.readText() }
            val json = JSONObject(raw)
            return FaceModelConfig(
                modelVersion = json.getString("modelVersion"),
                assetFile = json.getString("assetFile"),
                sourceFile = json.getString("sourceFile"),
                sourceSha256 = json.getString("sourceSha256"),
                modelSha256 = json.getString("modelSha256"),
                inputSize = json.getInt("inputSize"),
                colorOrder = json.getString("colorOrder"),
                normalizationMean =
                    json.getDouble("normalizationMean").toFloat(),
                normalizationStd =
                    json.getDouble("normalizationStd").toFloat(),
                embeddingDimension =
                    json.getInt("embeddingDimension"),
                l2Normalize = json.getBoolean("l2Normalize"),
                alignmentVersion =
                    json.getString("alignmentVersion"),
                pipelineVersion = json.getInt("pipelineVersion"),
                licenseLevel = json.getString("licenseLevel")
            )
        }
    }
}
