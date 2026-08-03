package com.codex.videolearnenglish

import java.net.URI

object ServicePairingConfig {
    const val ACTION_APPLY = "com.codex.videolearnenglish.APPLY_SERVICE_CONFIG"
    const val EXTRA_CONFIG_BASE64 = "config_base64"
    const val SCHEMA_VERSION = 1

    fun sanitizeUrls(urls: Iterable<String>): List<String> = urls
        .map { it.trim() }
        .filter { isAllowedTranscribeUrl(it) }
        .distinct()
        .sortedBy(::priority)

    fun isTailscaleUrl(url: String): Boolean = runCatching {
        URI(url).host.orEmpty().lowercase().endsWith(".ts.net")
    }.getOrDefault(false)

    private fun isAllowedTranscribeUrl(url: String): Boolean = runCatching {
        val uri = URI(url)
        val scheme = uri.scheme.orEmpty().lowercase()
        val host = uri.host.orEmpty()
        (scheme == "http" || scheme == "https") && host.isNotBlank() &&
            uri.path.trimEnd('/') == "/transcribe" && uri.rawUserInfo == null
    }.getOrDefault(false)

    private fun priority(url: String): Int {
        val lower = url.lowercase()
        return when {
            lower.contains("127.0.0.1") || lower.contains("10.0.2.2") -> 0
            lower.startsWith("http://192.168.") || lower.startsWith("http://10.") || lower.startsWith("http://172.") -> 1
            isTailscaleUrl(url) -> 2
            lower.startsWith("http://") -> 3
            lower.startsWith("https://") -> 4
            else -> 5
        }
    }
}
