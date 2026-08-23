package com.smartdesk.tablet.recognition

import java.io.File
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class FaceTemplateThresholdContractTest {
    private val source = File(
        "src/main/java/com/smartdesk/tablet/recognition/FaceTemplateStore.kt"
    ).readText(Charsets.UTF_8)

    @Test
    fun `provisional threshold does not depend on registered template count`() {
        val applyThreshold = source
            .substringAfter("fun applyProvisionalThreshold")
            .substringBefore("private fun saveAll")

        assertTrue(applyThreshold.contains("require(value in 0f..1f)"))
        assertFalse(applyThreshold.contains("loadAll()"))
        assertFalse(applyThreshold.contains("至少注册"))
    }

    @Test
    fun `template mutations preserve threshold metadata`() {
        val templateMutations = source
            .substringAfter("fun upsert")
            .substringBefore("fun thresholdStatus")

        assertFalse(templateMutations.contains("remove(THRESHOLD_KEY)"))
        assertFalse(templateMutations.contains("remove(THRESHOLD_STATUS_KEY)"))
        assertFalse(templateMutations.contains("remove(THRESHOLD_MODEL_HASH_KEY)"))
        assertFalse(templateMutations.contains("remove(THRESHOLD_PIPELINE_VERSION_KEY)"))
    }

    @Test
    fun `model and pipeline changes still invalidate threshold`() {
        val thresholdStatus = source
            .substringAfter("fun thresholdStatus")
            .substringBefore("fun threshold()")

        assertTrue(thresholdStatus.contains("modelHash != modelConfig.modelSha256"))
        assertTrue(thresholdStatus.contains("pipelineVersion != modelConfig.pipelineVersion"))
        assertTrue(thresholdStatus.contains("ThresholdStatus.CALIBRATION_PENDING"))
    }
}
