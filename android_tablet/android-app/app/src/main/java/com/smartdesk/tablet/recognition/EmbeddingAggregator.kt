package com.smartdesk.tablet.recognition

data class AggregatedEmbedding(
    val embedding: FloatArray,
    val removedIndex: Int,
    val consistencies: List<Float>
)

object EmbeddingAggregator {
    const val REQUIRED_FRAMES = 5

    fun aggregate(embeddings: List<FloatArray>): AggregatedEmbedding {
        require(embeddings.size == REQUIRED_FRAMES) {
            "必须使用5帧embedding进行聚合"
        }
        val consistencies = embeddings.indices.map { index ->
            embeddings.indices
                .filter { it != index }
                .map { other ->
                    RecognitionMath.cosine(
                        embeddings[index],
                        embeddings[other]
                    )
                }
                .average()
                .toFloat()
        }
        val removedIndex = consistencies.indices.minBy {
            consistencies[it]
        }
        val retained = embeddings.filterIndexed { index, _ ->
            index != removedIndex
        }
        return AggregatedEmbedding(
            embedding = RecognitionMath.average(retained),
            removedIndex = removedIndex,
            consistencies = consistencies
        )
    }
}
