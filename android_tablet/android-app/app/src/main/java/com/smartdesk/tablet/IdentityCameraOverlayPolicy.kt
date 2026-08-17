package com.smartdesk.tablet

internal object IdentityCameraOverlayPolicy {
    const val VERIFIED_CLOSE_DELAY_MS = 750L

    fun closeDelayMs(identityStatus: String): Long? =
        VERIFIED_CLOSE_DELAY_MS.takeIf { identityStatus == "VERIFIED" }
}
