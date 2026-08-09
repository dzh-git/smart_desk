package com.smartdesk.tablet.config

import android.content.Context
import android.util.Base64
import com.smartdesk.tablet.security.LocalStringStore
import com.smartdesk.tablet.security.SecureStringStore
import java.security.MessageDigest
import java.security.SecureRandom
import javax.crypto.SecretKeyFactory
import javax.crypto.spec.PBEKeySpec

class MaintenancePinStore internal constructor(
    private val secureStore: LocalStringStore,
    private val randomBytes: (Int) -> ByteArray = { size ->
        ByteArray(size).also(SecureRandom()::nextBytes)
    },
    private val encoder: (ByteArray) -> String = { value ->
        Base64.encodeToString(value, Base64.NO_WRAP)
    },
    private val decoder: (String) -> ByteArray = { value ->
        Base64.decode(value, Base64.NO_WRAP)
    }
) {
    constructor(context: Context) : this(
        SecureStringStore(
            context,
            PREFERENCES_NAME,
            KEY_ALIAS
        )
    )

    fun hasPin(): Boolean = secureStore.getString(PIN_KEY) != null

    fun set(pin: String) {
        validate(pin)
        val salt = randomBytes(SALT_BYTES)
        val digest = derive(pin, salt)
        secureStore.putString(
            PIN_KEY,
            listOf(
                FORMAT,
                ITERATIONS.toString(),
                encoder(salt),
                encoder(digest)
            ).joinToString("$")
        )
    }

    fun verify(pin: String): Boolean {
        val stored = secureStore.getString(PIN_KEY) ?: return false
        val parts = stored.split("$", limit = 4)
        if (parts.size != 4 || parts[0] != FORMAT) return false
        return runCatching {
            val iterations = parts[1].toInt()
            val salt = decoder(parts[2])
            val expected = decoder(parts[3])
            val actual = derive(pin, salt, iterations)
            MessageDigest.isEqual(expected, actual)
        }.getOrDefault(false)
    }

    private fun validate(pin: String) {
        require(pin.length in 6..12 && pin.all(Char::isDigit)) {
            "Maintenance PIN must contain 6-12 digits"
        }
    }

    private fun derive(
        pin: String,
        salt: ByteArray,
        iterations: Int = ITERATIONS
    ): ByteArray {
        val spec = PBEKeySpec(pin.toCharArray(), salt, iterations, KEY_BITS)
        return try {
            SecretKeyFactory.getInstance(ALGORITHM).generateSecret(spec).encoded
        } finally {
            spec.clearPassword()
        }
    }

    private companion object {
        const val FORMAT = "pbkdf2_sha1"
        const val ALGORITHM = "PBKDF2WithHmacSHA1"
        const val ITERATIONS = 150_000
        const val KEY_BITS = 256
        const val SALT_BYTES = 16
        const val PREFERENCES_NAME = "smartdesk_maintenance_pin"
        const val PIN_KEY = "pin_verifier"
        const val KEY_ALIAS = "smartdesk_maintenance_pin_key_v1"
    }
}
