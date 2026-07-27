package com.smartdesk.tablet.config

import android.content.Context
import android.util.Log

class DeviceConfigStore(context: Context) {
    private val preferences = context.getSharedPreferences(
        PREFERENCES_NAME,
        Context.MODE_PRIVATE
    )

    fun load(): DeviceConfig? {
        val raw = preferences.getString(CONFIG_KEY, null) ?: return null
        return runCatching { DeviceConfig.parse(raw) }
            .onFailure {
                Log.e(TAG, "Ignoring invalid stored device configuration", it)
            }
            .getOrNull()
    }

    fun save(json: String): DeviceConfig {
        val config = DeviceConfig.parse(json)
        check(
            preferences.edit()
                .putString(CONFIG_KEY, config.toJson().toString())
                .commit()
        ) {
            "Failed to persist device configuration"
        }
        return config
    }

    private companion object {
        const val TAG = "SmartDeskTablet"
        const val PREFERENCES_NAME = "smartdesk_device_config"
        const val CONFIG_KEY = "config"
    }
}
