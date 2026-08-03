package com.codex.videolearnenglish

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Base64
import org.json.JSONArray
import org.json.JSONObject

class ServiceConfigReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != ServicePairingConfig.ACTION_APPLY) return
        val encoded = intent.getStringExtra(ServicePairingConfig.EXTRA_CONFIG_BASE64).orEmpty()
        val config = runCatching {
            JSONObject(String(Base64.decode(encoded, Base64.DEFAULT), Charsets.UTF_8))
        }.getOrNull() ?: return
        if (config.optInt("schema_version") != ServicePairingConfig.SCHEMA_VERSION) return
        val raw = config.optJSONArray("transcribe_urls") ?: return
        val urls = ServicePairingConfig.sanitizeUrls((0 until raw.length()).map { raw.optString(it) })
        if (urls.isEmpty()) return
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit()
            .putString(SERVICE_URL_KEY, urls.first())
            .putString(SERVICE_URL_CANDIDATES_KEY, JSONArray(urls).toString())
            .putString(CONFIG_SOURCE_KEY, "usb_adb")
            .putString(CONFIG_UPDATED_AT_KEY, config.optString("updated_at"))
            .putString(CONFIG_TAILSCALE_URL_KEY, config.optString("tailscale_url"))
            .apply()
    }

    companion object {
        private const val PREFS_NAME = "video_english_learning"
        private const val SERVICE_URL_KEY = "whisper_service_url"
        private const val SERVICE_URL_CANDIDATES_KEY = "whisper_service_url_candidates"
        private const val CONFIG_SOURCE_KEY = "service_config_source"
        private const val CONFIG_UPDATED_AT_KEY = "service_config_updated_at"
        private const val CONFIG_TAILSCALE_URL_KEY = "service_config_tailscale_url"
    }
}
