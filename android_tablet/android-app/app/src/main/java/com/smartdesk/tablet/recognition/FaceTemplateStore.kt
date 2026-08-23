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
        reconcileDefaultHostIdentity(updated)
    }

    @Synchronized
    fun replaceManagedMeeting(
        meetingId: Int,
        revision: Int,
        templates: List<PersonFaceTemplate>,
        threshold: Float,
        thresholdStatus: ThresholdStatus,
        modelHash: String,
        pipelineVersion: Int
    ) {
        require(templates.size == 1) {
            "席位验证模板包必须只包含当前分配人员"
        }
        require(templates.map { it.personId }.distinct().size == templates.size) {
            "会议模板人员编号不能重复"
        }
        require(modelHash == modelConfig.modelSha256) {
            "中央模板模型与当前应用不兼容"
        }
        require(pipelineVersion == modelConfig.pipelineVersion) {
            "中央模板处理流水线与当前应用不兼容"
        }
        templates.forEach(::requireCompatible)
        saveAll(templates, clearManagedMeeting = false)
        preferences.edit()
            .putFloat(THRESHOLD_KEY, threshold)
            .putString(THRESHOLD_STATUS_KEY, thresholdStatus.name)
            .putString(THRESHOLD_MODEL_HASH_KEY, modelHash)
            .putInt(THRESHOLD_PIPELINE_VERSION_KEY, pipelineVersion)
            .putInt(MANAGED_MEETING_ID_KEY, meetingId)
            .putInt(MANAGED_REVISION_KEY, revision)
            .apply()
    }

    fun managedMeetingId(): Int =
        preferences.getInt(MANAGED_MEETING_ID_KEY, -1)

    fun managedRevision(): Int =
        preferences.getInt(MANAGED_REVISION_KEY, -1)

    @Synchronized
    fun remove(personId: String): Boolean {
        val current = loadAll()
        val updated = current.filterNot { it.personId == personId }
        if (updated.size == current.size) {
            return false
        }
        saveAll(updated)
        reconcileDefaultHostIdentity(updated)
        return true
    }

    @Synchronized
    fun clearAll() {
        secureStore.remove(TEMPLATES_KEY)
        secureStore.remove(DEFAULT_HOST_PERSON_KEY)
        preferences.edit()
            .remove(LEGACY_TEMPLATE_KEY)
            .remove(MANAGED_MEETING_ID_KEY)
            .remove(MANAGED_REVISION_KEY)
            .apply()
    }

    @Synchronized
    fun defaultHostPersonId(): String? {
        val templates = loadAll()
        val current = secureStore.getString(DEFAULT_HOST_PERSON_KEY)
        val resolved = HostIdentityDefaultPolicy.resolve(
            current,
            templates.map(PersonFaceTemplate::personId)
        )
        if (resolved != current) {
            if (resolved == null) {
                secureStore.remove(DEFAULT_HOST_PERSON_KEY)
            } else {
                secureStore.putString(DEFAULT_HOST_PERSON_KEY, resolved)
            }
        }
        return resolved
    }

    @Synchronized
    fun setDefaultHostPersonId(personId: String?): String? {
        val normalized = personId?.trim()?.takeIf(String::isNotEmpty)
        if (normalized == null) {
            secureStore.remove(DEFAULT_HOST_PERSON_KEY)
            return defaultHostPersonId()
        }
        require(loadAll().any { it.personId == normalized }) {
            "默认主持人必须使用已注册的本机模板"
        }
        secureStore.putString(DEFAULT_HOST_PERSON_KEY, normalized)
        return normalized
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

    private fun saveAll(
        templates: List<PersonFaceTemplate>,
        clearManagedMeeting: Boolean = true
    ) {
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
        preferences.edit().apply {
            remove(LEGACY_TEMPLATE_KEY)
            if (clearManagedMeeting) {
                remove(MANAGED_MEETING_ID_KEY)
                remove(MANAGED_REVISION_KEY)
            }
        }.apply()
    }

    private fun requireCompatible(template: PersonFaceTemplate) {
        require(
            template.normalEmbedding.size ==
                modelConfig.embeddingDimension &&
                template.fillLightEmbedding.size ==
                modelConfig.embeddingDimension
        ) { "模板与当前256维模型不兼容" }
    }

    private fun reconcileDefaultHostIdentity(
        templates: List<PersonFaceTemplate>
    ) {
        val current = secureStore.getString(DEFAULT_HOST_PERSON_KEY)
        val resolved = HostIdentityDefaultPolicy.resolve(
            current,
            templates.map(PersonFaceTemplate::personId)
        )
        if (resolved == null) {
            secureStore.remove(DEFAULT_HOST_PERSON_KEY)
        } else {
            secureStore.putString(DEFAULT_HOST_PERSON_KEY, resolved)
        }
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
        private const val MANAGED_MEETING_ID_KEY = "managed_meeting_id_v1"
        private const val MANAGED_REVISION_KEY = "managed_revision_v1"
        private const val DEFAULT_HOST_PERSON_KEY = "default_host_person_v1"
    }
}

object HostIdentityDefaultPolicy {
    fun resolve(current: String?, registeredPersonIds: List<String>): String? =
        when {
            registeredPersonIds.isEmpty() -> null
            current != null && current in registeredPersonIds -> current
            registeredPersonIds.size == 1 -> registeredPersonIds.single()
            else -> null
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
