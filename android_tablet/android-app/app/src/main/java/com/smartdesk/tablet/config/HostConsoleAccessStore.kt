package com.smartdesk.tablet.config

import android.content.Context
import com.smartdesk.tablet.security.LocalStringStore
import com.smartdesk.tablet.security.SecureStringStore

class HostConsoleAccessStore internal constructor(
    private val secureStore: LocalStringStore
) {
    constructor(context: Context) : this(
        SecureStringStore(
            context,
            PREFERENCES_NAME,
            KEY_ALIAS
        )
    )

    fun isAuthorized(): Boolean =
        secureStore.getString(AUTHORIZATION_KEY) == AUTHORIZED_VALUE

    fun grant() {
        secureStore.putString(AUTHORIZATION_KEY, AUTHORIZED_VALUE)
    }

    fun clear() {
        secureStore.remove(AUTHORIZATION_KEY)
    }

    private companion object {
        const val PREFERENCES_NAME = "smartdesk_host_console_access"
        const val KEY_ALIAS = "smartdesk_host_console_access_key_v1"
        const val AUTHORIZATION_KEY = "authorization"
        const val AUTHORIZED_VALUE = "granted_v1"
    }
}
