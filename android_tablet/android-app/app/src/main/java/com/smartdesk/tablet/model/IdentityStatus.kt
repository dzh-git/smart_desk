package com.smartdesk.tablet.model

data class IdentityStatus(
    val mode: String,
    val status: String,
    val personId: String? = null,
    val sampleCount: Int = 0,
    val requiredSamples: Int = 10,
    val captureStage: String = "NONE",
    val stageSampleCount: Int = 0,
    val stageRequiredSamples: Int = 5,
    val registeredCount: Int = 0,
    val similarity: Float? = null,
    val threshold: Float? = null,
    val top1PersonId: String? = null,
    val top1Score: Float? = null,
    val top2PersonId: String? = null,
    val top2Score: Float? = null,
    val margin: Float? = null,
    val thresholdStatus: String = "CALIBRATION_PENDING",
    val verificationLevel: String = "NONE",
    val modelVersion: String? = null,
    val matchStreak: Int = 0,
    val rejectStreak: Int = 0,
    val processingTimeMs: Long? = null,
    val message: String
)
