package com.smartdesk.tablet.recognition

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import org.json.JSONObject
import java.security.KeyFactory
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.spec.MGF1ParameterSpec
import java.security.spec.X509EncodedKeySpec
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.OAEPParameterSpec
import javax.crypto.spec.PSource

class FaceTransportCrypto {
    private val keyStore = KeyStore.getInstance("AndroidKeyStore").apply {
        load(null)
    }

    fun publicKeyPem(): String {
        ensureKeyPair()
        val encoded = keyStore.getCertificate(KEY_ALIAS).publicKey.encoded
        val body = Base64.encodeToString(encoded, Base64.NO_WRAP)
            .chunked(64)
            .joinToString("\n")
        return "-----BEGIN PUBLIC KEY-----\n$body\n-----END PUBLIC KEY-----\n"
    }

    fun encryptForServer(payload: JSONObject, publicKeyPem: String): JSONObject {
        val cleaned = publicKeyPem
            .replace("-----BEGIN PUBLIC KEY-----", "")
            .replace("-----END PUBLIC KEY-----", "")
            .replace(Regex("\\s"), "")
        val publicKey = KeyFactory.getInstance("RSA").generatePublic(
            X509EncodedKeySpec(Base64.decode(cleaned, Base64.DEFAULT))
        )
        val aesKey = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        val nonce = ByteArray(12).also(java.security.SecureRandom()::nextBytes)
        val aes = Cipher.getInstance("AES/GCM/NoPadding")
        aes.init(Cipher.ENCRYPT_MODE, aesKey, GCMParameterSpec(128, nonce))
        aes.updateAAD(AAD)
        val ciphertext = aes.doFinal(payload.toString().toByteArray(Charsets.UTF_8))
        val rsa = rsaCipher(Cipher.ENCRYPT_MODE, publicKey)
        val encryptedKey = rsa.doFinal(aesKey.encoded)
        return JSONObject()
            .put("algorithm", "RSA-OAEP-256+A256GCM")
            .put("encryptedKey", encode(encryptedKey))
            .put("nonce", encode(nonce))
            .put("ciphertext", encode(ciphertext))
    }

    fun decryptFromServer(envelope: JSONObject): JSONObject {
        require(
            envelope.optString("algorithm") == "RSA-OAEP-256+A256GCM"
        ) { "中央模板包加密算法不受支持" }
        ensureKeyPair()
        val privateKey = keyStore.getKey(KEY_ALIAS, null)
        val rsa = rsaCipher(Cipher.DECRYPT_MODE, privateKey)
        val aesKeyBytes = rsa.doFinal(decode(envelope.getString("encryptedKey")))
        val aesKey = javax.crypto.spec.SecretKeySpec(aesKeyBytes, "AES")
        val aes = Cipher.getInstance("AES/GCM/NoPadding")
        aes.init(
            Cipher.DECRYPT_MODE,
            aesKey,
            GCMParameterSpec(128, decode(envelope.getString("nonce")))
        )
        aes.updateAAD(AAD)
        val plaintext = aes.doFinal(decode(envelope.getString("ciphertext")))
        return JSONObject(String(plaintext, Charsets.UTF_8))
    }

    private fun ensureKeyPair() {
        if (keyStore.containsAlias(KEY_ALIAS)) return
        KeyPairGenerator.getInstance(
            KeyProperties.KEY_ALGORITHM_RSA,
            "AndroidKeyStore"
        ).apply {
            initialize(
                KeyGenParameterSpec.Builder(
                    KEY_ALIAS,
                    KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT
                )
                    .setKeySize(2048)
                    .setDigests(KeyProperties.DIGEST_SHA256, KeyProperties.DIGEST_SHA512)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_RSA_OAEP)
                    .build()
            )
        }.generateKeyPair()
    }

    private fun rsaCipher(mode: Int, key: java.security.Key): Cipher =
        Cipher.getInstance("RSA/ECB/OAEPPadding").apply {
            init(
                mode,
                key,
                OAEPParameterSpec(
                    "SHA-256",
                    "MGF1",
                    MGF1ParameterSpec.SHA256,
                    PSource.PSpecified.DEFAULT
                )
            )
        }

    private fun encode(value: ByteArray): String =
        Base64.encodeToString(value, Base64.NO_WRAP)

    private fun decode(value: String): ByteArray =
        Base64.decode(value, Base64.DEFAULT)

    private companion object {
        const val KEY_ALIAS = "smartdesk_face_transport_key_v1"
        val AAD = "smartdesk-face-template-v1".toByteArray(Charsets.UTF_8)
    }
}
