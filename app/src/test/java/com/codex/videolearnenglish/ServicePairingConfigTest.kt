package com.codex.videolearnenglish

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ServicePairingConfigTest {
    @Test fun sanitizesDeduplicatesAndOrdersPrivateRoutesFirst() {
        val urls = ServicePairingConfig.sanitizeUrls(listOf(
            "https://demo.trycloudflare.com/transcribe?token=x",
            "https://computer.tail123.ts.net/transcribe?token=x",
            "http://192.168.1.9:8766/transcribe?token=x",
            "http://127.0.0.1:8766/transcribe?token=x",
            "http://127.0.0.1:8766/transcribe?token=x"
        ))
        assertEquals("http://127.0.0.1:8766/transcribe?token=x", urls[0])
        assertEquals("http://192.168.1.9:8766/transcribe?token=x", urls[1])
        assertEquals("https://computer.tail123.ts.net/transcribe?token=x", urls[2])
        assertEquals(4, urls.size)
    }

    @Test fun rejectsUnsafeOrUnrelatedUrls() {
        assertTrue(ServicePairingConfig.sanitizeUrls(listOf("file:///tmp/a", "https://x.test/ping", "broken")).isEmpty())
        assertFalse(ServicePairingConfig.isTailscaleUrl("https://example.com/transcribe"))
        assertTrue(ServicePairingConfig.isTailscaleUrl("https://pc.example.ts.net/transcribe"))
    }
}
