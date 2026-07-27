package com.smartdesk.tablet.config

import android.content.Context
import android.util.Log
import com.smartdesk.tablet.security.SecureStringStore

class DeviceConfigStore(context: Context) {
    private val secureStore = SecureStringStore(
        context,
        PREFERENCES_NAME,
        KEY_ALIAS
    )

    fun load(): DeviceConfig? {
        val raw = secureStore.getString(CONFIG_KEY) ?: return null
        return runCatching { DeviceConfig.parse(raw) }
            .onFailure {
                Log.e(TAG, "Ignoring invalid stored device configuration", it)
            }
            .getOrNull()
    }

    fun save(json: String): DeviceConfig {
        val config = DeviceConfig.parse(
            json,
            fallbackDeviceToken = load()?.deviceToken
        )
        secureStore.putString(
            CONFIG_KEY,
            config.toJson(includeSecret = true).toString()
        )
        return config
    }

    private companion object {
        const val TAG = "SmartDeskTablet"
        const val PREFERENCES_NAME = "smartdesk_device_config"
        const val CONFIG_KEY = "config"
        const val KEY_ALIAS = "smartdesk_device_config_key_v1"
    }
}
