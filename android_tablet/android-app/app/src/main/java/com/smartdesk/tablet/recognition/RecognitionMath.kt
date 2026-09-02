package com.smartdesk.tablet.recognition

import kotlin.math.sqrt

object RecognitionMath {
    fun normalize(values: FloatArray): FloatArray {
        require(values.all(Float::isFinite)) { "特征向量包含NaN或Inf" }
        val norm = sqrt(
            values.fold(0.0) { sum, value ->
                sum + value * value
            }
        ).toFloat()
        require(norm.isFinite() && norm > 0f) { "模型返回了零向量" }
        return FloatArray(values.size) { index -> values[index] / norm }
    }

    fun average(embeddings: List<FloatArray>): FloatArray {
        require(embeddings.isNotEmpty()) { "注册样本不能为空" }
        val size = embeddings.first().size
        require(embeddings.all { it.size == size }) { "特征维度不一致" }
        val averaged = FloatArray(size)
        embeddings.forEach { embedding ->
            embedding.forEachIndexed { index, value ->
                averaged[index] += value
            }
        }
        averaged.indices.forEach { index ->
            averaged[index] /= embeddings.size
        }
        return normalize(averaged)
    }

    fun cosine(left: FloatArray, right: FloatArray): Float {
        require(left.size == right.size) { "特征维度不一致" }
        var dot = 0f
        var leftNorm = 0f
        var rightNorm = 0f
        left.indices.forEach { index ->
            dot += left[index] * right[index]
            leftNorm += left[index] * left[index]
            rightNorm += right[index] * right[index]
        }
        require(leftNorm > 0f && rightNorm > 0f) { "特征向量无效" }
        return dot / sqrt(leftNorm * rightNorm)
    }
}
