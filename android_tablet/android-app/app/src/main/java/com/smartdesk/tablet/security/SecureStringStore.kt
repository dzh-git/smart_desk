package com.smartdesk.tablet.security

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import android.util.Log
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

interface LocalStringStore {
    fun getString(key: String): String?
    fun putString(key: String, value: String)
    fun remove(key: String)
}

/**
 * AES-GCM string storage backed by a non-exportable Android Keystore key.
 *
 * Legacy plaintext values are migrated on first successful read. Corrupt or
 * undecryptable values fail closed and are never returned as plaintext.
 */
class SecureStringStore(
    context: Context,
    preferencesName: String,
    private val keyAlias: String
) : LocalStringStore {
    private val preferences = context.getSharedPreferences(
        preferencesName,
        Context.MODE_PRIVATE
    )

    @Synchronized
    override fun getString(key: String): String? {
        val stored = preferences.getString(key, null) ?: return null
        if (!stored.startsWith(ENCRYPTED_PREFIX)) {
            putString(key, stored)
            return stored
        }
        return runCatching { decrypt(stored) }
            .onFailure {
                Log.e(TAG, "Encrypted local value could not be read", it)
            }
            .getOrNull()
    }

    @Synchronized
    override fun putString(key: String, value: String) {
        val encrypted = encrypt(value)
        check(preferences.edit().putString(key, encrypted).commit()) {
            "Failed to persist encrypted local value"
        }
    }

    @Synchronized
    override fun remove(key: String) {
        preferences.edit().remove(key).apply()
    }

    private fun encrypt(value: String): String {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, secretKey())
        val ciphertext = cipher.doFinal(value.toByteArray(Charsets.UTF_8))
        return listOf(
            ENCRYPTED_PREFIX.removeSuffix(":"),
            Base64.encodeToString(cipher.iv, Base64.NO_WRAP),
            Base64.encodeToString(ciphertext, Base64.NO_WRAP)
        ).joinToString(":")
    }

    private fun decrypt(value: String): String {
        val parts = value.split(":", limit = 3)
        require(parts.size == 3 && parts[0] == "enc-v1") {
            "Unsupported encrypted value format"
        }
        val iv = Base64.decode(parts[1], Base64.NO_WRAP)
        val ciphertext = Base64.decode(parts[2], Base64.NO_WRAP)
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(
            Cipher.DECRYPT_MODE,
            secretKey(),
            GCMParameterSpec(GCM_TAG_BITS, iv)
        )
        return cipher.doFinal(ciphertext).toString(Charsets.UTF_8)
    }

    private fun secretKey(): SecretKey {
        val keyStore = KeyStore.getInstance(ANDROID_KEY_STORE).apply {
            load(null)
        }
        (keyStore.getKey(keyAlias, null) as? SecretKey)?.let {
            return it
        }

        return KeyGenerator.getInstance(
            KeyProperties.KEY_ALGORITHM_AES,
            ANDROID_KEY_STORE
        ).run {
            init(
                KeyGenParameterSpec.Builder(
                    keyAlias,
                    KeyProperties.PURPOSE_ENCRYPT or
                        KeyProperties.PURPOSE_DECRYPT
                )
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(
                        KeyProperties.ENCRYPTION_PADDING_NONE
                    )
                    .setRandomizedEncryptionRequired(true)
                    .build()
            )
            generateKey()
        }
    }

    private companion object {
        const val TAG = "SmartDeskSecureStore"
        const val ANDROID_KEY_STORE = "AndroidKeyStore"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        const val GCM_TAG_BITS = 128
        const val ENCRYPTED_PREFIX = "enc-v1:"
    }
}
