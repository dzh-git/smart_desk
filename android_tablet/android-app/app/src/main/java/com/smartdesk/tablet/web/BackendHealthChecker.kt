package com.smartdesk.tablet.web

import com.google.gson.JsonParser
import java.net.HttpURLConnection
import java.net.URL

class BackendHealthChecker(
    private val connectTimeoutMs: Int = 2_500,
    private val readTimeoutMs: Int = 2_500
) {
    enum class Result {
        HEALTHY,
        OFFLINE,
        SERVER_ERROR
    }

    fun check(serverBaseUrl: String): Result {
        val connection = try {
            URL("${serverBaseUrl.trimEnd('/')}/api/health")
                .openConnection() as HttpURLConnection
        } catch (_: Exception) {
            return Result.OFFLINE
        }
        return try {
            connection.requestMethod = "GET"
            connection.connectTimeout = connectTimeoutMs
            connection.readTimeout = readTimeoutMs
            connection.useCaches = false
            connection.setRequestProperty("Accept", "application/json")
            val statusCode = connection.responseCode
            if (statusCode !in 200..299) {
                Result.SERVER_ERROR
            } else {
                val body = connection.inputStream.bufferedReader(
                    Charsets.UTF_8
                ).use { reader ->
                    reader.readText().take(MAX_HEALTH_BODY_CHARS)
                }
                if (isHealthyResponse(statusCode, body)) {
                    Result.HEALTHY
                } else {
                    Result.SERVER_ERROR
                }
            }
        } catch (_: Exception) {
            Result.OFFLINE
        } finally {
            connection.disconnect()
        }
    }

    companion object {
        private const val MAX_HEALTH_BODY_CHARS = 4_096

        fun isHealthyResponse(statusCode: Int, body: String): Boolean {
            if (statusCode !in 200..299) {
                return false
            }
            return runCatching {
                JsonParser.parseString(body)
                    .asJsonObject
                    .get("status")
                    ?.asString == "ok"
            }.getOrDefault(false)
        }
    }
}
