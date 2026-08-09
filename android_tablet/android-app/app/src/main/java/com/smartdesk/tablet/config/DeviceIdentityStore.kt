package com.smartdesk.tablet.config

import android.content.Context
import com.smartdesk.tablet.security.LocalStringStore
import com.smartdesk.tablet.security.SecureStringStore
import java.util.UUID

class DeviceIdentityStore internal constructor(
    private val secureStore: LocalStringStore,
    private val idFactory: () -> String = {
        "tablet-${UUID.randomUUID()}"
    }
) {
    constructor(context: Context) : this(
        SecureStringStore(
            context,
            PREFERENCES_NAME,
            KEY_ALIAS
        )
    )

    @Synchronized
    fun getOrCreate(legacyDeviceId: String? = null): String {
        secureStore.getString(DEVICE_ID_KEY)?.let { return it }
        val deviceId = legacyDeviceId
            ?.trim()
            ?.takeIf(DEVICE_ID_PATTERN::matches)
            ?: idFactory()
        require(DEVICE_ID_PATTERN.matches(deviceId)) {
            "Generated deviceId is invalid"
        }
        secureStore.putString(DEVICE_ID_KEY, deviceId)
        return deviceId
    }

    private companion object {
        val DEVICE_ID_PATTERN = Regex("[A-Za-z0-9._-]{3,64}")
        const val PREFERENCES_NAME = "smartdesk_device_identity"
        const val DEVICE_ID_KEY = "device_id"
        const val KEY_ALIAS = "smartdesk_device_identity_key_v1"
    }
}
