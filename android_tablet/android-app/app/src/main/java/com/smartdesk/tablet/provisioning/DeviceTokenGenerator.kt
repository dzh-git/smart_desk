package com.smartdesk.tablet.provisioning

import android.util.Base64
import java.security.SecureRandom

class DeviceTokenGenerator internal constructor(
    private val randomBytes: (Int) -> ByteArray = { size ->
        ByteArray(size).also(SecureRandom()::nextBytes)
    },
    private val encoder: (ByteArray) -> String = { value ->
        Base64.encodeToString(
            value,
            Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING
        )
    }
) {
    fun generate(): String {
        return encoder(randomBytes(TOKEN_BYTES))
    }

    private companion object {
        const val TOKEN_BYTES = 32
    }
}
