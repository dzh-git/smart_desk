package com.smartdesk.tablet.recognition

enum class TemplateKind {
    NORMAL,
    FILL_LIGHT
}

enum class ThresholdStatus {
    CALIBRATION_PENDING,
    PROVISIONAL,
    VALIDATED
}

data class FaceMatchResult(
    val status: String,
    val templateKind: TemplateKind,
    val top1PersonId: String,
    val top1Score: Float,
    val top2PersonId: String?,
    val top2Score: Float?,
    val margin: Float?,
    val agreeingFrames: Int,
    val removedFrameIndex: Int,
    val verificationLevel: String
)

data class FaceVerificationProgress(
    val similarity: Float,
    val agreeingFrames: Int
)

object FaceMatcher {
    const val MIN_AGREEING_FRAMES = 4

    fun progress(
        frames: List<FloatArray>,
        templates: List<PersonFaceTemplate>,
        templateKind: TemplateKind,
        threshold: Float?
    ): FaceVerificationProgress {
        require(frames.isNotEmpty()) { "至少需要1帧人脸特征才能计算实时相似度" }
        require(templates.isNotEmpty()) { "至少需要1个人脸模板才能计算实时相似度" }
        val scores = frames.map { frame ->
            rank(frame, templates, templateKind).first().score
        }
        return FaceVerificationProgress(
            similarity = scores.last(),
            agreeingFrames = if (threshold == null) {
                0
            } else {
                scores.count { it >= threshold }
            }
        )
    }

    fun evaluate(
        frames: List<FloatArray>,
        templates: List<PersonFaceTemplate>,
        templateKind: TemplateKind,
        thresholdStatus: ThresholdStatus,
        threshold: Float?
    ): FaceMatchResult {
        require(templates.isNotEmpty()) { "至少需要1个人脸模板才能执行验证" }
        val aggregated = EmbeddingAggregator.aggregate(frames)
        val aggregateRanking = rank(
            aggregated.embedding,
            templates,
            templateKind
        )
        val top1 = aggregateRanking[0]
        val top2 = aggregateRanking.getOrNull(1)
        val agreeingFrames = frames.count { frame ->
            val frameTop1 = rank(frame, templates, templateKind).first()
            frameTop1.personId == top1.personId &&
                (threshold == null || frameTop1.score >= threshold)
        }
        val margin = top2?.let { top1.score - it.score }
        val status = when (thresholdStatus) {
            ThresholdStatus.CALIBRATION_PENDING ->
                "CALIBRATION_PENDING"
            ThresholdStatus.PROVISIONAL,
            ThresholdStatus.VALIDATED -> {
                val requiredThreshold = requireNotNull(threshold) {
                    "已标定状态缺少阈值"
                }
                when {
                    top1.score >= requiredThreshold &&
                        agreeingFrames >= MIN_AGREEING_FRAMES ->
                        "VERIFIED"
                    top1.score < requiredThreshold -> "UNKNOWN"
                    else -> "RETRY_REQUIRED"
                }
            }
        }
        val verificationLevel = when (thresholdStatus) {
            ThresholdStatus.CALIBRATION_PENDING -> "NONE"
            ThresholdStatus.PROVISIONAL -> "PROTOTYPE"
            ThresholdStatus.VALIDATED -> "VALIDATED"
        }
        return FaceMatchResult(
            status = status,
            templateKind = templateKind,
            top1PersonId = top1.personId,
            top1Score = top1.score,
            top2PersonId = top2?.personId,
            top2Score = top2?.score,
            margin = margin,
            agreeingFrames = agreeingFrames,
            removedFrameIndex = aggregated.removedIndex,
            verificationLevel = verificationLevel
        )
    }

    fun rank(
        embedding: FloatArray,
        templates: List<PersonFaceTemplate>,
        templateKind: TemplateKind
    ): List<PersonScore> = templates.map { person ->
        val template = when (templateKind) {
            TemplateKind.NORMAL -> person.normalEmbedding
            TemplateKind.FILL_LIGHT -> person.fillLightEmbedding
        }
        PersonScore(
            personId = person.personId,
            score = RecognitionMath.cosine(embedding, template)
        )
    }.sortedByDescending(PersonScore::score)
}

data class PersonScore(
    val personId: String,
    val score: Float
)
