package com.smartdesk.tablet.recognition

import android.content.Context
import com.smartdesk.tablet.security.SecureStringStore
import org.json.JSONArray
import org.json.JSONObject

class FaceTemplateStore(
    context: Context,
    private val modelConfig: FaceModelConfig =
        FaceModelConfig.load(context)
) {
    private val preferences = context.getSharedPreferences(
        PREFERENCES_NAME,
        Context.MODE_PRIVATE
    )
    private val secureStore = SecureStringStore(
        context,
        PREFERENCES_NAME,
        KEY_ALIAS
    )

    @Synchronized
    fun loadAll(): List<PersonFaceTemplate> {
        val raw = secureStore.getString(TEMPLATES_KEY)
            ?: return emptyList()
        return runCatching {
            val payload = JSONObject(raw)
            if (
                payload.getString("modelHash") !=
                modelConfig.modelSha256 ||
                payload.getInt("pipelineVersion") !=
                modelConfig.pipelineVersion
            ) {
                return emptyList()
            }
            val persons = payload.getJSONArray("persons")
            List(persons.length()) { index ->
                val person = persons.getJSONObject(index)
                PersonFaceTemplate(
                    personId = person.getString("personId"),
                    normalSampleCount =
                        person.getInt("normalSampleCount"),
                    fillLightSampleCount =
                        person.getInt("fillLightSampleCount"),
                    normalEmbedding = person
                        .getJSONArray("normalEmbedding")
                        .toFloatArray(),
                    fillLightEmbedding = person
                        .getJSONArray("fillLightEmbedding")
                        .toFloatArray(),
                    createdAt = person.getLong("createdAt")
                ).also(::requireCompatible)
            }
        }.getOrElse { emptyList() }
    }

    @Synchronized
    fun upsert(template: PersonFaceTemplate) {
        requireCompatible(template)
        val updated = FaceTemplateCollection.upsert(
            loadAll(),
            template,
            MAX_PERSON_COUNT
        )
        saveAll(updated)
    }

    @Synchronized
    fun remove(personId: String): Boolean {
        val current = loadAll()
        val updated = current.filterNot { it.personId == personId }
        if (updated.size == current.size) {
            return false
        }
        saveAll(updated)
        return true
    }

    @Synchronized
    fun clearAll() {
        secureStore.remove(TEMPLATES_KEY)
        preferences.edit()
            .remove(LEGACY_TEMPLATE_KEY)
            .remove(THRESHOLD_KEY)
            .remove(THRESHOLD_STATUS_KEY)
            .remove(THRESHOLD_MODEL_HASH_KEY)
            .remove(THRESHOLD_PIPELINE_VERSION_KEY)
            .apply()
    }

    fun thresholdStatus(): ThresholdStatus {
        val modelHash = preferences.getString(
            THRESHOLD_MODEL_HASH_KEY,
            null
        )
        val pipelineVersion = preferences.getInt(
            THRESHOLD_PIPELINE_VERSION_KEY,
            -1
        )
        if (
            modelHash != modelConfig.modelSha256 ||
            pipelineVersion != modelConfig.pipelineVersion
        ) {
            return ThresholdStatus.CALIBRATION_PENDING
        }
        return runCatching {
            ThresholdStatus.valueOf(
                preferences.getString(
                    THRESHOLD_STATUS_KEY,
                    ThresholdStatus.CALIBRATION_PENDING.name
                )!!
            )
        }.getOrDefault(ThresholdStatus.CALIBRATION_PENDING)
    }

    fun threshold(): Float? =
        if (thresholdStatus() == ThresholdStatus.CALIBRATION_PENDING) {
            null
        } else {
            preferences.getFloat(THRESHOLD_KEY, Float.NaN)
                .takeIf(Float::isFinite)
        }

    fun applyProvisionalThreshold(value: Float) {
        require(value in 0f..1f) { "原型阈值必须在0到1之间" }
        require(loadAll().size >= 2) {
            "至少注册2名人员后才能应用原型阈值"
        }
        preferences.edit()
            .putFloat(THRESHOLD_KEY, value)
            .putString(
                THRESHOLD_STATUS_KEY,
                ThresholdStatus.PROVISIONAL.name
            )
            .putString(
                THRESHOLD_MODEL_HASH_KEY,
                modelConfig.modelSha256
            )
            .putInt(
                THRESHOLD_PIPELINE_VERSION_KEY,
                modelConfig.pipelineVersion
            )
            .apply()
    }

    private fun saveAll(templates: List<PersonFaceTemplate>) {
        val persons = JSONArray()
        templates.forEach { template ->
            persons.put(
                JSONObject()
                    .put("personId", template.personId)
                    .put(
                        "normalSampleCount",
                        template.normalSampleCount
                    )
                    .put(
                        "fillLightSampleCount",
                        template.fillLightSampleCount
                    )
                    .put(
                        "normalEmbedding",
                        template.normalEmbedding.toJsonArray()
                    )
                    .put(
                        "fillLightEmbedding",
                        template.fillLightEmbedding.toJsonArray()
                    )
                    .put("createdAt", template.createdAt)
            )
        }
        val payload = JSONObject()
            .put("modelVersion", modelConfig.modelVersion)
            .put("modelHash", modelConfig.modelSha256)
            .put("pipelineVersion", modelConfig.pipelineVersion)
            .put("persons", persons)
        secureStore.putString(TEMPLATES_KEY, payload.toString())
        preferences.edit()
            .remove(LEGACY_TEMPLATE_KEY)
            .remove(THRESHOLD_KEY)
            .remove(THRESHOLD_STATUS_KEY)
            .remove(THRESHOLD_MODEL_HASH_KEY)
            .remove(THRESHOLD_PIPELINE_VERSION_KEY)
            .apply()
    }

    private fun requireCompatible(template: PersonFaceTemplate) {
        require(
            template.normalEmbedding.size ==
                modelConfig.embeddingDimension &&
                template.fillLightEmbedding.size ==
                modelConfig.embeddingDimension
        ) { "模板与当前256维模型不兼容" }
    }

    private fun FloatArray.toJsonArray(): JSONArray =
        JSONArray().also { values -> forEach(values::put) }

    private fun JSONArray.toFloatArray(): FloatArray =
        FloatArray(length()) { index -> getDouble(index).toFloat() }

    companion object {
        const val MAX_PERSON_COUNT = 9
        private const val PREFERENCES_NAME = "face_identity_private"
        private const val KEY_ALIAS = "smartdesk_face_templates_key_v1"
        private const val TEMPLATES_KEY = "face_templates_v3"
        private const val LEGACY_TEMPLATE_KEY = "seat_face_template"
        private const val THRESHOLD_KEY = "cosine_threshold_v3"
        private const val THRESHOLD_STATUS_KEY = "threshold_status_v3"
        private const val THRESHOLD_MODEL_HASH_KEY =
            "threshold_model_hash_v3"
        private const val THRESHOLD_PIPELINE_VERSION_KEY =
            "threshold_pipeline_version_v3"
    }
}

object FaceTemplateCollection {
    fun upsert(
        templates: List<PersonFaceTemplate>,
        template: PersonFaceTemplate,
        maxCount: Int
    ): List<PersonFaceTemplate> {
        val existingIndex = templates.indexOfFirst {
            it.personId == template.personId
        }
        if (existingIndex >= 0) {
            return templates.toMutableList().apply {
                set(existingIndex, template)
            }
        }
        require(templates.size < maxCount) {
            "最多只能注册${maxCount}名人员"
        }
        return templates + template
    }
}

data class PersonFaceTemplate(
    val personId: String,
    val normalSampleCount: Int,
    val fillLightSampleCount: Int,
    val normalEmbedding: FloatArray,
    val fillLightEmbedding: FloatArray,
    val createdAt: Long = System.currentTimeMillis()
)
