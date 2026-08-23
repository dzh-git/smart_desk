package com.smartdesk.tablet.recognition

import android.content.Context
import android.graphics.Bitmap
import android.os.SystemClock
import android.util.Log
import com.smartdesk.tablet.model.IdentityStatus

class FaceRecognitionManager(
    context: Context,
    private val onStatus: (IdentityStatus) -> Unit,
    private val onRequestMetering: () -> Unit,
    private val onFillLightChanged: (Boolean) -> Unit
) : AutoCloseable {
    private val engine = MobileFaceNetEngine(context)
    private val templateStore = FaceTemplateStore(context, engine.config)
    private val diagnostics = FaceDiagnostics(context)
    private val exposureGate = ExposureStabilityGate()
    private val stageEmbeddings = mutableListOf<FloatArray>()

    private var mode = Mode.IDLE
    private var personId: String? = null
    private var stage = TemplateKind.NORMAL
    private var phase = CapturePhase.WAITING_FOR_FACE
    private var normalEnrollmentEmbedding: FloatArray? = null
    private var sessionStarted = false
    private var exposureStarted = false
    private var captureReady = false
    private var fillLightEnabled = false
    private var latestStatus = initialStatus()

    @Synchronized
    fun startEnrollment(requestedPersonId: String): IdentityStatus {
        val normalizedId = requestedPersonId.trim()
        require(normalizedId.isNotEmpty()) { "人员编号不能为空" }
        require(normalizedId.length <= MAX_PERSON_ID_LENGTH) {
            "人员编号不能超过${MAX_PERSON_ID_LENGTH}个字符"
        }
        val templates = templateStore.loadAll()
        require(
            templates.any { it.personId == normalizedId } ||
                templates.size < FaceTemplateStore.MAX_PERSON_COUNT
        ) {
            "最多只能注册${FaceTemplateStore.MAX_PERSON_COUNT}名人员"
        }
        resetSession()
        personId = normalizedId
        mode = Mode.ENROLLING
        latestStatus = progressStatus(
            status = "ENROLLING",
            message = "请将正脸置于圆圈中央，准备采集自然光模板"
        )
        emit(latestStatus)
        return latestStatus
    }

    @Synchronized
    fun startVerification(requestedPersonId: String): IdentityStatus {
        val normalizedId = requestedPersonId.trim()
        require(normalizedId.isNotEmpty()) { "待验证人员编号不能为空" }
        val templates = templateStore.loadAll()
        require(templates.any { it.personId == normalizedId }) {
            "未找到当前席位人员的人脸模板：$normalizedId"
        }
        resetSession()
        personId = normalizedId
        mode = Mode.VERIFYING
        latestStatus = progressStatus(
            status = "VERIFYING",
            message = "请将正脸置于圆圈中央，准备自然光验证"
        )
        emit(latestStatus)
        return latestStatus
    }

    @Synchronized
    fun stop(): IdentityStatus {
        mode = Mode.IDLE
        resetSession()
        personId = null
        latestStatus = initialStatus()
        emit(latestStatus)
        return latestStatus
    }

    @Synchronized
    fun clearTemplates(): IdentityStatus {
        require(mode == Mode.IDLE) { "采集过程中不能清除模板" }
        templateStore.clearAll()
        personId = null
        latestStatus = initialStatus()
        emit(latestStatus)
        return latestStatus
    }

    @Synchronized
    fun removeTemplate(requestedPersonId: String): IdentityStatus {
        require(mode == Mode.IDLE) { "采集过程中不能删除模板" }
        val normalizedId = requestedPersonId.trim()
        require(normalizedId.isNotEmpty()) { "人员编号不能为空" }
        require(templateStore.remove(normalizedId)) {
            "未找到人员模板：$normalizedId"
        }
        latestStatus = initialStatus().copy(
            message = "已删除${normalizedId}的人脸模板"
        )
        emit(latestStatus)
        return latestStatus
    }

    @Synchronized
    fun applyProvisionalThreshold(value: Float): IdentityStatus {
        require(mode == Mode.IDLE) { "采集过程中不能修改阈值" }
        templateStore.applyProvisionalThreshold(value)
        latestStatus = initialStatus().copy(
            message = "已应用原型阈值，仅限内部验证"
        )
        emit(latestStatus)
        return latestStatus
    }

    @Synchronized
    fun setDiagnosticsEnabled(enabled: Boolean): IdentityStatus {
        diagnostics.setEnabled(enabled)
        latestStatus = latestStatus.copy(
            message = if (diagnostics.isEnabled()) {
                "Debug诊断已开启：${diagnostics.directoryPath()}"
            } else {
                "Debug诊断已关闭"
            }
        )
        emit(latestStatus)
        return latestStatus
    }

    @Synchronized
    fun clearDiagnostics(): IdentityStatus {
        diagnostics.clear()
        latestStatus = latestStatus.copy(message = "诊断数据已清除")
        emit(latestStatus)
        return latestStatus
    }

    @Synchronized
    fun registeredPeople(): List<String> =
        templateStore.loadAll().map(PersonFaceTemplate::personId)

    @Synchronized
    fun importFacePhotos(
        requestedPersonId: String,
        photos: List<FacePhotoInput>
    ): FacePhotoImportResult {
        require(mode == Mode.IDLE) {
            "采集或验证过程中不能导入照片"
        }
        val normalizedId = requestedPersonId.trim()
        require(normalizedId.isNotEmpty()) { "人员编号不能为空" }
        require(normalizedId.length <= MAX_PERSON_ID_LENGTH) {
            "人员编号不能超过${MAX_PERSON_ID_LENGTH}个字符"
        }
        val templates = templateStore.loadAll()
        require(
            templates.any { it.personId == normalizedId } ||
                templates.size < FaceTemplateStore.MAX_PERSON_COUNT
        ) {
            "最多只能注册${FaceTemplateStore.MAX_PERSON_COUNT}名人员"
        }
        val result = FacePhotoImporter(engine, templateStore).import(
            normalizedId,
            photos
        )
        latestStatus = initialStatus().copy(message = result.message)
        emit(latestStatus)
        return result
    }

    @Synchronized
    fun generateCentralTemplate(
        requestedPersonId: String,
        photos: List<FacePhotoInput>
    ): FacePhotoImporter.Generated {
        require(mode == Mode.IDLE) {
            "采集或验证过程中不能导入照片"
        }
        val normalizedId = requestedPersonId.trim()
        require(normalizedId.isNotEmpty()) { "人员编号不能为空" }
        require(normalizedId.length <= MAX_PERSON_ID_LENGTH) {
            "人员编号不能超过${MAX_PERSON_ID_LENGTH}个字符"
        }
        return FacePhotoImporter(engine, templateStore).generate(
            normalizedId,
            photos
        )
    }

    @Synchronized
    fun installManagedTemplates(
        meetingId: Int,
        revision: Int,
        templates: List<PersonFaceTemplate>,
        threshold: Float,
        thresholdStatus: ThresholdStatus,
        modelHash: String,
        pipelineVersion: Int
    ) {
        require(mode == Mode.IDLE) {
            "人脸识别运行时不能替换会议模板"
        }
        templateStore.replaceManagedMeeting(
            meetingId,
            revision,
            templates,
            threshold,
            thresholdStatus,
            modelHash,
            pipelineVersion
        )
        latestStatus = initialStatus().copy(message = "会议人脸模板同步完成")
        emit(latestStatus)
    }

    fun modelConfig(): FaceModelConfig = engine.config

    fun currentThreshold(): Float? = templateStore.threshold()

    fun currentThresholdStatus(): ThresholdStatus = templateStore.thresholdStatus()

    @Synchronized
    fun currentStatus(): IdentityStatus = latestStatus

    @Synchronized
    fun needsFaceCrop(): Boolean = mode != Mode.IDLE

    fun processFace(
        bitmap: Bitmap,
        cropTimeMs: Long,
        brightness: Float,
        sharpness: Float
    ) {
        var requestMetering = false
        var shouldEmbed = false
        val now = SystemClock.elapsedRealtime()
        val activeMode: Mode
        val activeStage: TemplateKind

        synchronized(this) {
            if (mode == Mode.IDLE) {
                return
            }
            activeMode = mode
            activeStage = stage
            sessionStarted = true
            if (!exposureStarted) {
                exposureGate.start(now)
                exposureStarted = true
                phase = CapturePhase.METERING
                requestMetering = true
                latestStatus = progressStatus(
                    message = stageMessage("正在执行中央测光")
                )
                emit(latestStatus)
            } else if (!captureReady) {
                when (exposureGate.observe(brightness, now)) {
                    ExposureGateResult.WAITING_FOR_METERING -> {
                        phase = CapturePhase.METERING
                        latestStatus = progressStatus(
                            message = stageMessage("等待测光稳定")
                        )
                        emit(latestStatus)
                    }
                    ExposureGateResult.WAITING_FOR_STABILITY -> {
                        phase = CapturePhase.STABILITY
                        latestStatus = progressStatus(
                            message = stageMessage("正在确认亮度稳定")
                        )
                        emit(latestStatus)
                    }
                    ExposureGateResult.READY -> {
                        phase = CapturePhase.CAPTURING
                        captureReady = true
                        latestStatus = progressStatus(
                            message = stageMessage("亮度已稳定，开始采集")
                        )
                        emit(latestStatus)
                    }
                    ExposureGateResult.TIMED_OUT -> {
                        abortRetryLocked(
                            "曝光未能稳定，请保持设备和光线稳定后重试"
                        )
                    }
                }
            } else {
                shouldEmbed = true
            }
        }
        if (requestMetering) {
            onRequestMetering()
            return
        }
        if (!shouldEmbed) {
            return
        }

        val embeddingResult = engine.embed(bitmap)
        val totalTimeMs = cropTimeMs + embeddingResult.processingTimeMs
        synchronized(this) {
            if (
                mode != activeMode ||
                stage != activeStage ||
                !captureReady
            ) {
                return
            }
            stageEmbeddings += embeddingResult.embedding
            runCatching {
                diagnostics.recordFrame(
                    bitmap = bitmap,
                    mode = mode.name,
                    stage = stage,
                    personId = personId,
                    sampleIndex = stageEmbeddings.size,
                    brightness = brightness,
                    sharpness = sharpness,
                    embedding = embeddingResult.embedding
                )
            }.onFailure {
                Log.w(TAG, "Unable to save debug diagnostic frame", it)
            }
            if (stageEmbeddings.size < EmbeddingAggregator.REQUIRED_FRAMES) {
                latestStatus = progressStatus(
                    processingTimeMs = totalTimeMs,
                    message = stageMessage(
                        "已采集${stageEmbeddings.size}/" +
                            "${EmbeddingAggregator.REQUIRED_FRAMES}"
                    )
                )
                emit(latestStatus)
                return
            }
            when (mode) {
                Mode.ENROLLING -> completeEnrollmentStage(totalTimeMs)
                Mode.VERIFYING -> completeVerificationStage(totalTimeMs)
                Mode.IDLE -> Unit
            }
        }
    }

    @Synchronized
    fun reportProcessingError(message: String): IdentityStatus {
        if (mode != Mode.IDLE) {
            abortRetryLocked(message)
        } else {
            latestStatus = latestStatus.copy(
                status = "ERROR",
                message = message
            )
            emit(latestStatus)
        }
        return latestStatus
    }

    @Synchronized
    fun reportQualityHint(message: String): IdentityStatus {
        if (mode == Mode.IDLE) {
            return latestStatus
        }
        if (sessionStarted && message.contains("五官")) {
            abortRetryLocked("关键点不完整，请重新验证")
            return latestStatus
        }
        latestStatus = progressStatus(message = message)
        emit(latestStatus)
        return latestStatus
    }

    @Synchronized
    fun reportGuideInterruption(faceCount: Int): IdentityStatus {
        if (mode == Mode.IDLE || faceCount == 1) {
            return latestStatus
        }
        if (sessionStarted) {
            abortRetryLocked(
                if (faceCount > 1) {
                    "圆圈内出现多人，本次采集已终止"
                } else {
                    "人脸离开圆圈，本次采集已终止"
                }
            )
            return latestStatus
        }
        latestStatus = progressStatus(
            status = if (faceCount > 1) {
                "MULTIPLE_FACES"
            } else {
                "WAITING_FOR_FACE"
            },
            message = if (faceCount > 1) {
                "圆圈内只允许一人"
            } else {
                "请将正脸置于圆圈中央"
            }
        )
        emit(latestStatus)
        return latestStatus
    }

    override fun close() {
        synchronized(this) {
            disableFillLight()
            mode = Mode.IDLE
        }
        engine.close()
    }

    private fun completeEnrollmentStage(processingTimeMs: Long) {
        val aggregated = EmbeddingAggregator.aggregate(stageEmbeddings)
        if (stage == TemplateKind.NORMAL) {
            normalEnrollmentEmbedding = aggregated.embedding
            beginFillLightStage()
            latestStatus = progressStatus(
                processingTimeMs = processingTimeMs,
                message = "自然光模板已生成，准备屏幕补光模板"
            )
            emit(latestStatus)
            return
        }

        val template = PersonFaceTemplate(
            personId = requireNotNull(personId),
            normalSampleCount = EmbeddingAggregator.REQUIRED_FRAMES,
            fillLightSampleCount = EmbeddingAggregator.REQUIRED_FRAMES,
            normalEmbedding = requireNotNull(
                normalEnrollmentEmbedding
            ),
            fillLightEmbedding = aggregated.embedding
        )
        templateStore.upsert(template)
        val enrolledPersonId = template.personId
        mode = Mode.IDLE
        disableFillLight()
        latestStatus = statusSnapshot(
            status = "ENROLLED",
            personId = enrolledPersonId,
            sampleCount = TOTAL_ENROLLMENT_FRAMES,
            captureStage = "NONE",
            stageSampleCount = EmbeddingAggregator.REQUIRED_FRAMES,
            processingTimeMs = processingTimeMs,
            message = "双光照人脸模板注册完成，仅保存256维特征"
        )
        emit(latestStatus)
        clearCaptureBuffers()
    }

    private fun completeVerificationStage(processingTimeMs: Long) {
        val result = FaceMatcher.evaluate(
            frames = stageEmbeddings.toList(),
            templates = templateStore.loadAll().filter {
                it.personId == personId
            },
            templateKind = stage,
            thresholdStatus = templateStore.thresholdStatus(),
            threshold = templateStore.threshold()
        )
        runCatching { diagnostics.recordMatch(result) }.onFailure {
            Log.w(TAG, "Unable to save debug match metrics", it)
        }
        if (
            stage == TemplateKind.NORMAL &&
            result.status != "VERIFIED"
        ) {
            beginFillLightStage()
            latestStatus = matchStatus(
                result = result,
                status = "VERIFYING",
                processingTimeMs = processingTimeMs,
                message = if (
                    result.status == "CALIBRATION_PENDING"
                ) {
                    "自然光分数已记录，正在采集补光标定分数"
                } else {
                    "自然光未通过，正在进行补光重试"
                }
            )
            emit(latestStatus)
            return
        }

        mode = Mode.IDLE
        disableFillLight()
        latestStatus = matchStatus(
            result = result,
            status = result.status,
            processingTimeMs = processingTimeMs,
            message = when (result.status) {
                "VERIFIED" ->
                    "原型身份验证通过，仅限内部验证"
                "UNKNOWN" -> "未通过身份验证"
                "CALIBRATION_PENDING" ->
                    "标定数据已记录，应用原型阈值前不会通过"
                else -> "采集结果不稳定，请重新验证"
            }
        )
        emit(latestStatus)
        clearCaptureBuffers()
    }

    private fun beginFillLightStage() {
        stage = TemplateKind.FILL_LIGHT
        stageEmbeddings.clear()
        exposureGate.reset()
        exposureStarted = false
        captureReady = false
        phase = CapturePhase.WAITING_FOR_FACE
        if (!fillLightEnabled) {
            fillLightEnabled = true
            onFillLightChanged(true)
        }
    }

    private fun abortRetryLocked(message: String) {
        val activePersonId = personId
        mode = Mode.IDLE
        disableFillLight()
        latestStatus = statusSnapshot(
            status = "RETRY_REQUIRED",
            personId = activePersonId,
            sampleCount = totalSampleCount(),
            captureStage = "NONE",
            stageSampleCount = stageEmbeddings.size,
            message = message
        )
        clearCaptureBuffers()
        emit(latestStatus)
    }

    private fun resetSession() {
        disableFillLight()
        stage = TemplateKind.NORMAL
        phase = CapturePhase.WAITING_FOR_FACE
        normalEnrollmentEmbedding = null
        sessionStarted = false
        exposureStarted = false
        captureReady = false
        exposureGate.reset()
        stageEmbeddings.clear()
    }

    private fun clearCaptureBuffers() {
        normalEnrollmentEmbedding = null
        sessionStarted = false
        exposureStarted = false
        captureReady = false
        exposureGate.reset()
        stageEmbeddings.clear()
        stage = TemplateKind.NORMAL
        phase = CapturePhase.WAITING_FOR_FACE
    }

    private fun disableFillLight() {
        if (fillLightEnabled) {
            fillLightEnabled = false
            onFillLightChanged(false)
        }
    }

    private fun progressStatus(
        status: String = modeStatus(),
        processingTimeMs: Long? = null,
        message: String
    ): IdentityStatus = statusSnapshot(
        status = status,
        personId = personId,
        sampleCount = totalSampleCount(),
        captureStage = captureStage(),
        stageSampleCount = stageEmbeddings.size,
        processingTimeMs = processingTimeMs,
        message = message
    )

    private fun matchStatus(
        result: FaceMatchResult,
        status: String,
        processingTimeMs: Long,
        message: String
    ): IdentityStatus = statusSnapshot(
        status = status,
        personId = result.top1PersonId,
        sampleCount = EmbeddingAggregator.REQUIRED_FRAMES,
        captureStage = if (status == "VERIFYING") {
            captureStage()
        } else {
            "NONE"
        },
        stageSampleCount = if (status == "VERIFYING") {
            stageEmbeddings.size
        } else {
            EmbeddingAggregator.REQUIRED_FRAMES
        },
        similarity = result.top1Score,
        top1PersonId = result.top1PersonId,
        top1Score = result.top1Score,
        top2PersonId = result.top2PersonId,
        top2Score = result.top2Score,
        margin = result.margin,
        matchStreak = result.agreeingFrames,
        verificationLevel = result.verificationLevel,
        processingTimeMs = processingTimeMs,
        message = message
    )

    private fun statusSnapshot(
        status: String,
        personId: String? = null,
        sampleCount: Int = 0,
        captureStage: String = "NONE",
        stageSampleCount: Int = 0,
        similarity: Float? = null,
        top1PersonId: String? = null,
        top1Score: Float? = null,
        top2PersonId: String? = null,
        top2Score: Float? = null,
        margin: Float? = null,
        matchStreak: Int = 0,
        verificationLevel: String? = null,
        processingTimeMs: Long? = null,
        message: String
    ): IdentityStatus {
        val thresholdStatus = templateStore.thresholdStatus()
        return IdentityStatus(
            mode = mode.name,
            status = status,
            personId = personId,
            sampleCount = sampleCount,
            requiredSamples = if (mode == Mode.ENROLLING) {
                TOTAL_ENROLLMENT_FRAMES
            } else {
                EmbeddingAggregator.REQUIRED_FRAMES
            },
            captureStage = captureStage,
            stageSampleCount = stageSampleCount,
            stageRequiredSamples = EmbeddingAggregator.REQUIRED_FRAMES,
            registeredCount = templateStore.loadAll().size,
            similarity = similarity,
            threshold = templateStore.threshold(),
            top1PersonId = top1PersonId,
            top1Score = top1Score,
            top2PersonId = top2PersonId,
            top2Score = top2Score,
            margin = margin,
            thresholdStatus = thresholdStatus.name,
            verificationLevel = verificationLevel ?: when (
                thresholdStatus
            ) {
                ThresholdStatus.CALIBRATION_PENDING -> "NONE"
                ThresholdStatus.PROVISIONAL -> "PROTOTYPE"
                ThresholdStatus.VALIDATED -> "VALIDATED"
            },
            modelVersion = engine.config.modelVersion,
            matchStreak = matchStreak,
            processingTimeMs = processingTimeMs,
            message = message
        )
    }

    private fun initialStatus(): IdentityStatus {
        val templates = templateStore.loadAll()
        return statusSnapshot(
            status = if (templates.isEmpty()) {
                "NOT_ENROLLED"
            } else {
                "ENROLLED"
            },
            message = if (templates.isEmpty()) {
                "尚未注册人脸模板"
            } else {
                "已注册${templates.size}名人员"
            }
        )
    }

    private fun totalSampleCount(): Int =
        if (
            mode == Mode.ENROLLING &&
            normalEnrollmentEmbedding != null
        ) {
            EmbeddingAggregator.REQUIRED_FRAMES +
                stageEmbeddings.size
        } else {
            stageEmbeddings.size
        }

    private fun captureStage(): String {
        val prefix = when (stage) {
            TemplateKind.NORMAL -> "NORMAL"
            TemplateKind.FILL_LIGHT -> "FILL_LIGHT"
        }
        return "${prefix}_${phase.name}"
    }

    private fun stageMessage(action: String): String =
        when (stage) {
            TemplateKind.NORMAL -> "自然光：$action"
            TemplateKind.FILL_LIGHT -> "屏幕补光：$action"
        }

    private fun modeStatus(): String = when (mode) {
        Mode.ENROLLING -> "ENROLLING"
        Mode.VERIFYING -> "VERIFYING"
        Mode.IDLE -> latestStatus.status
    }

    private fun emit(result: IdentityStatus) {
        onStatus(result)
    }

    private enum class Mode {
        IDLE,
        ENROLLING,
        VERIFYING
    }

    private enum class CapturePhase {
        WAITING_FOR_FACE,
        METERING,
        STABILITY,
        CAPTURING
    }

    private companion object {
        const val TAG = "SmartDeskTablet"
        const val MAX_PERSON_ID_LENGTH = 64
        const val TOTAL_ENROLLMENT_FRAMES =
            EmbeddingAggregator.REQUIRED_FRAMES * 2
    }
}
